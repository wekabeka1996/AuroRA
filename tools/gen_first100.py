import argparse
from datetime import UTC
import json
from pathlib import Path
import re

ISOZ = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

def find_latest_jsonl(logs_dir: Path) -> Path:
    files = sorted(logs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files: raise SystemExit("No .jsonl logs found in 'logs/'")
    return files[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="", help="input jsonl; default: latest in logs/")
    ap.add_argument("--out", dest="out", default="logs/sim_local_first100.jsonl")
    ap.add_argument("--count", type=int, default=100)
    args = ap.parse_args()

    inp = Path(args.inp) if args.inp else find_latest_jsonl(Path("logs"))
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)

    sel = []
    with inp.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            # Вибираємо лише події ORDER_STATUS(sim) або подібні до симулятора
            if str(obj.get("event","")) .startswith("ORDER_STATUS") and "sim" in str(obj.get("event","")):
                sel.append(obj)
            if len(sel) >= args.count:
                break

    if len(sel) < args.count:
        raise SystemExit(f"Found only {len(sel)} matching rows in {inp}")

    with out.open("w", encoding="utf-8") as g:
        for o in sel:
            # нормалізуємо час до мс із суфіксом Z, якщо ще не такий
            t = str(o.get("time") or o.get("ts") or o.get("timestamp") or "")
            if not ISOZ.match(t):
                # якщо є ns або ms — спробуємо конвертнути до ISO .sssZ
                from datetime import datetime
                try:
                    ns = int(o.get("ts_ns")) if o.get("ts_ns") else None
                    ms = int(o.get("ts_ms")) if o.get("ts_ms") else None
                    if ns is not None:
                        dt = datetime.fromtimestamp(ns/1e9, tz=UTC)
                    elif ms is not None:
                        dt = datetime.fromtimestamp(ms/1e3, tz=UTC)
                    else:
                        raise ValueError
                    o["time"] = dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
                except Exception:
                    # як fallback — пропускаємо рядок, стабільність > повнота
                    continue
            g.write(json.dumps(o, ensure_ascii=False) + "\n")

    print(f"Wrote {out} (rows={args.count})")

if __name__ == "__main__":
    main()
