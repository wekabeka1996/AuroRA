from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import validate, ValidationError
from datetime import datetime


def tail_lines(path: Path, n: int) -> list[str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        return lines[-n:]
    except FileNotFoundError:
        return []


def main():
    parser = argparse.ArgumentParser()
    import os
    default_file = str(Path(os.getenv('AURORA_SESSION_DIR', 'logs')) / 'aurora_events.jsonl')
    parser.add_argument("--file", default=default_file)
    parser.add_argument("--schema", default="observability/schema.json")
    parser.add_argument("--last", type=int, default=200)
    args = parser.parse_args()

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    lines = tail_lines(Path(args.file), args.last)
    ok = True
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s:
            continue
        try:
            raw = json.loads(s)
            # Map legacy event format {type,severity,code,payload} to schema
            if set(raw.keys()) >= {"type", "payload"}:
                sev = raw.get("severity")
                mapped = {
                    "ts": datetime.utcnow().isoformat() + "Z",
                    "level": (str(sev).upper() if sev else "INFO"),
                    "category": str(raw.get("type") or "MISC"),
                    "code": str(raw.get("code") or raw.get("type") or "UNKNOWN"),
                    "ctx": raw.get("payload") or {},
                }
                validate(mapped, schema)
            else:
                validate(raw, schema)
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"Invalid event at tail index {i}: {e}")
            ok = False
    if not ok:
        raise SystemExit(1)
    print(f"Validated {len(lines)} events against schema")


if __name__ == "__main__":
    main()
