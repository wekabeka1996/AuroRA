from __future__ import annotations

from typing import Any

from core.execution.sim_local_sink import SimLocalSink


class SimAdapter:
    """Adapter that exposes minimal exchange-like API backed by SimLocalSink.

    This allows the runner to call the same methods (fetch_top_of_book, place_order, cancel_all)
    while delegating execution to the local simulator. Designed for tests and offline runs.
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}
        # Create a SimLocalSink with passed cfg and default event logger
        self._sink = SimLocalSink(cfg=self.cfg)
        # Symbol placeholder
        self.symbol = self.cfg.get('symbol', 'TEST/USDT')

    def fetch_top_of_book(self):
        # Return a deterministic snapshot; used by runner in tests
        mid = self.cfg.get('mock_mid', 100.0)
        spread = self.cfg.get('mock_spread', 0.01)
        bid = mid - spread / 2.0
        ask = mid + spread / 2.0
        bids = [(bid, 1.0)]
        asks = [(ask, 1.0)]
        trades = []
        return mid, spread, bids, asks, trades

    def place_order(self, side: str, qty: float, price: float | None = None):
        order = {'side': side, 'qty': qty, 'price': price, 'order_id': None, 'order_type': 'market' if price is None else 'limit'}
        oid = self._sink.submit(order, market={'best_bid': None, 'best_ask': None, 'liquidity': {}})
        # Return a minimal dict compatible with runner expectations
        return {'id': oid, 'status': 'closed'}

    def cancel_all(self):
        # Simpler no-op for sim adapter
        return True

