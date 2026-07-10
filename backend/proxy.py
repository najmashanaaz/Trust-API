"""
backend/proxy.py
────────────────
PURPOSE:
    Generic traffic-swapping proxy layer.

    forward_request() receives a "primary" API name and a standard request,
    consults the live failover state in SQLite, routes to whichever provider
    is currently ACTIVE (primary or its backup), calls the correct adapter,
    and returns a uniform response dict.

ROUTING LOGIC:
    1. Resolve primary_api_name → api_id via get_all_apis()
    2. Read failover state via get_failover_state(api_id)
    3. If ACTIVE (or no state row): use primary provider config
       If FAILED_OVER: resolve active_backup_id → backup api_name, use that config
    4. Look up resolved name in PROVIDER_CONFIG
    5. Read API key from environment — return error dict if missing (no crash)
    6. Dispatch to the correct adapter module
    7. Wrap adapter call in try/except — return error dict on failure
    8. Inject "served_by" into response and return

NOTE:
    This module is intentionally READ-ONLY against the database.
    It never writes, never modifies failover state, never triggers checks.
    It is a pure consumer of what Phase 1/2 have already determined.
"""

import os

from backend.database import get_all_apis, get_failover_state
from backend.provider_config import PROVIDER_CONFIG


def forward_request(primary_api_name: str, standard_request: dict) -> dict:
    """
    Route a standard chat request to the currently active provider for
    primary_api_name, automatically using the backup if failover is active.

    Parameters
    ----------
    primary_api_name : str
        The api_name of the intended primary provider, e.g. "OpenAI".
        Must match a value in the `apis` database table.
    standard_request : dict
        Must contain at minimum:
            "messages": [{"role": "user"|"assistant"|"system", "content": str}]
        Optionally:
            "model": str  — overrides the default_model from PROVIDER_CONFIG

    Returns
    -------
    dict
        On success:  {"content": str, "raw": dict, "served_by": str}
        On error:    {"error": str, "served_by": str}   (never raises)
    """

    # ── Step 1: build name↔id lookup maps from the database ──────────────────
    all_apis   = get_all_apis()
    name_to_id = {api["api_name"]: api["id"]       for api in all_apis}
    id_to_name = {api["id"]:       api["api_name"] for api in all_apis}

    # ── Step 2: resolve primary_api_name → api_id ────────────────────────────
    primary_id = name_to_id.get(primary_api_name)
    if primary_id is None:
        return {
            "error":     f"Unknown primary API name: '{primary_api_name}'. "
                         f"Available: {sorted(name_to_id.keys())}",
            "served_by": primary_api_name,
        }

    # ── Step 3: check failover state ─────────────────────────────────────────
    state = get_failover_state(primary_id)

    if state is not None and state["current_status"] == "FAILED_OVER":
        backup_id = state["active_backup_id"]
        if backup_id is None:
            # Failover is active but backup_id is null — fall back to primary
            resolved_name = primary_api_name
        else:
            resolved_name = id_to_name.get(backup_id)
            if resolved_name is None:
                return {
                    "error":     f"Failover is ACTIVE but backup api_id={backup_id} "
                                 f"not found in apis table.",
                    "served_by": primary_api_name,
                }
    else:
        # ACTIVE state (or no state row yet) — use primary
        resolved_name = primary_api_name

    # ── Step 4: look up provider config ──────────────────────────────────────
    config = PROVIDER_CONFIG.get(resolved_name)
    if config is None:
        return {
            "error":     f"Provider '{resolved_name}' is not in PROVIDER_CONFIG. "
                         f"It can be monitored but the proxy cannot route to it yet.",
            "served_by": resolved_name,
        }

    # ── Step 5: resolve API key from environment ──────────────────────────────
    api_key_env = config["api_key_env"]
    api_key     = os.environ.get(api_key_env)
    if not api_key:
        return {
            "error":     f"Missing environment variable '{api_key_env}'. "
                         f"Set it in your .env file to use '{resolved_name}'.",
            "served_by": resolved_name,
        }

    # ── Step 6: resolve model (caller can override via "model" key) ───────────
    model = standard_request.get("model") or config["default_model"]

    # ── Step 7: dispatch to correct adapter ───────────────────────────────────
    try:
        adapter_name = config["adapter"]

        if adapter_name == "openai_compatible":
            from backend.adapters.openai_compatible import call as oa_call
            result = oa_call(
                standard_request=standard_request,
                base_url=config["base_url"],
                api_key=api_key,
                model=model,
            )

        elif adapter_name == "google_gemini":
            from backend.adapters.google_gemini import call as gemini_call
            result = gemini_call(
                standard_request=standard_request,
                api_key=api_key,
                model=model,
            )

        else:
            return {
                "error":     f"Unknown adapter '{adapter_name}' in PROVIDER_CONFIG "
                             f"for provider '{resolved_name}'.",
                "served_by": resolved_name,
            }

    except Exception as err:
        return {
            "error":     str(err),
            "served_by": resolved_name,
        }

    # ── Step 8: inject served_by and return ───────────────────────────────────
    result["served_by"] = resolved_name
    return result
