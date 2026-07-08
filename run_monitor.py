"""
run_monitor.py
──────────────
Top-level launcher for the TrustAPI monitoring service.

Run this from the project root directory:

    python run_monitor.py

This script adds the project root to sys.path so that
`backend.*` imports work correctly regardless of the current
working directory when the script is invoked.

It is equivalent to:
    python -m backend.monitoring_service
"""

import sys
import os

# Add the project root (the directory containing this file) to sys.path.
# This ensures `from backend.xxx import yyy` works correctly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.monitoring_service import main

if __name__ == "__main__":
    main()
