"""
backend/failover.py
───────────────────
PURPOSE:
    Phase 2 automated failover engine.

    evaluate_failover(api_id, status) is called by monitor.py after every
    health check.  It maintains per-API failure/success counters in SQLite
    and triggers state transitions when thresholds are crossed:

        ACTIVE  ──(≥3 consecutive failures)──▶  FAILED_OVER
        FAILED_OVER  ──(≥5 consecutive successes)──▶  ACTIVE

    If no backup is configured for an API, the function logs a warning and
    returns without crashing — existing monitoring behaviour is unchanged.

THRESHOLDS (named constants — do not use magic numbers elsewhere):
    FAILOVER_THRESHOLD = 3   consecutive DOWN checks → trigger failover
    RECOVERY_THRESHOLD = 5   consecutive UP checks   → recover to primary
"""

from datetime import datetime

from backend.database import (
    get_failover_state,
    upsert_failover_state,
    get_backup_for_api,
    get_users_watching_api,
    get_all_apis,
)
from backend.email_alerts import send_failover_alert, send_failover_recovery_alert

# ── Thresholds ─────────────────────────────────────────────────────────────────
FAILOVER_THRESHOLD = 3   # consecutive DOWN checks before activating backup
RECOVERY_THRESHOLD = 5   # consecutive UP checks before returning to primary


# ── Internal helper ────────────────────────────────────────────────────────────
def _api_name_for(api_id: int) -> str:
    """Returns the api_name for a given api_id, or a fallback string."""
    for api in get_all_apis():
        if api["id"] == api_id:
            return api["api_name"]
    return f"API#{api_id}"


# ── Public interface ───────────────────────────────────────────────────────────
def evaluate_failover(api_id: int, status: str) -> None:
    """
    Evaluates whether a failover transition should occur for the given API
    after a single health-check result of 'UP' or 'DOWN'.

    Called by monitor.check_api() after the existing alert_sent block.
    Safe to call even when api_backup_config has zero rows — no exceptions
    are raised and existing monitoring behaviour is unaffected.

    Parameters:
        api_id — database id of the API that was just checked
        status — "UP" or "DOWN" (the result of the health check)
    """
    # ── Load or initialise state ───────────────────────────────────────────────
    state = get_failover_state(api_id)
    if state is None:
        # First time this API has been evaluated — create a clean default state.
        state = {
            "api_id":               api_id,
            "current_status":       "ACTIVE",
            "active_backup_id":     None,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "last_state_change":    datetime.utcnow().isoformat(),
        }

    current_status       = state["current_status"]
    active_backup_id     = state["active_backup_id"]
    consecutive_failures  = state["consecutive_failures"]
    consecutive_successes = state["consecutive_successes"]

    # ── Update counters ────────────────────────────────────────────────────────
    if status == "DOWN":
        consecutive_failures  += 1
        consecutive_successes  = 0
    elif status == "UP":
        consecutive_successes += 1
        consecutive_failures   = 0

    # ── Transition: ACTIVE → FAILED_OVER ──────────────────────────────────────
    if consecutive_failures >= FAILOVER_THRESHOLD and current_status == "ACTIVE":
        backup = get_backup_for_api(api_id)
        if backup is None:
            # No backup configured — log and stay ACTIVE (no crash).
            print(
                f"[Failover] WARNING: {_api_name_for(api_id)} has reached "
                f"{FAILOVER_THRESHOLD} consecutive failures but has NO backup "
                f"configured in api_backup_config. Skipping failover."
            )
        else:
            backup_api_id   = backup["backup_api_id"]
            primary_name    = _api_name_for(api_id)
            backup_name     = _api_name_for(backup_api_id)
            current_status  = "FAILED_OVER"
            active_backup_id = backup_api_id

            print(
                f"[Failover] FAILOVER triggered for '{primary_name}' "
                f"→ backup '{backup_name}' (backup_api_id={backup_api_id})"
            )

            # Alert every user who watches this primary API.
            for user in get_users_watching_api(api_id):
                send_failover_alert(user["email"], primary_name, backup_name)

    # ── Transition: FAILED_OVER → ACTIVE ──────────────────────────────────────
    elif consecutive_successes >= RECOVERY_THRESHOLD and current_status == "FAILED_OVER":
        primary_name     = _api_name_for(api_id)
        current_status   = "ACTIVE"
        active_backup_id = None

        print(
            f"[Failover] RECOVERY: '{primary_name}' has been stable for "
            f"{RECOVERY_THRESHOLD} consecutive checks. Returning to ACTIVE."
        )

        # Alert every user who watches this primary API.
        for user in get_users_watching_api(api_id):
            send_failover_recovery_alert(user["email"], primary_name)

    # ── Persist updated state ─────────────────────────────────────────────────
    upsert_failover_state(
        api_id=api_id,
        current_status=current_status,
        active_backup_id=active_backup_id,
        consecutive_failures=consecutive_failures,
        consecutive_successes=consecutive_successes,
    )
