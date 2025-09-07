#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

def main():
    try:
        import requests
    except Exception:
        print("ERROR: requests library not available", file=sys.stderr)
        sys.exit(2)
    try:
        from dotenv import load_dotenv
    except Exception:
        load_dotenv = None

    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if load_dotenv is not None and env_path.exists():
        try:
            load_dotenv(dotenv_path=str(env_path))
        except Exception:
            pass

    token = os.getenv("AURORA_API_TOKEN")
    if not token:
        print("ERROR: AURORA_API_TOKEN not set", file=sys.stderr)
        sys.exit(3)

    host = os.getenv("AURORA_API_HOST", "127.0.0.1")
    port = int(os.getenv("AURORA_API_PORT", "8000"))
    url = f"http://{host}:{port}/overlay/apply"

    # Build overlay body from argv or use a sane default
    # Usage:
    #   python tools/apply_overlay.py '{"pretrade": {"order_profile": "er_before_slip"}}'
    # or  python tools/apply_overlay.py --wrapped '{"overlay": { ... }}'
    wrapped = False
    body_arg = None
    for i, a in enumerate(sys.argv[1:]):
        if a == "--wrapped":
            wrapped = True
            continue
        body_arg = a
        break

    if body_arg is None:
        payload = {"overlay": {"pretrade": {"order_profile": "er_before_slip"}, "guards": {"spread_bps_limit": 30}}}
    else:
        try:
            obj = json.loads(body_arg)
        except Exception as e:
            print(f"ERROR: invalid JSON provided: {e}", file=sys.stderr)
            sys.exit(4)
        if wrapped:
            payload = obj
        else:
            payload = {"overlay": obj}

    try:
        r = requests.post(url, json=payload, headers={"X-Auth-Token": token}, timeout=5)
    except Exception as e:
        print(f"ERROR: request failed: {e}", file=sys.stderr)
        sys.exit(5)

    print(f"status={r.status_code}")
    try:
        print(r.json())
    except Exception:
        print(r.text)

    # Show active overlay quick check
    try:
        r2 = requests.get(f"http://{host}:{port}/overlay/active", headers={"X-Auth-Token": token}, timeout=3)
        print("active:", r2.status_code)
        try:
            print(r2.json())
        except Exception:
            print(r2.text)
    except Exception:
        pass

if __name__ == "__main__":
    main()
