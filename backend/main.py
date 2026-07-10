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
from dotenv import load_dotenv

load_dotenv()  # Load .env before any os.environ reads

from fastapi import Depends, Header
from backend.auth import hash_password, verify_password, create_token, decode_token
from backend.database import (
    create_user, get_user_by_email, get_user_by_id,
    add_to_watchlist, remove_from_watchlist, get_watchlist,
    add_backup_config,
)
from pydantic import BaseModel

# ── Request Models ────────────────────────────────────────────────────────────
class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class WatchlistRequest(BaseModel):
    api_id: int

class BackupConfigRequest(BaseModel):
    primary_api_id: int
    backup_api_id: int
    priority: int = 1

class DependencyScanRequest(BaseModel):
    dependencies: list[str]

class ProxyChatRequest(BaseModel):
    primary: str
    messages: list[dict]
    model: str | None = None
    
# ── Auth Helper ───────────────────────────────────────────────────────────────
def get_current_user(authorization: str = Header(None)):
    """Extracts and validates the JWT token from the Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ")[1]
    payload = decode_token(token)
    if not payload:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Token expired or invalid")
    return payload

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.database import init_db, migrate_db, sync_apis, get_all_apis, get_logs_for_api, get_latest_check_for_all_apis, get_all_failover_status, get_all_backup_configs, delete_backup_config
from backend.apis import APIS_TO_MONITOR
from backend.monitor import calculate_reliability
from backend.package_mapping import PACKAGE_TO_API


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
        print("[Server]   -> Start it with:  python run_monitor.py")

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


@app.get("/api/failover-status", tags=["Monitoring"])
def get_failover_status():
    """
    Returns every monitored API with its current failover state.

    Data source: LEFT JOIN of apis + api_failover_state.
    APIs with no failover state row yet appear with default values:
      current_status='ACTIVE', active_backup_id=null.

    Response format:
        [
          {"api_id": 1, "api_name": "OpenAI", "current_status": "ACTIVE", "active_backup_id": null},
          ...
        ]
    """
    return get_all_failover_status()


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

# ── Auth Endpoints ────────────────────────────────────────────────────────────

@app.post("/api/signup", tags=["Auth"])
def signup(body: SignupRequest):
    """Creates a new user account."""
    if get_user_by_email(body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    hashed = hash_password(body.password)
    user_id = create_user(body.email, hashed)
    token = create_token(user_id, body.email)
    return {"token": token, "email": body.email, "user_id": user_id}


@app.post("/api/login", tags=["Auth"])
def login(body: LoginRequest):
    """Logs in an existing user and returns a JWT token."""
    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["id"], user["email"])
    return {"token": token, "email": user["email"], "user_id": user["id"]}


@app.get("/api/me", tags=["Auth"])
def get_me(current_user: dict = Depends(get_current_user)):
    """Returns the currently logged-in user's info."""
    return {"user_id": current_user["sub"], "email": current_user["email"]}


# ── Watchlist Endpoints ───────────────────────────────────────────────────────

@app.get("/api/watchlist", tags=["Watchlist"])
def get_my_watchlist(current_user: dict = Depends(get_current_user)):
    """Returns all APIs in the current user's watchlist."""
    user_id = int(current_user["sub"])
    return get_watchlist(user_id)


@app.post("/api/watchlist", tags=["Watchlist"])
def add_api_to_watchlist(body: WatchlistRequest, current_user: dict = Depends(get_current_user)):
    """Adds an API to the current user's watchlist."""
    user_id = int(current_user["sub"])
    add_to_watchlist(user_id, body.api_id)
    return {"message": "Added to watchlist"}


@app.delete("/api/watchlist/{api_id}", tags=["Watchlist"])
def remove_api_from_watchlist(api_id: int, current_user: dict = Depends(get_current_user)):
    """Removes an API from the current user's watchlist."""
    user_id = int(current_user["sub"])
    remove_from_watchlist(user_id, api_id)
    return {"message": "Removed from watchlist"}


# ── Backup Config Endpoints ───────────────────────────────────────────────────

@app.post("/api/backup-config", tags=["Failover"], status_code=201)
def create_backup_config(body: BackupConfigRequest):
    """
    Links a primary API to a backup API for automated failover.

    Validates:
      - Both api_ids must exist in the apis table (404 if not).
      - primary_api_id must differ from backup_api_id (400 if equal).

    Returns the created config row id.
    """
    valid_ids = {api["id"] for api in get_all_apis()}

    if body.primary_api_id not in valid_ids:
        raise HTTPException(status_code=404, detail=f"primary_api_id={body.primary_api_id} not found.")
    if body.backup_api_id not in valid_ids:
        raise HTTPException(status_code=404, detail=f"backup_api_id={body.backup_api_id} not found.")
    if body.primary_api_id == body.backup_api_id:
        raise HTTPException(status_code=400, detail="primary_api_id and backup_api_id must be different.")

    config_id = add_backup_config(body.primary_api_id, body.backup_api_id, body.priority)
    return {
        "id":             config_id,
        "primary_api_id": body.primary_api_id,
        "backup_api_id":  body.backup_api_id,
        "priority":       body.priority,
    }


@app.get("/api/backup-config", tags=["Failover"])
def list_backup_configs():
    """
    Returns all backup config rows joined with api names for both primary and backup.

    Response format:
        [
          {
            "id": 1,
            "primary_api_id": 1, "primary_name": "OpenAI",
            "backup_api_id":  2, "backup_name":  "Google Cloud",
            "priority": 1
          },
          ...
        ]
    """
    return get_all_backup_configs()


@app.delete("/api/backup-config/{config_id}", tags=["Failover"])
def remove_backup_config(config_id: int):
    """
    Deletes a specific backup config row by its id.
    Returns 404 if the row does not exist.
    """
    deleted = delete_backup_config(config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Backup config id={config_id} not found.")
    return {"message": f"Backup config {config_id} deleted."}


# ── Package & Alternatives Endpoints (Phase 3) ────────────────────────────────

@app.get("/api/package-reliability/{package_name}", tags=["Phase3"])
def get_package_reliability(package_name: str):
    """
    Looks up a npm/pip package name in PACKAGE_TO_API, resolves to an api_id,
    and returns that API's current reliability stats.

    Returns {"tracked": false} if the package maps to no monitored API.
    Returns {"tracked": true, "no_data": true} if mapped but no checks run yet.
    """
    status_url = PACKAGE_TO_API.get(package_name)
    if not status_url:
        return {"tracked": False, "package": package_name}

    # Resolve url → api_id from the apis table
    apis = get_all_apis()
    api = next((a for a in apis if a["api_url"] == status_url), None)
    if not api:
        return {"tracked": False, "package": package_name, "reason": "url_not_in_db"}

    stats = calculate_reliability(api["id"])

    # Also fetch latest status (UP/DOWN)
    latest = next(
        (r for r in get_latest_check_for_all_apis() if r["api_id"] == api["id"]),
        None,
    )

    return {
        "tracked":          True,
        "package":          package_name,
        "api_id":           api["id"],
        "api_name":         api["api_name"],
        "api_url":          api["api_url"],
        "current_status":   latest["status"] if latest else None,
        "reliability_score": stats["reliability_score"],
        "uptime_pct":       stats["uptime_pct"],
        "stats_status":     stats["status"],  # "ok" or "no_data"
    }


@app.get("/api/alternatives/{api_id}", tags=["Phase3"])
def get_alternatives(api_id: int):
    """
    Returns other APIs in the same category as api_id, sorted by
    reliability_score descending. Excludes api_id itself.

    Returns 404 if api_id does not exist.
    """
    apis = get_all_apis()
    target = next((a for a in apis if a["id"] == api_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"API id={api_id} not found.")

    category = target.get("category")
    if not category:
        return []

    alternatives = []
    for api in apis:
        if api["id"] == api_id:
            continue
        if api.get("category") != category:
            continue
        stats = calculate_reliability(api["id"])
        alternatives.append({
            "api_id":           api["id"],
            "api_name":         api["api_name"],
            "api_url":          api["api_url"],
            "category":         api.get("category"),
            "reliability_score": stats["reliability_score"],
            "uptime_pct":       stats["uptime_pct"],
            "stats_status":     stats["status"],
        })

    alternatives.sort(key=lambda x: x["reliability_score"], reverse=True)
    return alternatives


@app.post("/api/dependency-scan", tags=["Phase3"])
def dependency_scan(body: DependencyScanRequest):
    """
    Accepts a list of package names (from a scanned package.json or
    requirements.txt) and returns reliability info for every dependency
    that resolves via PACKAGE_TO_API — in one batched call.

    Untracked packages are omitted from the response (not errors).

    Request body: {"dependencies": ["openai", "anthropic", ...]}

    Response: list of reliability objects (same shape as package-reliability).
    """
    apis      = get_all_apis()
    url_to_api = {a["api_url"]: a for a in apis}

    latest_map = {r["api_id"]: r for r in get_latest_check_for_all_apis()}

    results = []
    seen_api_ids: set[int] = set()  # deduplicate if multiple packages map to same API

    for pkg in body.dependencies:
        status_url = PACKAGE_TO_API.get(pkg)
        if not status_url:
            continue  # not tracked — silently skip
        api = url_to_api.get(status_url)
        if not api:
            continue
        if api["id"] in seen_api_ids:
            continue
        seen_api_ids.add(api["id"])

        stats  = calculate_reliability(api["id"])
        latest = latest_map.get(api["id"])

        results.append({
            "tracked":           True,
            "package":           pkg,
            "api_id":            api["id"],
            "api_name":          api["api_name"],
            "api_url":           api["api_url"],
            "current_status":    latest["status"] if latest else None,
            "reliability_score": stats["reliability_score"],
            "uptime_pct":        stats["uptime_pct"],
            "stats_status":      stats["status"],
        })

    return results


# ── Proxy Endpoint ────────────────────────────────────────────────────────────

@app.post("/api/proxy/chat", tags=["Proxy"])
def proxy_chat(body: ProxyChatRequest):
    """
    Generic traffic-swapping chat proxy.

    Routes the request to whichever provider is currently ACTIVE for the
    given primary API name — automatically using the configured backup if
    the primary has FAILED_OVER in the failover state table.

    Request body:
        {
            "primary":  "OpenAI",   // api_name from the apis table
            "messages": [{"role": "user", "content": "Hello!"}],
            "model":    "gpt-4o"    // optional — overrides default_model
        }

    Response (success):
        {"content": "<reply>", "raw": {...}, "served_by": "OpenAI"}

    Response (error — never crashes, always returns JSON):
        {"error": "<reason>", "served_by": "<provider name>"}

    Providers currently supported by the proxy:
        OpenAI, Groq, Fireworks AI, Together AI, DeepSeek, Google Cloud.
    All other monitored APIs (Anthropic, Azure, etc.) are tracked for
    uptime/reliability but not yet routable via this endpoint.
    """
    from backend.proxy import forward_request
    return forward_request(
        primary_api_name=body.primary,
        standard_request={"messages": body.messages, "model": body.model},
    )

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
