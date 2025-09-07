from __future__ import annotations

"""
Local pre-trade ping to trigger diagnostics in core/aurora/pipeline.
Runs FastAPI app in-process and posts a minimal /pretrade/check request.
"""

import os
import sys
from pathlib import Path
from pprint import pprint

# Minimal env required by api/service lifespan
os.environ.setdefault("AURORA_API_TOKEN", "x" * 32)
os.environ.setdefault("AURORA_MODE", "testnet")

from fastapi.testclient import TestClient  # type: ignore
# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.service import app


def main() -> None:
    client = TestClient(app)
    payload = {
        "account": {"mode": "testnet"},
        "order": {
            "symbol": "BINANCE:BTC/USDT",
            "side": "buy",
            "qty": 0.001,
            "price": 100.0,
        },
        "market": {
            "latency_ms": 12.0,
            "slip_bps_est": 0.8,
            "a_bps": 6.0,
            "b_bps": 8.0,
            "spread_bps": 2.0,
            "score": 0.1,
            "mode_regime": "normal",
        },
        "fees_bps": 0.08,
    }

    print("Posting /pretrade/check with payload:")
    pprint(payload)
    resp = client.post("/pretrade/check", json=payload)
    print("\nResponse status:", resp.status_code)
    try:
        data = resp.json()
        print("Response JSON:")
        pprint(data)
    except Exception:
        print("Raw response:", resp.text)


if __name__ == "__main__":
    main()
