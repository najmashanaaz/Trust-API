"""
backend/database.py
───────────────────
PURPOSE:
    This module handles EVERYTHING related to the SQLite database.
    It is the only place in the project that talks directly to the database.
    No other file should import sqlite3 — they all go through these functions.

DATABASE SCHEMA (two tables):
    apis
        id        — auto-incrementing primary key
        api_name  — human-readable name, e.g. "OpenAI"
        api_url   — the URL we send a GET request to

    api_logs
        id              — auto-incrementing primary key for each log row
        api_id          — foreign key → apis.id
        status          — "UP" or "DOWN"
        response_time   — milliseconds the request took (NULL if DOWN/error)
        http_status_code— actual HTTP response code (200, 503, etc.); NULL on connection failure
        error_message   — real exception text on failure; NULL on success
        checked_at      — ISO-8601 UTC timestamp of when the check ran
"""

import sqlite3
import os
from datetime import datetime

# ── Path to the database file ─────────────────────────────────────────────────
DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "database", "monitor.db")
)


# ── Connection helper ─────────────────────────────────────────────────────────
def get_connection() -> sqlite3.Connection:
    """
    Opens and returns a connection to the SQLite database.
    check_same_thread=False is required because the monitoring thread and
    the FastAPI request threads both access the same database.
    We also enable WAL journal mode for better concurrent read/write performance.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    # WAL mode allows concurrent reads while a write is in progress —
    # critical when the monitoring service is writing and the web server is reading.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Table creation ────────────────────────────────────────────────────────────
def init_db():
    """
    Creates the database tables if they don't already exist.
    Safe to call on every startup — uses IF NOT EXISTS.
    Also calls migrate_db() to add new columns to existing databases.
    """
    # Ensure the database directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    # ── Table: apis ──────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS apis (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT    NOT NULL,
            api_url  TEXT    NOT NULL UNIQUE
        )
    """)

    # ── Table: api_logs ──────────────────────────────────────────────────────
    # Full schema with all columns including the new http_status_code and error_message.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_logs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id           INTEGER NOT NULL,
            status           TEXT    NOT NULL,
            response_time    REAL,
            http_status_code INTEGER,
            error_message    TEXT,
            checked_at       TEXT    NOT NULL,
            FOREIGN KEY (api_id) REFERENCES apis(id) ON DELETE CASCADE
        )
    """)
    # ── Table: users ─────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        )
    """)

    # ── Table: watchlist ──────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            api_id     INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (api_id)  REFERENCES apis(id)  ON DELETE CASCADE,
            UNIQUE(user_id, api_id)
        )
    """)

    # Index on (api_id, checked_at) dramatically speeds up history and stats queries.
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_api_logs_api_id_checked_at
        ON api_logs (api_id, checked_at DESC)
    """)

    # ── Table: api_backup_config ──────────────────────────────────────────────
    # Stores which backup API should be activated when a primary fails over.
    # priority: lower number = higher priority (tried first).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_backup_config (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            primary_api_id INTEGER NOT NULL,
            backup_api_id  INTEGER NOT NULL,
            priority       INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (primary_api_id) REFERENCES apis(id) ON DELETE CASCADE,
            FOREIGN KEY (backup_api_id)  REFERENCES apis(id) ON DELETE CASCADE
        )
    """)

    # ── Table: api_failover_state ─────────────────────────────────────────────
    # One row per monitored API; tracks live failover state and counters.
    # current_status: 'ACTIVE' (primary serving) or 'FAILED_OVER' (backup serving).
    # active_backup_id: NULL when ACTIVE; set to the backup api_id when FAILED_OVER.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_failover_state (
            api_id               INTEGER PRIMARY KEY,
            current_status       TEXT    NOT NULL DEFAULT 'ACTIVE',
            active_backup_id     INTEGER,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            consecutive_successes INTEGER NOT NULL DEFAULT 0,
            last_state_change    TEXT,
            FOREIGN KEY (api_id)           REFERENCES apis(id) ON DELETE CASCADE,
            FOREIGN KEY (active_backup_id) REFERENCES apis(id) ON DELETE SET NULL
        )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Database initialised at: {DB_PATH}")

    # Migrate any existing database to include new columns
    migrate_db()


def migrate_db():
    """
    Safely adds new columns to an existing api_logs table if they are missing.
    This allows upgrading an already-running database without losing history.

    Uses ALTER TABLE ... ADD COLUMN which is always safe in SQLite:
    if the column already exists it raises an OperationalError which we catch
    and ignore.
    """
    conn = get_connection()
    cursor = conn.cursor()

    migrations = [
        ("http_status_code", "ALTER TABLE api_logs ADD COLUMN http_status_code INTEGER"),
        ("error_message",    "ALTER TABLE api_logs ADD COLUMN error_message TEXT"),
        ("category",         "ALTER TABLE apis ADD COLUMN category TEXT"),
    ]

    for col_name, sql in migrations:
        try:
            cursor.execute(sql)
            conn.commit()
            print(f"[DB] Migration: added column '{col_name}' to api_logs.")
        except sqlite3.OperationalError:
            # Column already exists — nothing to do.
            pass

    conn.close()


# ── Sync APIs ─────────────────────────────────────────────────────────────────
def sync_apis(api_list: list[dict]):
    """
    Synchronizes the database with the configured list of APIs.
    - Removes API records (and their logs via CASCADE) not in the new list.
    - Inserts new APIs that aren't already tracked.
    - Never modifies existing rows so historical data is preserved.
    """
    conn = get_connection()
    cursor = conn.cursor()

    target_urls = {api["url"] for api in api_list}

    cursor.execute("SELECT id, api_url FROM apis")
    current_rows = cursor.fetchall()

    pruned_count = 0
    for row_id, api_url in current_rows:
        if api_url not in target_urls:
            cursor.execute("DELETE FROM api_logs WHERE api_id = ?", (row_id,))
            cursor.execute("DELETE FROM apis WHERE id = ?", (row_id,))
            pruned_count += 1

    if pruned_count > 0:
        print(f"[DB] Removed {pruned_count} deprecated API(s) and their logs.")

    inserted_count = 0
    for api in api_list:
        cursor.execute("SELECT id FROM apis WHERE api_url = ?", (api["url"],))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO apis (api_name, api_url, category) VALUES (?, ?, ?)",
                (api["name"], api["url"], api.get("category"))
            )
            inserted_count += 1
        else:
            # Update category in case it was added to an existing row
            cursor.execute(
                "UPDATE apis SET category = ? WHERE api_url = ?",
                (api.get("category"), api["url"])
            )

    conn.commit()
    conn.close()

    if inserted_count > 0:
        print(f"[DB] Added {inserted_count} new API(s) to monitoring.")
    print("[DB] API list synchronization complete.")


# ── Read: all APIs ────────────────────────────────────────────────────────────
def get_all_apis() -> list[dict]:
    """
    Returns every row in the `apis` table as a list of dicts.

    Return format:
        [{"id": 1, "api_name": "OpenAI", "api_url": "https://..."}, ...]
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, api_name, api_url, category FROM apis ORDER BY id")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# ── Write: log a single check ─────────────────────────────────────────────────
def log_check(
    api_id: int,
    status: str,
    response_time: float | None,
    http_status_code: int | None = None,
    error_message: str | None = None,
):
    """
    Inserts one row into `api_logs` after each health check.

    Parameters:
        api_id           — id from the `apis` table
        status           — "UP" or "DOWN"
        response_time    — milliseconds; None on total connection failure
        http_status_code — real HTTP code from the server; None if no response reached
        error_message    — real Python exception string on failure; None on success

    Every call appends a new row. Historical data is NEVER overwritten.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO api_logs
            (api_id, status, response_time, http_status_code, error_message, checked_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            api_id,
            status,
            response_time,
            http_status_code,
            error_message,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


# ── Read: latest check for ALL APIs ──────────────────────────────────────────
def get_latest_check_for_all_apis() -> list[dict]:
    """
    Returns the single most-recent log row for EVERY monitored API in one query.

    This is what the FastAPI /api/status endpoint uses.
    It reads purely from the database — no in-memory state.

    Return format:
        [
          {
            "api_id":          1,
            "api_name":        "OpenAI",
            "api_url":         "https://status.openai.com",
            "status":          "UP",
            "response_time":   312.4,
            "http_status_code": 200,
            "error_message":   null,
            "checked_at":      "2024-07-06T11:00:00.123456"
          },
          ...
        ]

    APIs that have never been checked will appear with status=None (no log row yet).
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # LEFT JOIN ensures APIs with zero log rows still appear in the result.
    # The subquery selects only the most recent log row per api_id.
    cursor.execute("""
        SELECT
            a.id              AS api_id,
            a.api_name,
            a.api_url,
            l.status,
            l.response_time,
            l.http_status_code,
            l.error_message,
            l.checked_at
        FROM apis a
        LEFT JOIN api_logs l
            ON l.id = (
                SELECT id FROM api_logs
                WHERE api_id = a.id
                ORDER BY checked_at DESC
                LIMIT 1
            )
        ORDER BY a.id
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# ── Read: logs for one API ────────────────────────────────────────────────────
def get_logs_for_api(api_id: int, limit: int = 50) -> list[dict]:
    """
    Returns the most recent `limit` log rows for a specific API.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, api_id, status, response_time, http_status_code, error_message, checked_at
        FROM api_logs
        WHERE api_id = ?
        ORDER BY checked_at DESC
        LIMIT ?
        """,
        (api_id, limit),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# ── Read: aggregate stats for one API ────────────────────────────────────────
def get_stats_for_api(api_id: int) -> dict:
    """
    Returns aggregate statistics for one API across ALL its stored log rows.
    Used by monitor.py to calculate the reliability score.

    Return:
        {
            "total_checks":    144,
            "successful":      140,
            "failed":            4,
            "avg_response_ms": 231.8,
            "p95_latency_ms":  520.3
        }
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*)                                          AS total_checks,
            SUM(CASE WHEN status = 'UP'   THEN 1 ELSE 0 END) AS successful,
            SUM(CASE WHEN status = 'DOWN' THEN 1 ELSE 0 END) AS failed,
            AVG(response_time)                                AS avg_response_ms
        FROM api_logs
        WHERE api_id = ?
        """,
        (api_id,),
    )
    row = dict(cursor.fetchone())
    conn.close()

    row["total_checks"]    = row["total_checks"]    or 0
    row["successful"]      = row["successful"]      or 0
    row["failed"]          = row["failed"]          or 0
    row["avg_response_ms"] = row["avg_response_ms"] or 0.0
    row["p95_latency_ms"]  = get_p95_latency(api_id)

    return row


# ── Read: p95 latency for one API ─────────────────────────────────────────────
def get_p95_latency(api_id: int) -> float:
    """
    Calculates the 95th-percentile response time for a given API
    using all stored successful (UP) check records.

    SQLite has no built-in PERCENTILE_CONT function, so we implement it
    manually: sort all response_time values ascending, then pick the
    value at the 95th-percentile row index.

    Returns 0.0 if there is no data.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT response_time
        FROM api_logs
        WHERE api_id = ?
          AND response_time IS NOT NULL
        ORDER BY response_time ASC
        """,
        (api_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return 0.0

    # rows is a list of single-element tuples: [(123.4,), (234.5,), ...]
    times = [r[0] for r in rows]
    n = len(times)

    # p95 index: use ceiling so we don't under-estimate on small datasets
    import math
    idx = min(math.ceil(n * 0.95) - 1, n - 1)
    return round(times[idx], 2)


# ── User and Watchlist Database Helpers ────────────────────────────────────────

def create_user(email: str, password_hash: str) -> int:
    """Inserts a new user into the database and returns the generated user ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
        (email, password_hash, datetime.utcnow().isoformat())
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return user_id


def get_user_by_email(email: str) -> dict | None:
    """Retrieves a user dictionary by email, or None if not found."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password_hash, created_at FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    """Retrieves a user dictionary by ID, or None if not found."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, email, password_hash, created_at FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def add_to_watchlist(user_id: int, api_id: int) -> None:
    """Adds an API to the user's watchlist."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, api_id) VALUES (?, ?)",
            (user_id, api_id)
        )
        conn.commit()
    finally:
        conn.close()


def remove_from_watchlist(user_id: int, api_id: int) -> None:
    """Removes an API from the user's watchlist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND api_id = ?",
        (user_id, api_id)
    )
    conn.commit()
    conn.close()


def get_watchlist(user_id: int) -> list[dict]:
    """
    Returns API information for all APIs in a user's watchlist.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.id, a.api_name, a.api_url
        FROM apis a
        JOIN watchlist w ON a.id = w.api_id
        WHERE w.user_id = ?
        ORDER BY a.id
    """, (user_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_users_watching_api(api_id: int) -> list[dict]:
    """
    Returns a list of users (id, email) watching a specific API.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.id, u.email
        FROM users u
        JOIN watchlist w ON u.id = w.user_id
        WHERE w.api_id = ?
    """, (api_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows




# ── Failover: read highest-priority backup for an API ─────────────────────────
def get_backup_for_api(api_id: int) -> dict | None:
    """
    Returns the highest-priority backup config row for the given primary API,
    or None if no backup has been configured.

    'Highest priority' means the row with the lowest `priority` number.
    If two rows share the same priority, the one with the lower id wins.

    Return format:
        {"id": 1, "primary_api_id": 2, "backup_api_id": 5, "priority": 1}
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, primary_api_id, backup_api_id, priority
        FROM api_backup_config
        WHERE primary_api_id = ?
        ORDER BY priority ASC, id ASC
        LIMIT 1
        """,
        (api_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Failover: read current failover state for one API ─────────────────────────
def get_failover_state(api_id: int) -> dict | None:
    """
    Returns the api_failover_state row for the given API as a dict,
    or None if no row exists yet (API has never been evaluated for failover).

    Return format:
        {
            "api_id": 3,
            "current_status": "ACTIVE",
            "active_backup_id": None,
            "consecutive_failures": 0,
            "consecutive_successes": 2,
            "last_state_change": "2026-07-08T12:00:00.000000"
        }
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT api_id, current_status, active_backup_id,
               consecutive_failures, consecutive_successes, last_state_change
        FROM api_failover_state
        WHERE api_id = ?
        """,
        (api_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Failover: insert or replace the full failover state row ───────────────────
def upsert_failover_state(
    api_id: int,
    current_status: str,
    active_backup_id: int | None,
    consecutive_failures: int,
    consecutive_successes: int,
) -> None:
    """
    Inserts or replaces the api_failover_state row for the given API.
    Sets last_state_change to the current UTC timestamp on every call.

    Using INSERT OR REPLACE (UPSERT) means the caller never needs to check
    whether a row already exists — this is always safe to call.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO api_failover_state
            (api_id, current_status, active_backup_id,
             consecutive_failures, consecutive_successes, last_state_change)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            api_id,
            current_status,
            active_backup_id,
            consecutive_failures,
            consecutive_successes,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


# ── Failover: add a backup config entry ───────────────────────────────────────
def add_backup_config(primary_id: int, backup_id: int, priority: int = 1) -> int:
    """
    Inserts a row into api_backup_config linking a primary API to a backup API.

    Parameters:
        primary_id — the api_id of the primary (the one being monitored)
        backup_id  — the api_id to activate when the primary fails over
        priority   — lower number = higher priority (default 1)

    Returns the new row id.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO api_backup_config (primary_api_id, backup_api_id, priority)
        VALUES (?, ?, ?)
        """,
        (primary_id, backup_id, priority),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


# ── Failover: read all APIs with their current failover state ─────────────────
def get_all_failover_status() -> list[dict]:
    """
    Returns every API joined with its current failover state.
    APIs that have no failover state row yet appear with ACTIVE defaults.

    Used by the GET /api/failover-status dashboard endpoint.

    Return format:
        [
          {
            "api_id": 1,
            "api_name": "OpenAI",
            "api_url": "https://...",
            "current_status": "ACTIVE",
            "active_backup_id": None
          },
          ...
        ]
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            a.id                                          AS api_id,
            a.api_name,
            a.api_url,
            COALESCE(f.current_status, 'ACTIVE')          AS current_status,
            f.active_backup_id
        FROM apis a
        LEFT JOIN api_failover_state f ON a.id = f.api_id
        ORDER BY a.id
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# ── Backup config: read all rows with resolved API names ──────────────────────
def get_all_backup_configs() -> list[dict]:
    """
    Returns every row in api_backup_config joined with the api_name for both
    the primary and backup API.

    Return format:
        [
          {
            "id": 1,
            "primary_api_id": 1,
            "primary_name": "OpenAI",
            "backup_api_id": 2,
            "backup_name": "Google Cloud",
            "priority": 1
          },
          ...
        ]
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            c.id,
            c.primary_api_id,
            p.api_name   AS primary_name,
            c.backup_api_id,
            b.api_name   AS backup_name,
            c.priority
        FROM api_backup_config c
        JOIN apis p ON c.primary_api_id = p.id
        JOIN apis b ON c.backup_api_id  = b.id
        ORDER BY c.primary_api_id, c.priority ASC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# ── Backup config: delete a single row by id ──────────────────────────────────
def delete_backup_config(config_id: int) -> bool:
    """
    Deletes the api_backup_config row with the given id.

    Returns True if a row was actually deleted, False if the id did not exist.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM api_backup_config WHERE id = ?",
        (config_id,),
    )
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted
