from __future__ import annotations

import time
from typing import Any, Dict, Optional
import os

from core.execution.sim_local_sink import SimLocalSink


class SimAdapter:
    """Adapter that exposes minimal exchange-like API backed by SimLocalSink.

    This allows the runner to call the same methods (fetch_top_of_book, place_order, cancel_all)
    while delegating execution to the local simulator. Designed for tests and offline runs.
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}
        # Create a SimLocalSink with passed cfg and default event logger
        self._sink = SimLocalSink(cfg=self.cfg)
        # Symbol placeholder
        self.symbol = self.cfg.get('symbol', 'TEST/USDT')
        # Optional biases to drive positive features in diagnostics
        def _to_float(x: Any, default: float = 0.0) -> float:
            try:
                return float(x)
            except Exception:
                return default
        self._obi_bias = _to_float(self.cfg.get('mock_obi_bias', os.getenv('AURORA_SIM_OBI_BIAS', 0.0)), 0.0)
        self._tfi_bias = _to_float(self.cfg.get('mock_tfi_bias', os.getenv('AURORA_SIM_TFI_BIAS', 0.0)), 0.0)

    def fetch_top_of_book(self):
        # Return a deterministic snapshot; allow slight asymmetry via biases
        mid = float(self.cfg.get('mock_mid', 100.0))
        spread = float(self.cfg.get('mock_spread', 0.01))
        bid = mid - spread / 2.0
        ask = mid + spread / 2.0
        # Volume asymmetry to produce OBI != 0
        q_base = 1.0
        q_bid = max(0.1, q_base + self._obi_bias)
        q_ask = max(0.1, q_base - self._obi_bias)
        bids = [(bid, q_bid)]
        asks = [(ask, q_ask)]
        # Simple trade imbalance to drive TFI != 0
        t_buy = max(0.0, 1.0 + self._tfi_bias)
        t_sell = max(0.0, 1.0 - self._tfi_bias)
        trades = [
            {"side": "buy", "amount": t_buy, "price": ask, "timestamp": int(time.time() * 1000)},
            {"side": "sell", "amount": t_sell, "price": bid, "timestamp": int(time.time() * 1000)}
        ]
        return mid, spread, bids, asks, trades

    def place_order(self, side: str, qty: float, price: Optional[float] = None):
        order = {'side': side, 'qty': qty, 'price': price, 'order_id': None, 'order_type': 'market' if price is None else 'limit'}
        oid = self._sink.submit(order, market={'best_bid': None, 'best_ask': None, 'liquidity': {}})
        # Return a minimal dict compatible with runner expectations
        return {'id': oid, 'status': 'closed'}

    def cancel_all(self):
        # Simpler no-op for sim adapter
        return True

