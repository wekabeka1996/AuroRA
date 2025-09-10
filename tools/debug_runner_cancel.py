import os
from pathlib import Path
import time

from skalp_bot.runner import run_live_aurora as runner

# Setup fixed session dir
sess = Path('.').resolve() / 'tmp_debug_cancel'
if sess.exists():
    import shutil
    shutil.rmtree(sess)
sess.mkdir(parents=True, exist_ok=True)
os.environ['AURORA_SESSION_DIR'] = str(sess)
os.environ['AURORA_MAX_TICKS'] = '4'
os.environ['EXCHANGE_TESTNET'] = 'true'
os.environ['DRY_RUN'] = 'true'

# Prepare FakeAdapterPending from tests
class FakeAdapter:
    def __init__(self, cfg, *, should_fail: bool = False, symbol: str = "BTC/USDT") -> None:
        self._should_fail = should_fail
        self.symbol = symbol
        self._positions = []

    def fetch_top_of_book(self):
        mid = 50000.0
        bids = [(49999.5, 0.5), (49999.0, 0.5)]
        asks = [(50000.5, 0.5), (50001.0, 0.5)]
        trades = [{"ts": int(time.time() * 1000), "price": 50000.0, "qty": 0.01, "side": 1}]
        spread = asks[0][0] - bids[0][0]
        return mid, spread, bids, asks, trades

    def fetch_ohlcv_1m(self, limit=100):
        now_ms = int(time.time() * 1000)
        return [[now_ms - i * 60000, 1, 2, 0, 1 + i * 0.001] for i in range(limit)][-limit:]

    def get_gross_exposure_usdt(self):
        return 0.0

    def get_positions(self):
        return list(self._positions)

    def cancel_all(self):
        return None

    def place_order(self, side: str, qty: float, price=None):
        return {"id": f"oid-pend-{int(time.time()*1e6)}", "status": "open", "filled": 0.0, "info": {"orderId": f"oid-pend-{int(time.time()*1e6)}"}}

    def close_position(self, side: str, qty: float):
        return {"id": f"oid-close-{int(time.time()*1e6)}", "status": "closed", "filled": float(qty), "info": {"orderId": f"oid-close-{int(time.time()*1e6)}"}}

# Monkeypatch runner components
runner.CCXTBinanceAdapter = lambda cfg: FakeAdapter(cfg, should_fail=False)
runner.AuroraGate = lambda base_url, mode, timeout_s: type('G', (), {'check': lambda *a, **k: {'allow': True}, 'posttrade': lambda **p: {'ok': True}})()

# Sequenced scores: open then exit
seq = [1.0, 0.0, 0.0, 0.0]
def compute_alpha_score(features, rp, weights=None):
    return seq.pop(0) if seq else 0.0
runner.compute_alpha_score = compute_alpha_score
runner.obi_from_l5 = lambda bids, asks, levels: 0.30
runner.tfi_from_trades = lambda trades: 0.20
runner.time.sleep = lambda s: None

# Run
runner.main(None, None)

# Print logs
print('SESSION DIR:', sess)
for name in ['aurora_events.jsonl', 'orders_success.jsonl', 'orders_failed.jsonl', 'orders_denied.jsonl']:
    p = sess / name
    print('\n====', name, 'exists=', p.exists(), 'size=', p.stat().st_size if p.exists() else None)
    if p.exists():
        print(p.read_text(encoding='utf-8'))

print('Done')
