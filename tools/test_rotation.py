# tools/test_rotation.py
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
import time


def _last_line_is_valid_json(p: Path) -> bool:
    try:
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt", encoding="utf-8") as f:
            last = None
            for line in f:
                if line.strip():
                    last = line
        if not last:
            return False
        obj = json.loads(last)
        ts = obj.get("time", "")
        return isinstance(obj, dict) and isinstance(ts, str) and ts.endswith("Z")
    except Exception:
        return False


def _write_jsonl_stub(dst: Path, n: int = 1000) -> None:
    # детермінований рядок з ISO-Z
    row = {"time": "2025-01-01T00:00:00.000Z", "msg": "ok", "source": "rotation_test"}
    with open(dst, "w", encoding="utf-8") as f:
        for _ in range(n):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rotate_one(current: Path, gz_name: str) -> Path:
    gz_path = current.with_name(gz_name)
    with open(current, "rb") as src, gzip.open(gz_path, "wb") as dst:
        dst.write(src.read())
    # почистити current (імітація rollover)
    current.write_text("", encoding="utf-8")
    return gz_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-name", default="exec", help="basename без розширення")
    ap.add_argument("--max-mb", type=float, default=1.0, help="межа розміру перед ротацією")
    ap.add_argument("--retention", type=int, default=5, help="скільки .gz зберігати")
    ap.add_argument("--rounds", type=int, default=8, help="скільки разів перекочувати")
    ap.add_argument("--dir", default="logs", help="каталог логів")
    args = ap.parse_args()

    logdir = Path(args.dir)
    logdir.mkdir(parents=True, exist_ok=True)
    current = logdir / f"{args.log_name}.jsonl"  # type: ignore[attr-defined]

    # прибрати тільки наші попередні .gz цього basename
    pattern = f"{args.log_name}.jsonl.*.gz"
    for p in logdir.glob(pattern):
        try: p.unlink()
        except: pass
    try:
        current.unlink()
    except:
        pass

    # Емуляція наповнення + ротації
    target_bytes = int(args.max_mb * 1024 * 1024)
    for _ in range(args.rounds):
        # наповнюємо файл до > max_mb
        _write_jsonl_stub(current, n=5000)
        if current.stat().st_size <= target_bytes:
            # дописати ще трохи, поки не перевищимо поріг
            while current.stat().st_size <= target_bytes:
                _write_jsonl_stub(current, n=2000)

        ts = int(time.time() * 1000)
        gz_name = f"{args.log_name}.jsonl.{ts}.gz"
        _rotate_one(current, gz_name)

        # Тримати не більше retention gzip-файлів
        gz_list = sorted(logdir.glob(pattern))
        while len(gz_list) > args.retention:
            gz_list[0].unlink()
            gz_list.pop(0)

    # Перевірки (gate)
    gz_list = sorted(logdir.glob(pattern))
    ok_cnt = len(gz_list) <= args.retention
    ok_tail = all(_last_line_is_valid_json(p) for p in gz_list)

    print(f"kept_gz={len(gz_list)} (<= {args.retention})")
    print(f"tail_json_Z_valid={ok_tail}")
    for p in gz_list:
        print(f"check {p.name}: valid_tail={_last_line_is_valid_json(p)}")

    if ok_cnt and ok_tail:
        print("ROTATION_OK")
        raise SystemExit(0)
    else:
        if not ok_cnt:
            print("ROTATION_FAIL: retention exceeded")
        if not ok_tail:
            print("ROTATION_FAIL: invalid tail JSON/ISO-Z")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
