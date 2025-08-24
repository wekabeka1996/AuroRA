from fastapi.testclient import TestClient
from api.service import app

client = TestClient(app)

payload = {
    "account": {"mode": "shadow"},
    "order": {"qty": 1.0},
    "market": {
        "latency_ms": 5.0,
        "slip_bps_est": 0.5,
        "a_bps": 5.0,
        "b_bps": 12.0,
        "score": 0.5,
        "mode_regime": "normal",
        "spread_bps": 5.0,
        "trap_cancel_deltas": [10, 8, 6, 4, 2],
        "trap_add_deltas": [0, 0, 0, 0, 0],
        "trap_trades_cnt": 1,
    },
    "fees_bps": 0.2,
}

r = client.post("/pretrade/check", json=payload)
print('STATUS:', r.status_code)
print('HEADERS:', r.headers)
print('TEXT:\n', r.text)
try:
    print('JSON:\n', r.json())
except Exception as e:
    print('JSON parse error:', e)

# Exit code based on status for CI convenience
import sys
sys.exit(0 if r.status_code == 200 else 2)
