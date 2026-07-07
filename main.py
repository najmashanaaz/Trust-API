"""
backend/main.py
───────────────
PURPOSE:
    FastAPI web server — serves the dashboard and REST endpoints.

    This server is a PURE READ-ONLY consumer of the SQLite database.
    It NEVER performs HTTP health checks itself.  All monitoring is
    done exclusively by the standalone monitoring service
    (run_monitor.py / backend/monitoring_service.py).

ENDPOINTS:
    GET /              — Serves the frontend index.html
    GET /health        — Simple server liveness check
    GET /api/status    — Latest check result for every API (from DB)
    GET /api/reliability — Reliability stats for every API (from DB history)
    GET /api/history/{api_id} — Recent check log for one API (from DB)

EMBEDDED SCHEDULER (optional / development mode):
    Set the environment variable EMBED_SCHEDULER=1 to run the monitoring
    scheduler inside the FastAPI process as well.  This is useful when you
    only want to start one process during development.
    In production, prefer running run_monitor.py separately.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import init_db, migrate_db, sync_apis, get_all_apis, get_logs_for_api, get_latest_check_for_all_apis
from backend.apis import APIS_TO_MONITOR
from backend.monitor import calculate_reliability


# ── Lifespan Management ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once on server startup (before the first request) and once on shutdown.

    Startup tasks:
      1. Initialise and migrate the SQLite schema (safe to run repeatedly).
      2. Sync the configured API list into the database.
      3. Optionally start the embedded scheduler (EMBED_SCHEDULER=1).

    The web server does NOT run health checks by default.
    It only reads rows that the monitoring service has already written.
    """
    print("[Server] Starting up...")
    init_db()
    migrate_db()
    sync_apis(APIS_TO_MONITOR)

    # ── Optional embedded scheduler (development convenience) ─────────────────
    _scheduler = None
    if os.environ.get("EMBED_SCHEDULER", "0") == "1":
        print("[Server] EMBED_SCHEDULER=1 detected — starting built-in scheduler.")
        from backend.monitor import run_all_checks, create_scheduler
        # Run one immediate check so the dashboard isn't empty on first load.
        print("[Server] Running initial embedded check...")
        run_all_checks()
        _scheduler = create_scheduler()
        _scheduler.start()
        print("[Server] Embedded scheduler running.")
    else:
        print("[Server] Monitoring is handled by the external monitoring service.")
        print("[Server]   → Start it with:  python run_monitor.py")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    print("[Server] Shutting down...")
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        print("[Server] Embedded scheduler stopped.")


# ── Create FastAPI App ────────────────────────────────────────────────────────
app = FastAPI(
    title="API Reliability Monitoring Platform",
    description=(
        "A production-grade backend that reads real monitoring data from SQLite "
        "and serves it to the dashboard. Health checks are performed exclusively "
        "by the standalone monitoring service."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


# ── Middleware: CORS ──────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    """Simple liveness probe — confirms the FastAPI server is running."""
    return {"status": "healthy", "version": "2.0.0"}


@app.get("/api/status", tags=["Monitoring"])
def get_status():
    """
    Returns the most recent check result for every monitored API.

    Data source: SQLite `api_logs` table — the latest row per API.
    This endpoint NEVER performs any HTTP requests to external services.
    All values come from real historical measurements stored by the monitoring service.

    Returns an empty results list if no checks have been run yet.
    """
    results = get_latest_check_for_all_apis()
    return {"results": results}


@app.get("/api/reliability", tags=["Monitoring"])
def get_all_reliability():
    """
    Calculates reliability statistics for every monitored API based on
    the complete check history in SQLite.

    Metrics returned per API:
      - total_checks      — total number of health checks ever recorded
      - successful        — how many resulted in status="UP"
      - failed            — how many resulted in status="DOWN"
      - uptime_pct        — percentage of UP checks
      - avg_response_ms   — mean response time across all UP checks
      - p95_latency_ms    — 95th-percentile response time (real measurements)
      - speed_score       — 0-100 latency score used in reliability formula
      - reliability_score — weighted composite score (70% uptime, 20% speed, 10% success rate)

    All values are calculated from real stored data. No fake metrics.
    """
    apis = get_all_apis()
    report = []
    for api in apis:
        stats = calculate_reliability(api["id"])
        report.append({
            "api_id":   api["id"],
            "api_name": api["api_name"],
            "api_url":  api["api_url"],
            "stats":    stats,
        })
    return report


@app.get("/api/history/{api_id}", tags=["Monitoring"])
def get_history(api_id: int, limit: int = 50):
    """
    Fetches the most recent check logs for a single API by its database ID.

    Used by the dashboard when a user clicks an API card to view its history.
    Returns up to `limit` rows, newest first.

    Each row includes:
      - status          — "UP" or "DOWN"
      - response_time   — milliseconds (null if DOWN with no response)
      - http_status_code— real HTTP code (null if connection failed entirely)
      - error_message   — real error string on failure (null on success)
      - checked_at      — UTC ISO timestamp
    """
    apis = get_all_apis()
    valid_ids = {api["id"] for api in apis}
    if api_id not in valid_ids:
        raise HTTPException(status_code=404, detail=f"API with id={api_id} not found.")

    logs = get_logs_for_api(api_id, limit=limit)
    return logs


# ── Serve Static Frontend ─────────────────────────────────────────────────────
frontend_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "frontend")
)


@app.get("/", include_in_schema=False)
def serve_index():
    """Serves the dashboard index.html at the root URL."""
    index_file = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"error": "Frontend not found. Ensure the frontend/ directory exists."}


if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
else:
    print(f"[Warning] Frontend directory not found at: {frontend_path}")
