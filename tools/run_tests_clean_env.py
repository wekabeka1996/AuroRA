#!/usr/bin/env python3
"""Run pytest with AURORA_* env vars removed and pycache cleared (Windows-friendly).

Usage: python tools\run_tests_clean_env.py
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

# Prepare environment without AURORA_* keys
env = os.environ.copy()
removed = [k for k in list(env.keys()) if k.startswith("AURORA_")]
for k in removed:
    env.pop(k, None)
print(f"Removed env vars: {removed}")

# Clean __pycache__ and .pyc files
root = Path(__file__).resolve().parents[1]
print(f"Cleaning pycache under: {root}")
for p in root.rglob('__pycache__'):
    try:
        shutil.rmtree(p)
    except Exception as e:
        print(f"Warning: could not remove {p}: {e}")
for p in root.rglob('*.pyc'):
    try:
        p.unlink()
    except Exception as e:
        print(f"Warning: could not remove {p}: {e}")

# Run pytest
print("Starting pytest -q ...")
rc = subprocess.call([sys.executable, '-m', 'pytest', '-q'], env=env)
print(f"pytest exit code: {rc}")
sys.exit(rc)
