#!/usr/bin/env python3
"""
backend/verify_proxy_swap.py
────────────────────────────
PURPOSE:
    Standalone verification script to test Phase 3 live traffic-swapping proxy
    failover behavior directly.

USAGE:
    python backend/verify_proxy_swap.py --primary Groq --backup "Google Cloud"
"""

import os
import sys
import argparse
from dotenv import load_dotenv

# Add the project root to sys.path to allow imports from backend.*
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load environment variables from the root .env file
env_path = os.path.join(project_root, ".env")
load_dotenv(dotenv_path=env_path)

from backend.database import get_all_apis, get_failover_state, upsert_failover_state
from backend.provider_config import PROVIDER_CONFIG
from backend.proxy import forward_request


def print_provider_status():
    """Prints all configured providers and whether their API keys are SET or MISSING in .env."""
    print("=== PROVIDER CONFIG KEY STATUS ===")
    for provider, config in PROVIDER_CONFIG.items():
        key_var = config.get("api_key_env")
        val = os.environ.get(key_var) if key_var else None
        status = "SET" if val else "MISSING"
        print(f"  {provider:<15} ({key_var or 'N/A'}): {status}")
    print("==================================\n")


def main():
    parser = argparse.ArgumentParser(description="Verify proxy failover swapping.")
    parser.add_argument("--primary", required=True, help="Name of primary API provider (e.g. Groq)")
    parser.add_argument("--backup", required=True, help="Name of backup API provider (e.g. Google Cloud)")
    args = parser.parse_args()

    # 1. Print all provider API key statuses
    print_provider_status()

    # 2. Get API mapping from the database
    all_apis = get_all_apis()
    name_to_id = {api["api_name"]: api["id"] for api in all_apis}

    # Verify input names exist in database
    if args.primary not in name_to_id:
        print(f"ERROR: Primary provider '{args.primary}' not found in database.")
        print(f"Available database APIs: {list(name_to_id.keys())}")
        sys.exit(1)

    if args.backup not in name_to_id:
        print(f"ERROR: Backup provider '{args.backup}' not found in database.")
        print(f"Available database APIs: {list(name_to_id.keys())}")
        sys.exit(1)

    primary_id = name_to_id[args.primary]
    backup_id = name_to_id[args.backup]

    # Save original state for backup/restoration reference
    orig_state = get_failover_state(primary_id)
    print(f"Original failover state for '{args.primary}': {orig_state}")

    # Set up try-finally block to ensure database restoration
    try:
        # Force primary state to FAILED_OVER pointing to backup
        print(f"\n[1/3] Temporarily forcing '{args.primary}' to FAILED_OVER with backup '{args.backup}' (ID: {backup_id})...")
        upsert_failover_state(
            api_id=primary_id,
            current_status="FAILED_OVER",
            active_backup_id=backup_id,
            consecutive_failures=3,
            consecutive_successes=0
        )

        # Print current failover state to verify update
        new_state = get_failover_state(primary_id)
        print(f"Temporary database failover state: {new_state}")

        # 3. Call forward_request directly with a test message
        test_payload = {
            "messages": [
                {"role": "user", "content": "Say hello in exactly five words."}
            ]
        }
        print(f"\n[2/3] Forwarding request to proxy for primary '{args.primary}'...")
        response = forward_request(args.primary, test_payload)

        # 4. Print results clearly
        if "error" in response:
            print("\n>>> RESULT: ERROR <<<")
            print(f"  Served by: {response.get('served_by')}")
            print(f"  Message:   {response.get('error')}")
        else:
            print("\n>>> RESULT: SUCCESS <<<")
            print(f"  Served by: {response.get('served_by')}")
            print(f"  Content:   {response.get('content')}")

    except Exception as e:
        print(f"\nAn unexpected exception occurred during test execution: {e}")

    finally:
        # 5. Restore primary failover state to ACTIVE (0 failures/successes)
        print(f"\n[3/3] Restoring '{args.primary}' failover state to ACTIVE (0 failures/successes)...")
        upsert_failover_state(
            api_id=primary_id,
            current_status="ACTIVE",
            active_backup_id=None,
            consecutive_failures=0,
            consecutive_successes=0
        )
        final_state = get_failover_state(primary_id)
        print(f"Final restored failover state: {final_state}")
        print("Restoration complete.")


if __name__ == "__main__":
    main()
