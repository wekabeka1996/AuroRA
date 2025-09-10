import argparse
import json
from pathlib import Path
import re
import sys

ISOZ = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    args = ap.parse_args()
    p = Path(args.file)
    lines = p.read_text(encoding="utf-8").splitlines()
    ok = 0
    for i, line in enumerate(lines, 1):
        try:
            obj = json.loads(line)
        except Exception:
            print(f"Line {i}: invalid JSON", file=sys.stderr); continue
        t = obj.get("time")
        if not (isinstance(t, str) and ISOZ.match(t)):
            print(f"Line {i}: invalid time format: {t}", file=sys.stderr); continue
        ev = obj.get("event","")
        if "ORDER_STATUS" not in ev:
            print(f"Line {i}: missing ORDER_STATUS", file=sys.stderr); continue
        ok += 1
    print(f"Validated {ok}/{len(lines)}")
    if ok != len(lines) or len(lines) != 100:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
