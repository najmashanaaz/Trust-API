"""
backend/monitor.py
──────────────────
PURPOSE:
    The monitoring engine.  Does three things:
      1. Sends real HTTP requests to each monitored API and measures response time.
      2. Saves every result (status, response_time, http_status_code, error_message)
         into the SQLite database as a new row — history is NEVER overwritten.
      3. Calculates a reliability score from historical database records only.

SCHEDULER:
    Exposes create_scheduler() which returns a configured APScheduler
    BackgroundScheduler.  The scheduler is started by either:
      a) backend/monitoring_service.py  (standalone 24/7 process — RECOMMENDED)
      b) backend/main.py lifespan       (embedded mode, set EMBED_SCHEDULER=1)

RELIABILITY SCORE FORMULA:
    Score = (0.70 × uptime_pct) + (0.20 × speed_score) + (0.10 × success_rate)

    uptime_pct   — % of checks where status was "UP"  (0–100)
    speed_score  — 100 if avg response ≤ 200ms, scales linearly to 0 at 2000ms+
    success_rate — same as uptime_pct (kept separate for future re-weighting)

    All inputs come exclusively from real measured rows in SQLite.
    No random numbers.  No simulated values.  No placeholder data.
"""

import requests
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from backend.database import get_all_apis, log_check, get_stats_for_api

# ── Safe print (Windows terminal may reject some Unicode) ─────────────────────
_original_print = print

def print(*args, **kwargs):
    try:
        _original_print(*args, **kwargs)
    except UnicodeEncodeError:
        sep = kwargs.get("sep", " ")
        msg = sep.join(str(arg) for arg in args)
        safe = (
            msg.replace("✅", "[UP]")
               .replace("❌", "[DOWN]")
               .replace("⚠️", "[WARN]")
               .replace("⏱️", "[TIMEOUT]")
               .replace("🔄", "[RETRY]")
        )
        try:
            _original_print(safe, **{k: v for k, v in kwargs.items() if k != "sep"})
        except Exception:
            _original_print(
                msg.encode("ascii", errors="backslashreplace").decode("ascii"),
                **{k: v for k, v in kwargs.items() if k != "sep"},
            )


# ── Constants ─────────────────────────────────────────────────────────────────
TIMEOUT_SECONDS   = 10      # Hard limit per HTTP request
FASTEST_EXPECTED_MS = 200.0  # Anything at or below this → speed_score = 100
SLOWEST_EXPECTED_MS = 2000.0 # Anything at or above this → speed_score = 0
CHECK_INTERVAL_MINUTES = 5   # How often to run all checks


# ── HTML status page parser ───────────────────────────────────────────────────
def check_html_outages(html_text: str) -> str:
    """
    Scans the raw HTML from a custom status page for operational status phrases.
    Returns "UP" or "DOWN".

    Positive phrases are checked FIRST to prevent false negatives where pages
    mention outage keywords inside incident history ("previous major outage").
    """
    html_lower = html_text.lower()

    positive_phrases = [
        "all systems operational",
        "all services operational",
        "all systems are operational",
        "all services are operational",
        "all systems functioning",
        "no issues with",
        "no active incidents",
        "no known issues",
        "fully operational",
    ]
    for phrase in positive_phrases:
        if phrase in html_lower:
            return "UP"

    outage_keywords = [
        "major outage",
        "critical incident",
        "service outage",
        "unplanned disruption",
        "system-down",
        "major disruption",
        "critical outage",
        "service disruption",
    ]
    for kw in outage_keywords:
        if kw in html_lower:
            return "DOWN"

    # Default to UP if the page loads without any explicit outage indicators.
    # A reachable status page with no alerts is generally "operational".
    return "UP"


# ── Core check function ───────────────────────────────────────────────────────
def check_api(api: dict) -> dict:
    """
    Performs ONE real HTTP health check against the given API.

    For Statuspage.io providers: queries the /api/v2/status.json endpoint
    for an authoritative machine-readable status indicator.

    For custom status pages: fetches the HTML and parses the content.

    On any failure:
      - status     → "DOWN"
      - error_message → the real Python exception string (never invented)
      - response_time → None (we cannot report a time if the request failed)

    Every result is persisted to SQLite before returning.
    """
    from backend.apis import APIS_TO_MONITOR  # avoids circular import at module level

    api_id  = api["id"]
    api_url = api["api_url"]

    # Look up the type for this API from the config list
    api_type = next(
        (item.get("type", "custom") for item in APIS_TO_MONITOR if item["url"] == api_url),
        "custom",
    )

    status           = "DOWN"   # Pessimistic default
    response_time    = None     # Time in ms; None if unreachable
    http_status_code = None     # Real HTTP code; None if no response received
    error_message    = None     # Real exception text; None on success

    headers = {"User-Agent": "TrustAPI-Monitor/2.0 (production monitoring; not a bot)"}
    start   = time.monotonic()

    try:
        if api_type == "statuspage":
            # ── Statuspage.io JSON endpoint ──────────────────────────────────
            # Official providers expose /api/v2/status.json with a clean JSON
            # payload that contains an `indicator` field:
            #   "none"        → healthy  → UP
            #   "minor"       → degraded but functional → UP
            #   "maintenance" → planned → UP
            #   "major"       → significant impact → DOWN
            #   "critical"    → major incident → DOWN
            json_url = api_url.rstrip("/") + "/api/v2/status.json"
            try:
                response         = requests.get(json_url, timeout=TIMEOUT_SECONDS, headers=headers)
                elapsed          = time.monotonic() - start
                response_time    = round(elapsed * 1000, 2)
                http_status_code = response.status_code

                if response.ok:
                    data      = response.json()
                    indicator = data.get("status", {}).get("indicator", "none").lower()
                    status    = "UP" if indicator in ("none", "minor", "maintenance") else "DOWN"
                    if status == "DOWN":
                        error_message = f"Statuspage indicator: '{indicator}'"
                        print(f"[Monitor] ⚠️  {api['api_name']} statuspage indicator = '{indicator}'")
                else:
                    raise ValueError(f"Status JSON returned HTTP {response.status_code}")

            except ValueError as ve:
                # JSON endpoint returned a bad HTTP code — fall back to HTML scrape
                print(f"[Monitor] 🔄 {api['api_name']}: JSON endpoint failed ({ve}), falling back to HTML scrape")
                start            = time.monotonic()
                response         = requests.get(api_url, timeout=TIMEOUT_SECONDS, headers=headers)
                elapsed          = time.monotonic() - start
                response_time    = round(elapsed * 1000, 2)
                http_status_code = response.status_code
                if response.ok:
                    status        = check_html_outages(response.text)
                    error_message = None if status == "UP" else "Non-operational status detected in HTML"
                else:
                    status        = "DOWN"
                    error_message = f"HTML fallback returned HTTP {response.status_code}"

        else:
            # ── Custom status page (scrape the HTML) ─────────────────────────
            response         = requests.get(api_url, timeout=TIMEOUT_SECONDS, headers=headers)
            elapsed          = time.monotonic() - start
            response_time    = round(elapsed * 1000, 2)
            http_status_code = response.status_code

            if response.ok:
                status        = check_html_outages(response.text)
                error_message = None if status == "UP" else "Non-operational status detected in HTML"
            else:
                status        = "DOWN"
                error_message = f"HTTP {response.status_code}: {response.reason}"
                print(f"[Monitor] ⚠️  {api['api_name']} returned HTTP {response.status_code}")

    except requests.exceptions.Timeout:
        elapsed       = time.monotonic() - start
        error_message = f"Connection timed out after {TIMEOUT_SECONDS}s (elapsed {round(elapsed, 1)}s)"
        print(f"[Monitor] ⏱️  {api['api_name']} timed out")

    except requests.exceptions.ConnectionError as e:
        error_message = f"Connection error: {str(e)[:200]}"
        print(f"[Monitor] ❌  {api['api_name']} connection error")

    except requests.exceptions.TooManyRedirects as e:
        elapsed       = time.monotonic() - start
        response_time = round(elapsed * 1000, 2)
        error_message = f"Too many redirects: {str(e)[:200]}"
        print(f"[Monitor] ❌  {api['api_name']} too many redirects")

    except requests.exceptions.RequestException as e:
        error_message = f"Request error: {str(e)[:200]}"
        print(f"[Monitor] ❌  {api['api_name']} request error: {e}")

    except Exception as e:
        error_message = f"Unexpected error: {str(e)[:200]}"
        print(f"[Monitor] ❌  {api['api_name']} unexpected error: {e}")

    # ── Persist result to SQLite ──────────────────────────────────────────────
    # ALWAYS log — whether the check succeeded or failed.
    # Every row is a new INSERT; previous rows are never modified.
    log_check(
        api_id=api_id,
        status=status,
        response_time=response_time,
        http_status_code=http_status_code,
        error_message=error_message,
    )

    checked_at  = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    emoji       = "✅" if status == "UP" else "❌"
    rt_display  = f"{response_time} ms" if response_time is not None else "N/A"
    http_display = f" [HTTP {http_status_code}]" if http_status_code else ""
    print(f"[Monitor] {emoji} {api['api_name']:25s}  {status:4s}  {rt_display}{http_display}")

    return {
        "api_id":          api_id,
        "api_name":        api["api_name"],
        "api_url":         api_url,
        "status":          status,
        "response_time":   response_time,
        "http_status_code": http_status_code,
        "error_message":   error_message,
        "checked_at":      checked_at,
    }


# ── Run all checks ────────────────────────────────────────────────────────────
def run_all_checks():
    """
    Fetches all monitored APIs from the database and calls check_api() on each.
    This is the function scheduled to run every 5 minutes.

    Results are inserted into SQLite by check_api() — this function does NOT
    maintain any in-memory cache.  The web server reads directly from the DB.
    """
    apis = get_all_apis()

    if not apis:
        print("[Monitor] ⚠️  No APIs in database. Did sync_apis() run?")
        return

    print(f"\n[Monitor] ═══════ Starting check cycle: {len(apis)} APIs ═══════")
    start_time = time.monotonic()

    for api in apis:
        check_api(api)

    elapsed = time.monotonic() - start_time
    print(
        f"[Monitor] ═══════ Cycle complete in {elapsed:.1f}s "
        f"at {datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')} UTC ═══════\n"
    )


# ── Reliability score calculator ──────────────────────────────────────────────
def calculate_reliability(api_id: int) -> dict:
    """
    Computes a reliability score for one API from its ENTIRE stored history.
    All numbers come from real database rows — never invented.

    Formula:
        reliability_score = (0.70 × uptime_pct)
                          + (0.20 × speed_score)
                          + (0.10 × success_rate)

    Where:
        uptime_pct   = successful_checks / total_checks × 100
        speed_score  = linear scale from 100 (≤200ms avg) to 0 (≥2000ms avg)
        success_rate = same as uptime_pct (kept separate for future re-weighting)

    Returns 0.0 for all metrics when there are no historical records yet.
    """
    stats   = get_stats_for_api(api_id)
    total   = stats["total_checks"]
    success = stats["successful"]
    avg_rt  = stats["avg_response_ms"] or 0.0
    p95_rt  = stats["p95_latency_ms"]  or 0.0

    # ── Uptime percentage ─────────────────────────────────────────────────────
    uptime_pct = round((success / total) * 100, 2) if total > 0 else 0.0

    # ── Speed score (0–100) ───────────────────────────────────────────────────
    if avg_rt <= FASTEST_EXPECTED_MS:
        speed_score = 100.0
    elif avg_rt >= SLOWEST_EXPECTED_MS:
        speed_score = 0.0
    else:
        ratio       = (avg_rt - FASTEST_EXPECTED_MS) / (SLOWEST_EXPECTED_MS - FASTEST_EXPECTED_MS)
        speed_score = round(100.0 * (1.0 - ratio), 2)

    # ── Success rate (mirror of uptime; kept for independent future weighting) ─
    success_rate = uptime_pct

    # ── Weighted reliability score ────────────────────────────────────────────
    reliability_score = round(
        (0.70 * uptime_pct) + (0.20 * speed_score) + (0.10 * success_rate),
        2,
    )

    return {
        "total_checks":      total,
        "successful":        success,
        "failed":            stats["failed"],
        "uptime_pct":        uptime_pct,
        "avg_response_ms":   round(avg_rt, 2),
        "p95_latency_ms":    p95_rt,
        "speed_score":       speed_score,
        "reliability_score": reliability_score,
    }


# ── APScheduler factory ───────────────────────────────────────────────────────
def create_scheduler() -> BackgroundScheduler:
    """
    Creates and configures an APScheduler BackgroundScheduler but does NOT start it.
    The caller is responsible for calling scheduler.start() and scheduler.shutdown().

    Configuration:
        - misfire_grace_time=120: If a job misses its scheduled time by up to
          2 minutes (e.g. the machine was under heavy load), run it immediately
          rather than skipping it. This prevents silent monitoring gaps.
        - coalesce=True: If multiple executions were missed while the scheduler
          was down, only run once on recovery rather than flooding the system.
        - max_instances=1: Never allow two concurrent check cycles to run at
          the same time (each cycle already takes 10–60 seconds for 16 APIs).
    """
    scheduler = BackgroundScheduler(
        job_defaults={
            "misfire_grace_time": 120,
            "coalesce":           True,
            "max_instances":      1,
        }
    )
    scheduler.add_job(
        func=run_all_checks,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        id="monitor_all_apis",
        name="Monitor All APIs",
        replace_existing=True,
    )
    return scheduler
