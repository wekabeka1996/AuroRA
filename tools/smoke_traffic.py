from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import random
import time
from typing import Any

import requests


@dataclass
class Stats:
    ok: int = 0
    fail: int = 0
    blocked: int = 0
    last_reason: str | None = None


def make_payload(symbol: str) -> dict[str, Any]:
    # Generate a plausible pretrade payload; use testnet mode
    # Randomize a bit to exercise gates deterministically
    a_bps = random.uniform(3.0, 8.0)
    b_bps = a_bps + random.uniform(3.0, 10.0)
    slip_bps = random.uniform(0.2, 2.0)
    spread_bps = random.uniform(2.0, 10.0)
    score = random.uniform(0.2, 0.8)

    # Occasionally inject a TRAP-ish pattern
    if random.random() < 0.25:
        cancel = [random.uniform(2, 10) for _ in range(5)]
        add = [0.0 for _ in range(5)]
        ntr = 1
    else:
        cancel = [random.uniform(0, 1) for _ in range(5)]
        add = [random.uniform(0, 1) for _ in range(5)]
        ntr = random.randint(1, 3)

    payload = {
        "account": {"mode": "testnet"},
        "order": {"symbol": symbol, "qty": 1.0, "base_notional": 100.0},
        "market": {
            "latency_ms": random.uniform(3.0, 25.0),
            "slip_bps_est": slip_bps,
            "a_bps": a_bps,
            "b_bps": b_bps,
            "score": score,
            "mode_regime": "normal",
            "spread_bps": spread_bps,
            "trap_cancel_deltas": cancel,
            "trap_add_deltas": add,
            "trap_trades_cnt": ntr,
        },
        "fees_bps": 0.2,
    }
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--duration-min", type=int, default=10)
    ap.add_argument("--rps", type=float, default=5.0)
    ap.add_argument("--symbol", default="BTCUSDT")
    args = ap.parse_args()

    url = args.base_url.rstrip("/") + "/pretrade/check"
    period = 1.0 / max(0.1, float(args.rps))
    deadline = time.time() + args.duration_min * 60
    s = requests.Session()
    stats = Stats()

    print(f"SMOKE traffic: {args.duration_min} min @ {args.rps} rps → {url}")

    i = 0
    while time.time() < deadline:
        t0 = time.time()
        try:
            resp = s.post(url, json=make_payload(args.symbol), timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                if bool(data.get("allow")):
                    stats.ok += 1
                else:
                    stats.blocked += 1
                    stats.last_reason = str(data.get("reason"))
            else:
                stats.fail += 1
        except Exception:
            stats.fail += 1

        i += 1
        # pacing
        dt = time.time() - t0
        sleep_s = max(0.0, period - dt)
        if sleep_s:
            time.sleep(sleep_s)

    print(json.dumps({
        "ok": stats.ok,
        "blocked": stats.blocked,
        "fail": stats.fail,
        "last_reason": stats.last_reason,
    }))

if __name__ == "__main__":
    main()
