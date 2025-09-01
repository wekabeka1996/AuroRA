import os
import time
import tempfile
from pathlib import Path

from skalp_bot.runner import run_live_aurora as runner


class FakeAdapterPending(runner.FakeAdapter if hasattr(runner, 'FakeAdapter') else object):
    def __init__(self, cfg, *, should_fail: bool = False, symbol: str = "BTC/USDT") -> None:
        # Use simple fake shape compatible with tests
        self._should_fail = should_fail
        self.symbol = symbol

    def fetch_top_of_book(self):
        mid = 50000.0
        bids = [(49999.5, 0.5)]
        asks = [(50000.5, 0.5)]
        trades = []
        return mid, (asks[0][0] - bids[0][0]), bids, asks, trades

    def place_order(self, side: str, qty: float, price=None):
        return {"id": f"oid-pend-{int(time.time()*1e6)}", "status": "open", "filled": 0.0, "info": {"orderId": f"oid-pend-{int(time.time()*1e6)}"}}

    def cancel_all(self):
        return None


def main():
    tmp = Path(tempfile.mkdtemp(prefix="aurora_dbg_"))
    os.environ["AURORA_SESSION_DIR"] = str(tmp)
    os.environ["AURORA_MAX_TICKS"] = "4"
    os.environ["EXCHANGE_TESTNET"] = "true"
    os.environ["DRY_RUN"] = "true"

    # Monkeypatch the module adapters/gate and deterministic signals
    runner.CCXTBinanceAdapter = lambda cfg: FakeAdapterPending(cfg, should_fail=False)  # type: ignore
    class AllowGate:
        def __init__(self, base_url, mode, timeout_s):
            self._base = base_url
            self._mode = mode
            self._timeout = timeout_s
        def check(self, account, order, market, risk_tags=("scalping", "auto"), fees_bps: float = 1.0):
            return {"allow": True, "max_qty": order.get("qty", 0.001), "reason": "OK", "observability": {"gate_state": "ALLOW"}, "cooldown_ms": 0}
        def posttrade(self, **payload):
            return {"ok": True}

    runner.AuroraGate = lambda base_url, mode, timeout_s: AllowGate(base_url, mode, timeout_s)  # type: ignore
    seq = [1.0, 0.0, 0.0, 0.0]
    runner.compute_alpha_score = lambda features, rp, weights=None: seq.pop(0) if seq else 0.0  # type: ignore
    runner.obi_from_l5 = lambda bids, asks, levels: 0.30  # type: ignore
    runner.tfi_from_trades = lambda trades: 0.20  # type: ignore
    runner.time.sleep = lambda s: None  # type: ignore

    runner.main(None, None)

    ev_file = tmp / "aurora_events.jsonl"
    print("Session dir:", tmp)
    if ev_file.exists():
        print("Events:")
        for l in ev_file.read_text(encoding='utf-8').splitlines():
            print(l)
    else:
        print("No events file found")


if __name__ == '__main__':
    main()
