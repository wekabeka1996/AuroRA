import sys

_MULT = {"ns": 1, "ms": 1_000_000, "s": 1_000_000_000}

def to_ns(ts: int | float, ts_unit: str) -> int:
    if ts_unit not in _MULT:
        print(f"[timescale] Unknown ts_unit='{ts_unit}'. Allowed: ns|ms|s", file=sys.stderr)
        raise SystemExit(62)
    return int(float(ts) * _MULT[ts_unit])
