"""
backend/test_monitor.py
───────────────────────
PURPOSE:
    Verifies the status page scraper and parser logic by directly invoking
    check_api on the 16 configured AI status pages.
"""

from backend.database import init_db, sync_apis, get_all_apis
from backend.apis import APIS_TO_MONITOR
from backend.monitor import check_api

def main():
    print("[Test] Initialising database...")
    init_db()
    
    print("[Test] Syncing APIs list into database...")
    sync_apis(APIS_TO_MONITOR)
    
    print("[Test] Retrieving APIs from database...")
    apis = get_all_apis()
    
    print(f"[Test] Found {len(apis)} APIs in DB. Running checks sequentially...")
    
    successful_runs = 0
    failed_runs = 0
    
    for api in apis:
        try:
            res = check_api(api)
            print(f"[Test] Result for {res['api_name']}: {res['status']} ({res['response_time']} ms)")
            successful_runs += 1
        except Exception as e:
            print(f"[Test] ERROR checking {api['api_name']}: {e}")
            failed_runs += 1
            
    print(f"\n[Test] Execution completed. Success: {successful_runs}, Failed: {failed_runs}")

if __name__ == "__main__":
    import sys
    import os
    # Add project root directory to path to allow relative package imports
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
