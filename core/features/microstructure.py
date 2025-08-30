"""
Aurora+ScalpBot — core/features/microstructure.py
-----------------------------------------------
Microstructure features for high-frequency trading signals.

Implements (§ R1/Road_map alignment):
- Order book imbalance (OBI) with depth weighting
- Time-to-fill (TTF) estimation with queue position
- Absorption ratio for market impact modeling
- Micro-price calculation with inventory weighting
- Realized spread decomposition
- Volume profile analysis

Features are designed for low-latency processing with minimal allocations.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
import math

try:  # pragma: no cover
    from core.types import MarketSnapshot, Trade, Side, OrderType, ExecMode
except Exception:  # pragma: no cover - fallback for standalone testing
    from enum import Enum

    class Side(str, Enum):
        BUY = "BUY"
        SELL = "SELL"

    class OrderType(str, Enum):
        LIMIT = "LIMIT"
        MARKET = "MARKET"

    class ExecMode(str, Enum):
        MAKER = "MAKER"
        TAKER = "TAKER"

    @dataclass
    class Trade:
        timestamp: float
        price: float
        size: float
        side: Side

    @dataclass
    class MarketSnapshot:
        timestamp: float
        bid_price: float
        ask_price: float
        bid_volumes_l: Sequence[float]
        ask_volumes_l: Sequence[float]
        trades: Sequence[Trade]

        @property
        def mid(self) -> float:
            return 0.5 * (self.bid_price + self.ask_price)

        @property
        def quoted_spread(self) -> float:
            return self.ask_price - self.bid_price


@dataclass
class MicrostructureFeatures:
    """Container for microstructure features."""

    # Order book imbalance
    obi_depth_5: float = 0.0  # OBI with top 5 levels
    obi_depth_10: float = 0.0  # OBI with top 10 levels
    obi_weighted: float = 0.0  # Volume-weighted OBI

    # Micro-price
    micro_price: float = 0.0  # Inventory-weighted mid
    micro_price_depth: int = 5  # Levels used for micro-price

    # Spread metrics
    effective_spread: float = 0.0  # 2 * |price - mid|
    realized_spread: float = 0.0  # Round-trip spread
    quoted_spread: float = 0.0  # ask - bid

    # Volume profile
    volume_imbalance: float = 0.0  # Buy volume - Sell volume
    volume_ratio: float = 0.0  # Buy volume / (Buy + Sell volume)

    # Absorption
    absorption_ratio: float = 0.0  # Market impact absorption
    absorption_depth: float = 0.0  # Depth available for absorption

    # Time-to-fill estimates
    ttf_estimate: float = 0.0  # Estimated time to fill order
    queue_position: float = 0.0  # Estimated queue position

    # Market quality
    market_depth: float = 0.0  # Total quoted depth
    liquidity_ratio: float = 0.0  # Bid depth / Ask depth

    # Timestamp for feature freshness
    timestamp: float = 0.0


class MicrostructureEngine:
    """Engine for computing microstructure features from market data."""

    def __init__(self, max_depth: int = 20) -> None:
        self.max_depth = max_depth
        self._prev_trades: List[Trade] = []
        self._trade_window_s = 30.0  # Window for realized spread

    def compute_features(
        self,
        snapshot: MarketSnapshot,
        recent_trades: Optional[Sequence[Trade]] = None,
    ) -> MicrostructureFeatures:
        """Compute all microstructure features from current snapshot."""

        features = MicrostructureFeatures(timestamp=snapshot.timestamp)

        # Basic spread metrics
        features.quoted_spread = snapshot.ask_price - snapshot.bid_price
        features.market_depth = sum(snapshot.bid_volumes_l) + sum(snapshot.ask_volumes_l)
        features.liquidity_ratio = (
            sum(snapshot.bid_volumes_l) / sum(snapshot.ask_volumes_l)
            if sum(snapshot.ask_volumes_l) > 0
            else 1.0
        )

        # Order book imbalance
        features.obi_depth_5 = self._compute_obi(snapshot, depth=5)
        features.obi_depth_10 = self._compute_obi(snapshot, depth=10)
        features.obi_weighted = self._compute_weighted_obi(snapshot)

        # Micro-price
        features.micro_price = self._compute_micro_price(snapshot)

        # Volume profile from recent trades
        if recent_trades:
            features.volume_imbalance, features.volume_ratio = self._compute_volume_profile(recent_trades)

        # Absorption metrics
        features.absorption_ratio, features.absorption_depth = self._compute_absorption(snapshot)

        # Time-to-fill estimates
        features.ttf_estimate, features.queue_position = self._estimate_ttf(snapshot)

        # Update trade history for realized spread
        if recent_trades:
            self._update_trade_history(recent_trades)
            features.realized_spread = self._compute_realized_spread(snapshot.mid)

        return features

    def _compute_obi(self, snapshot: MarketSnapshot, depth: int) -> float:
        """Compute order book imbalance with specified depth."""
        bid_vol = sum(snapshot.bid_volumes_l[:depth])
        ask_vol = sum(snapshot.ask_volumes_l[:depth])
        total_vol = bid_vol + ask_vol
        return (bid_vol - ask_vol) / total_vol if total_vol > 0 else 0.0

    def _compute_weighted_obi(self, snapshot: MarketSnapshot) -> float:
        """Compute volume-weighted order book imbalance."""
        bid_weighted = sum(
            vol / (1 + i)  # Weight by inverse distance from top
            for i, vol in enumerate(snapshot.bid_volumes_l[:self.max_depth])
        )
        ask_weighted = sum(
            vol / (1 + i)
            for i, vol in enumerate(snapshot.ask_volumes_l[:self.max_depth])
        )
        total_weighted = bid_weighted + ask_weighted
        return (bid_weighted - ask_weighted) / total_weighted if total_weighted > 0 else 0.0

    def _compute_micro_price(self, snapshot: MarketSnapshot, depth: int = 5) -> float:
        """Compute micro-price using inventory weighting."""
        bid_vol = sum(snapshot.bid_volumes_l[:depth])
        ask_vol = sum(snapshot.ask_volumes_l[:depth])

        if bid_vol == 0 and ask_vol == 0:
            return snapshot.mid

        # Micro-price formula: weighted average of bid/ask with inventory
        micro_price = (
            snapshot.bid_price * ask_vol + snapshot.ask_price * bid_vol
        ) / (bid_vol + ask_vol)

        return micro_price

    def _compute_volume_profile(self, trades: Sequence[Trade]) -> Tuple[float, float]:
        """Compute volume imbalance and ratio from recent trades."""
        buy_vol = sum(trade.size for trade in trades if trade.side == Side.BUY)
        sell_vol = sum(trade.size for trade in trades if trade.side == Side.SELL)
        total_vol = buy_vol + sell_vol

        imbalance = buy_vol - sell_vol
        ratio = buy_vol / total_vol if total_vol > 0 else 0.5

        return imbalance, ratio

    def _compute_absorption(self, snapshot: MarketSnapshot) -> Tuple[float, float]:
        """Compute absorption ratio and available depth."""
        # Absorption ratio: how much volume is needed to move price by 1%
        price_move_pct = 0.01
        target_price = snapshot.mid * (1 + price_move_pct)

        # Estimate volume needed to reach target price
        absorption_vol = 0.0
        current_price = snapshot.ask_price

        for i, vol in enumerate(snapshot.ask_volumes_l):
            if current_price >= target_price:
                break
            absorption_vol += vol
            # Approximate next price level
            current_price += snapshot.quoted_spread * 0.1

        total_depth = sum(snapshot.ask_volumes_l)
        absorption_ratio = absorption_vol / total_depth if total_depth > 0 else 0.0

        return absorption_ratio, total_depth

    def _estimate_ttf(self, snapshot: MarketSnapshot) -> Tuple[float, float]:
        """Estimate time-to-fill and queue position for a market order."""
        # Simplified TTF estimation based on order book depth
        avg_spread = snapshot.quoted_spread
        total_depth = sum(snapshot.bid_volumes_l) + sum(snapshot.ask_volumes_l)

        # Assume order size is 1 standard lot (simplified)
        order_size = 1.0

        if total_depth == 0:
            return float('inf'), 1.0

        # Time estimate based on depth and typical fill rates
        fill_rate_per_second = total_depth / 10.0  # Rough estimate
        ttf_seconds = order_size / fill_rate_per_second

        # Queue position estimate (simplified)
        queue_pos = min(1.0, order_size / total_depth)

        return ttf_seconds, queue_pos

    def _update_trade_history(self, trades: Sequence[Trade]) -> None:
        """Update trade history for realized spread calculation."""
        self._prev_trades.extend(trades)

        # Keep only recent trades
        cutoff_time = trades[-1].timestamp - self._trade_window_s if trades else 0
        self._prev_trades = [
            trade for trade in self._prev_trades
            if trade.timestamp >= cutoff_time
        ]

    def _compute_realized_spread(self, current_mid: float) -> float:
        """Compute realized spread from round-trip trades."""
        if len(self._prev_trades) < 2:
            return 0.0

        # Find round-trip: buy followed by sell or vice versa
        realized_spreads = []

        for i in range(len(self._prev_trades) - 1):
            trade1 = self._prev_trades[i]
            trade2 = self._prev_trades[i + 1]

            if trade1.side != trade2.side:
                # Round trip detected
                spread = 2 * abs(trade2.price - trade1.price)
                realized_spreads.append(spread)

        return sum(realized_spreads) / len(realized_spreads) if realized_spreads else 0.0


# =============================
# Self-tests
# =============================

def _create_test_snapshot() -> MarketSnapshot:
    """Create a test market snapshot."""
    return MarketSnapshot(
        timestamp=1000.0,
        bid_price=99.98,
        ask_price=100.02,
        bid_volumes_l=[10.0, 8.0, 6.0, 4.0, 2.0, 1.0, 0.5],
        ask_volumes_l=[12.0, 9.0, 7.0, 5.0, 3.0, 2.0, 1.0],
        trades=[
            Trade(999.0, 100.00, 5.0, Side.BUY),
            Trade(999.5, 100.01, 3.0, Side.SELL),
        ]
    )


def _create_test_trades() -> List[Trade]:
    """Create test trades for volume profile."""
    return [
        Trade(995.0, 99.99, 10.0, Side.BUY),
        Trade(996.0, 100.01, 8.0, Side.SELL),
        Trade(997.0, 100.00, 6.0, Side.BUY),
        Trade(998.0, 100.02, 4.0, Side.SELL),
    ]


def _test_microstructure_features() -> None:
    """Test microstructure feature computation."""
    engine = MicrostructureEngine()
    snapshot = _create_test_snapshot()
    trades = _create_test_trades()

    features = engine.compute_features(snapshot, trades)

    # Basic validations
    assert features.timestamp == snapshot.timestamp
    assert features.quoted_spread == snapshot.ask_price - snapshot.bid_price
    assert features.market_depth > 0

    # OBI should be between -1 and 1
    assert -1 <= features.obi_depth_5 <= 1
    assert -1 <= features.obi_weighted <= 1

    # Micro-price should be reasonable
    mid = snapshot.mid
    assert mid - 0.1 <= features.micro_price <= mid + 0.1

    # Volume metrics
    assert features.volume_ratio >= 0 and features.volume_ratio <= 1

    # Absorption metrics
    assert features.absorption_ratio >= 0
    assert features.absorption_depth >= 0

    # TTF estimates
    assert features.ttf_estimate >= 0
    assert 0 <= features.queue_position <= 1

    print("Microstructure features test passed")


if __name__ == "__main__":
    _test_microstructure_features()
    print("OK - core/features/microstructure.py self-tests passed")