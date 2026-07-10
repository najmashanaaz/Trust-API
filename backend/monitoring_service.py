"""
backend/monitoring_service.py
──────────────────────────────
PURPOSE:
    Standalone monitoring process that runs 24/7, completely independent
    of the FastAPI web server.

    This is the RECOMMENDED way to run monitoring in production.

OPERATION:
    1. Initialises the SQLite database (creates tables if missing, migrates schema).
    2. Syncs the list of monitored APIs into the database.
    3. Runs an immediate first check so the dashboard has data right away.
    4. Starts APScheduler to repeat checks every 5 minutes indefinitely.
    5. Keeps the process alive; handles Ctrl+C for clean shutdown.

USAGE (from the project root directory):
    python run_monitor.py

    OR directly:
    python -m backend.monitoring_service

IMPORTANT:
    This process should run in its own terminal window (or be managed by
    a process supervisor like systemd/PM2 in production).
    The FastAPI server (uvicorn backend.main:app) should run separately.
    Both read from / write to the same SQLite database file.
"""

import sys
import os
import time
import logging

# ── Ensure the project root is on sys.path so relative imports work ───────────
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_project_root, ".env"))  # Load .env before any os.environ reads

from backend.database import init_db, migrate_db, sync_apis
from backend.apis import APIS_TO_MONITOR
from backend.monitor import run_all_checks, create_scheduler, CHECK_INTERVAL_MINUTES

# ── Logging configuration ─────────────────────────────────────────────────────
# APScheduler's own logs are verbose at DEBUG; keep them at WARNING.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

BANNER = """
╔══════════════════════════════════════════════════════════════════╗
║        TrustAPI  —  Monitoring Service  v2.0                    ║
║  Checks every {interval} minutes  |  Writes only real data to DB  ║
╚══════════════════════════════════════════════════════════════════╝
""".format(interval=CHECK_INTERVAL_MINUTES)


def main():
    """
    Entry point for the standalone monitoring service.
    Designed to run forever until interrupted with Ctrl+C.
    """
    try:
        print(BANNER)
        print(f"[Service] Project root: {_project_root}")

        # ── Step 1: Initialise and migrate the database ───────────────────────
        print("[Service] Initialising database schema...")
        init_db()        # Creates tables if absent
        migrate_db()     # Adds new columns to existing databases (safe no-op if already current)

        # ── Step 2: Synchronise the API list ─────────────────────────────────
        print(f"[Service] Syncing {len(APIS_TO_MONITOR)} APIs into database...")
        sync_apis(APIS_TO_MONITOR)

        # ── Step 3: Immediate first check ─────────────────────────────────────
        # Run one full cycle right now so the dashboard has fresh data
        # without waiting 5 minutes for the first scheduled tick.
        print("[Service] Running initial check cycle...")
        run_all_checks()
        print("[Service] Initial check cycle complete.")

        # ── Step 4: Start the APScheduler ────────────────────────────────────
        scheduler = create_scheduler()
        scheduler.start()
        print(
            f"[Service] Scheduler started. Next automatic check in "
            f"{CHECK_INTERVAL_MINUTES} minutes."
        )
        print("[Service] Press Ctrl+C to stop.\n")

        # ── Step 5: Keep the process alive ───────────────────────────────────
        # The scheduler runs in background threads; we just need this main
        # thread to stay alive so the process doesn't exit.
        while True:
            time.sleep(60)

    except KeyboardInterrupt:
        print("\n[Service] Shutdown signal received (Ctrl+C).")
        try:
            scheduler.shutdown(wait=False)
            print("[Service] Scheduler stopped cleanly.")
        except Exception:
            pass
        print("[Service] Monitoring service stopped.")
        sys.exit(0)

    except Exception as exc:
        print(f"[Service] FATAL ERROR: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
