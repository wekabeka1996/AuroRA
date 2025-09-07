"""
Tests — Features Module
=======================

Comprehensive test coverage for Aurora features module.
"""

from __future__ import annotations

import pytest
import time
import math
from typing import List
from unittest.mock import patch

from core.features.tfi import (
    tfi_increment,
    vpin_like,
    vpin_volume_buckets,
    TFIStream,
    _Rolling,
    _WinTrade,
    _make_trades_imbalanced,
    _make_trades_balanced,
    _test_event_time_tfi_vpin,
    _test_vpin_contrast
)
from core.types import Trade, Side
from core.features.microstructure import MicrostructureFeatures, MicrostructureEngine, MarketSnapshot
from core.features.scaling import (
    _clip,
    Welford,
    P2Quantile,
    RobustMedianMAD,
    ZScoreScaler,
    RobustScaler,
    HysteresisMinMax,
    DictFeatureScaler
)


class TestTFIFeatures:
    """Test TFI (Trade Flow Imbalance) features."""

    def test_tfi_increment_buy_side(self):
        """Test tfi_increment with BUY side."""
        trade = Trade(timestamp=1000.0, price=100.0, size=10.0, side=Side.BUY)
        result = tfi_increment(trade)
        assert result == 10.0

    def test_tfi_increment_sell_side(self):
        """Test tfi_increment with SELL side."""
        trade = Trade(timestamp=1000.0, price=100.0, size=10.0, side=Side.SELL)
        result = tfi_increment(trade)
        assert result == -10.0

    def test_tfi_increment_string_side_buy(self):
        """Test tfi_increment with string BUY side."""
        trade = Trade(timestamp=1000.0, price=100.0, size=15.0, side="BUY")
        result = tfi_increment(trade)
        assert result == 15.0

    def test_tfi_increment_string_side_sell(self):
        """Test tfi_increment with string SELL side."""
        trade = Trade(timestamp=1000.0, price=100.0, size=15.0, side="SELL")
        result = tfi_increment(trade)
        assert result == -15.0

    def test_tfi_increment_unknown_side(self):
        """Test tfi_increment with unknown side (defaults to SELL behavior)."""
        trade = Trade(timestamp=1000.0, price=100.0, size=20.0, side="UNKNOWN")
        result = tfi_increment(trade)
        assert result == -20.0

    def test_vpin_like_balanced_volumes(self):
        """Test vpin_like with equal buy/sell volumes."""
        result = vpin_like(100.0, 100.0)
        assert result == 0.0

    def test_vpin_like_buy_dominant(self):
        """Test vpin_like with more buy volume."""
        result = vpin_like(150.0, 50.0)
        assert result == 0.5  # |150-50| / (150+50) = 100/200 = 0.5

    def test_vpin_like_sell_dominant(self):
        """Test vpin_like with more sell volume."""
        result = vpin_like(50.0, 150.0)
        assert result == 0.5  # |50-150| / (50+150) = 100/200 = 0.5

    def test_vpin_like_zero_denominator(self):
        """Test vpin_like with zero total volume."""
        result = vpin_like(0.0, 0.0)
        assert result == 0.0

    def test_vpin_like_negative_volumes(self):
        """Test vpin_like with negative volumes (should handle gracefully)."""
        result = vpin_like(-10.0, -20.0)
        assert result == 0.0  # Negative total volume returns 0.0

    def test_vpin_volume_buckets_empty_trades(self):
        """Test vpin_volume_buckets with empty trades."""
        result = vpin_volume_buckets([], 100.0)
        assert result == 0.0

    def test_vpin_volume_buckets_single_bucket(self):
        """Test vpin_volume_buckets with trades filling exactly one bucket."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=50.0, side=Side.BUY),
            Trade(timestamp=2.0, price=100.0, size=50.0, side=Side.SELL)
        ]
        result = vpin_volume_buckets(trades, 100.0)
        assert result == 0.0  # |50-50| / 100 = 0

    def test_vpin_volume_buckets_imbalanced_bucket(self):
        """Test vpin_volume_buckets with imbalanced bucket."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=70.0, side=Side.BUY),
            Trade(timestamp=2.0, price=100.0, size=30.0, side=Side.SELL)
        ]
        result = vpin_volume_buckets(trades, 100.0)
        assert result == 0.4  # |70-30| / 100 = 40/100 = 0.4

    def test_vpin_volume_buckets_multiple_buckets(self):
        """Test vpin_volume_buckets with multiple buckets."""
        trades = [
            # First bucket: 70 buy, 30 sell → imbalance 0.4
            Trade(timestamp=1.0, price=100.0, size=70.0, side=Side.BUY),
            Trade(timestamp=2.0, price=100.0, size=30.0, side=Side.SELL),
            # Second bucket: 80 buy, 20 sell → imbalance 0.6
            Trade(timestamp=3.0, price=100.0, size=80.0, side=Side.BUY),
            Trade(timestamp=4.0, price=100.0, size=20.0, side=Side.SELL)
        ]
        result = vpin_volume_buckets(trades, 100.0)
        expected = (0.4 + 0.6) / 2  # Average of bucket imbalances
        assert abs(result - expected) < 1e-10

    def test_vpin_volume_buckets_partial_bucket_ignored(self):
        """Test vpin_volume_buckets ignores partial final bucket."""
        trades = [
            # Complete bucket: 60 buy, 40 sell → imbalance 0.2
            Trade(timestamp=1.0, price=100.0, size=60.0, side=Side.BUY),
            Trade(timestamp=2.0, price=100.0, size=40.0, side=Side.SELL),
            # Partial bucket: only 30 buy, should be ignored
            Trade(timestamp=3.0, price=100.0, size=30.0, side=Side.BUY)
        ]
        result = vpin_volume_buckets(trades, 100.0)
        assert result == 0.2  # Only complete bucket counted

    def test_vpin_volume_buckets_large_trade_split(self):
        """Test vpin_volume_buckets splits large trades across buckets."""
        # Large trade of 250 units split across 3 buckets of 100 each
        trades = [
            Trade(timestamp=1.0, price=100.0, size=250.0, side=Side.BUY)
        ]
        result = vpin_volume_buckets(trades, 100.0)
        # First bucket: 100 buy, 0 sell → imbalance 1.0
        # Second bucket: 100 buy, 0 sell → imbalance 1.0
        # Third bucket: 50 buy, 0 sell → partial, ignored
        expected = (1.0 + 1.0) / 2
        assert abs(result - expected) < 1e-10

    def test_vpin_volume_buckets_max_buckets_limit(self):
        """Test vpin_volume_buckets respects max_buckets limit."""
        # Create 10 buckets
        trades = []
        for i in range(10):
            trades.extend([
                Trade(timestamp=float(i*2), price=100.0, size=60.0, side=Side.BUY),
                Trade(timestamp=float(i*2+1), price=100.0, size=40.0, side=Side.SELL)
            ])

        # With max_buckets=5, should only use last 5 buckets
        result = vpin_volume_buckets(trades, 100.0, max_buckets=5)
        assert result == 0.2  # All buckets have imbalance 0.2

    def test_vpin_volume_buckets_zero_bucket_volume(self):
        """Test vpin_volume_buckets with zero bucket volume."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=50.0, side=Side.BUY)
        ]
        result = vpin_volume_buckets(trades, 0.0)
        assert result == 0.0  # Should handle zero bucket volume gracefully

    def test_vpin_volume_buckets_negative_bucket_volume(self):
        """Test vpin_volume_buckets with negative bucket volume."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=50.0, side=Side.BUY)
        ]
        result = vpin_volume_buckets(trades, -10.0)
        assert result == 0.0  # Should handle negative bucket volume gracefully


class TestTFIStream:
    """Test TFIStream streaming class."""

    def test_tfi_stream_initialization(self):
        """Test TFIStream initialization with default parameters."""
        stream = TFIStream()
        assert stream.win.h == 5.0
        assert stream.bucket_volume == 100.0
        assert stream.max_trades == 5000
        assert len(stream._trades) == 0

    def test_tfi_stream_custom_parameters(self):
        """Test TFIStream initialization with custom parameters."""
        stream = TFIStream(window_s=10.0, bucket_volume=200.0, max_trades=1000)
        assert stream.win.h == 10.0
        assert stream.bucket_volume == 200.0
        assert stream.max_trades == 1000

    def test_ingest_trade_buy(self):
        """Test ingesting a BUY trade."""
        stream = TFIStream(window_s=5.0)
        trade = Trade(timestamp=1000.0, price=100.0, size=50.0, side=Side.BUY)

        stream.ingest_trade(trade)

        # Check that trade was added to internal storage
        assert len(stream._trades) == 1
        assert stream._trades[0] == trade

        # Check rolling window sums
        buy_sum, sell_sum = stream.win.sums(1000.0)
        assert buy_sum == 50.0
        assert sell_sum == 0.0

    def test_ingest_trade_sell(self):
        """Test ingesting a SELL trade."""
        stream = TFIStream(window_s=5.0)
        trade = Trade(timestamp=1000.0, price=100.0, size=30.0, side=Side.SELL)

        stream.ingest_trade(trade)

        # Check rolling window sums
        buy_sum, sell_sum = stream.win.sums(1000.0)
        assert buy_sum == 0.0
        assert sell_sum == 30.0

    def test_ingest_trade_string_sides(self):
        """Test ingesting trades with string side representations."""
        stream = TFIStream(window_s=5.0)

        buy_trade = Trade(timestamp=1000.0, price=100.0, size=40.0, side="BUY")
        sell_trade = Trade(timestamp=1001.0, price=100.0, size=20.0, side="SELL")

        stream.ingest_trade(buy_trade)
        stream.ingest_trade(sell_trade)

        buy_sum, sell_sum = stream.win.sums(1001.0)
        assert buy_sum == 40.0
        assert sell_sum == 20.0

    def test_ingest_trade_eviction_by_count(self):
        """Test trade eviction when max_trades limit is reached."""
        stream = TFIStream(max_trades=3)

        # Add 5 trades
        for i in range(5):
            trade = Trade(timestamp=float(1000 + i), price=100.0, size=10.0, side=Side.BUY)
            stream.ingest_trade(trade)

        # Should only keep last 3 trades
        assert len(stream._trades) == 3
        assert stream._trades[0].timestamp == 1002.0
        assert stream._trades[-1].timestamp == 1004.0

    def test_ingest_trade_eviction_by_time(self):
        """Test trade eviction by time horizon."""
        stream = TFIStream(window_s=2.0)

        # Add trades spanning more than 10x window (20 seconds)
        base_time = 1000.0
        for i in range(5):
            trade = Trade(timestamp=base_time + i * 6.0, price=100.0, size=10.0, side=Side.BUY)
            stream.ingest_trade(trade)

        # Should evict old trades (cutoff = current_ts - 10 * window_s = 1000 + 24 - 20 = 1004)
        current_time = base_time + 24.0
        stream.ingest_trade(Trade(timestamp=current_time, price=100.0, size=10.0, side=Side.BUY))

        # Trades before 1004 should be evicted
        for trade in stream._trades:
            assert trade.timestamp >= 1004.0

    def test_features_basic(self):
        """Test basic feature extraction."""
        stream = TFIStream(window_s=5.0, bucket_volume=0.0)  # Disable bucket VPIN

        # Add some trades
        stream.ingest_trade(Trade(timestamp=1000.0, price=100.0, size=50.0, side=Side.BUY))
        stream.ingest_trade(Trade(timestamp=1001.0, price=100.0, size=30.0, side=Side.SELL))

        features = stream.features(now_ts=1002.0)

        assert features["buy_vol"] == 50.0
        assert features["sell_vol"] == 30.0
        assert features["tfi"] == 20.0  # 50 - 30
        assert features["vpin_like"] == 0.25  # |50-30| / (50+30) = 20/80 = 0.25
        assert features["vpin_bucketed"] == 0.0  # Disabled

    def test_features_with_bucket_vpin(self):
        """Test feature extraction with bucket VPIN enabled."""
        stream = TFIStream(window_s=5.0, bucket_volume=100.0)

        # Add trades that fill a bucket
        stream.ingest_trade(Trade(timestamp=1000.0, price=100.0, size=60.0, side=Side.BUY))
        stream.ingest_trade(Trade(timestamp=1001.0, price=100.0, size=40.0, side=Side.SELL))

        features = stream.features(now_ts=1002.0)

        assert features["vpin_bucketed"] == 0.2  # |60-40| / 100 = 20/100 = 0.2

    def test_features_time_windowing(self):
        """Test that features respect time window."""
        stream = TFIStream(window_s=2.0)

        # Add old trade first (chronological order)
        stream.ingest_trade(Trade(timestamp=995.0, price=100.0, size=30.0, side=Side.SELL))

        # Add recent trade
        stream.ingest_trade(Trade(timestamp=1000.0, price=100.0, size=50.0, side=Side.BUY))

        # Check features at time 1002 (old trade should be evicted)
        features = stream.features(now_ts=1002.0)

        assert features["buy_vol"] == 50.0
        assert features["sell_vol"] == 0.0  # Old sell trade evicted
        assert features["tfi"] == 50.0

    def test_features_empty_stream(self):
        """Test features with empty stream."""
        stream = TFIStream()

        features = stream.features()

        assert features["buy_vol"] == 0.0
        assert features["sell_vol"] == 0.0
        assert features["tfi"] == 0.0
        assert features["vpin_like"] == 0.0
        assert features["vpin_bucketed"] == 0.0


class TestRollingWindow:
    """Test _Rolling internal class."""

    def test_rolling_initialization(self):
        """Test _Rolling initialization."""
        rolling = _Rolling(horizon_s=5.0)
        assert rolling.h == 5.0
        assert rolling.bsum == 0.0
        assert rolling.ssum == 0.0
        assert len(rolling.q) == 0

    def test_rolling_add_and_sums(self):
        """Test adding trades and getting sums."""
        rolling = _Rolling(horizon_s=5.0)

        # Add a buy trade
        rolling.add(1000.0, buy=50.0, sell=0.0)
        buy_sum, sell_sum = rolling.sums(1000.0)
        assert buy_sum == 50.0
        assert sell_sum == 0.0

        # Add a sell trade
        rolling.add(1001.0, buy=0.0, sell=30.0)
        buy_sum, sell_sum = rolling.sums(1001.0)
        assert buy_sum == 50.0
        assert sell_sum == 30.0

    def test_rolling_eviction(self):
        """Test eviction of old trades."""
        rolling = _Rolling(horizon_s=2.0)

        # Add trades in chronological order
        rolling.add(995.0, buy=20.0, sell=0.0)   # Will be evicted
        rolling.add(1000.0, buy=50.0, sell=0.0)  # Will be evicted
        rolling.add(1003.0, buy=0.0, sell=30.0)  # Will remain

        # Check sums at time 1004 (cutoff = 1004 - 2 = 1002)
        buy_sum, sell_sum = rolling.sums(1004.0)
        assert buy_sum == 0.0   # Both buy trades evicted
        assert sell_sum == 30.0  # Only recent sell trade remains

    def test_rolling_partial_eviction(self):
        """Test partial eviction scenarios."""
        rolling = _Rolling(horizon_s=3.0)

        # Add multiple trades
        rolling.add(1000.0, buy=10.0, sell=0.0)
        rolling.add(1001.0, buy=0.0, sell=15.0)
        rolling.add(1002.0, buy=20.0, sell=0.0)
        rolling.add(1005.0, buy=0.0, sell=25.0)  # This should evict first two trades

        buy_sum, sell_sum = rolling.sums(1005.0)
        assert buy_sum == 20.0  # Only trade at 1002
        assert sell_sum == 25.0  # Only trade at 1005


class TestWinTrade:
    """Test _WinTrade dataclass."""

    def test_win_trade_creation(self):
        """Test _WinTrade creation."""
        win_trade = _WinTrade(ts=1000.0, buy=50.0, sell=0.0)
        assert win_trade.ts == 1000.0
        assert win_trade.buy == 50.0
        assert win_trade.sell == 0.0

    def test_win_trade_equality(self):
        """Test _WinTrade equality."""
        wt1 = _WinTrade(ts=1000.0, buy=50.0, sell=0.0)
        wt2 = _WinTrade(ts=1000.0, buy=50.0, sell=0.0)
        wt3 = _WinTrade(ts=1001.0, buy=50.0, sell=0.0)

        assert wt1 == wt2
        assert wt1 != wt3


class TestSyntheticTradeGenerators:
    """Test synthetic trade generation functions."""

    def test_make_trades_imbalanced(self):
        """Test _make_trades_imbalanced generates imbalanced trades."""
        trades = _make_trades_imbalanced(n=100, seed=42)

        assert len(trades) == 100

        # Check that trades have proper structure
        for trade in trades:
            assert isinstance(trade.timestamp, float)
            assert trade.price == 100.0
            assert trade.size >= 0.1
            assert trade.side in [Side.BUY, Side.SELL]

        # Should have more BUY than SELL trades (70% buy, 30% sell)
        buy_count = sum(1 for t in trades if t.side == Side.BUY)
        sell_count = sum(1 for t in trades if t.side == Side.SELL)

        assert buy_count > sell_count
        assert buy_count + sell_count == 100

    def test_make_trades_balanced(self):
        """Test _make_trades_balanced generates balanced trades."""
        trades = _make_trades_balanced(n=100, seed=42)

        assert len(trades) == 100

        # Should alternate between BUY and SELL
        for i, trade in enumerate(trades):
            expected_side = Side.BUY if i % 2 == 0 else Side.SELL
            assert trade.side == expected_side

    def test_make_trades_deterministic(self):
        """Test that trade generators are deterministic with same seed."""
        trades1 = _make_trades_imbalanced(n=50, seed=123)
        trades2 = _make_trades_imbalanced(n=50, seed=123)

        assert len(trades1) == len(trades2)
        for t1, t2 in zip(trades1, trades2):
            assert t1.timestamp == t2.timestamp
            assert t1.size == t2.size
            assert t1.side == t2.side


class TestSelfTests:
    """Test the self-test functions."""

    def test_self_test_event_time_tfi_vpin(self):
        """Test _test_event_time_tfi_vpin runs without errors."""
        # This should not raise any exceptions
        _test_event_time_tfi_vpin()

    def test_self_test_vpin_contrast(self):
        """Test _test_vpin_contrast runs without errors."""
        # This should not raise any exceptions
        _test_vpin_contrast()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_tfi_increment_zero_size(self):
        """Test tfi_increment with zero size."""
        trade = Trade(timestamp=1000.0, price=100.0, size=0.0, side=Side.BUY)
        result = tfi_increment(trade)
        assert result == 0.0

    def test_vpin_like_very_small_denominator(self):
        """Test vpin_like with very small denominator."""
        result = vpin_like(1e-10, 1e-10)
        assert result == 0.0

    def test_vpin_volume_buckets_single_trade_partial(self):
        """Test vpin_volume_buckets with single trade smaller than bucket."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=50.0, side=Side.BUY)
        ]
        result = vpin_volume_buckets(trades, 100.0)
        assert result == 0.0  # Partial bucket ignored

    def test_tfi_stream_zero_window(self):
        """Test TFIStream with zero window size."""
        stream = TFIStream(window_s=0.0)

        stream.ingest_trade(Trade(timestamp=1000.0, price=100.0, size=50.0, side=Side.BUY))

        # With zero window, trade should be immediately evicted
        features = stream.features(now_ts=1000.0)
        assert features["buy_vol"] == 0.0
        assert features["sell_vol"] == 0.0

    def test_tfi_stream_zero_bucket_volume(self):
        """Test TFIStream with zero bucket volume."""
        stream = TFIStream(bucket_volume=0.0)

        stream.ingest_trade(Trade(timestamp=1000.0, price=100.0, size=50.0, side=Side.BUY))

        features = stream.features(now_ts=1000.0)
        assert features["vpin_bucketed"] == 0.0

    def test_rolling_zero_horizon(self):
        """Test _Rolling with zero horizon."""
        rolling = _Rolling(horizon_s=0.0)

        rolling.add(1000.0, buy=50.0, sell=0.0)

        # With zero horizon, trade should be immediately evicted
        buy_sum, sell_sum = rolling.sums(1000.0)
        assert buy_sum == 0.0
        assert sell_sum == 0.0

    @patch('time.time')
    def test_features_now_ts_parameter(self, mock_time):
        """Test features method with explicit now_ts parameter."""
        mock_time.return_value = 1005.0

        stream = TFIStream(window_s=5.0)
        stream.ingest_trade(Trade(timestamp=1000.0, price=100.0, size=50.0, side=Side.BUY))

        # Test with explicit now_ts
        features = stream.features(now_ts=1002.0)
        assert features["buy_vol"] == 50.0

        # Test with default (should use mocked time.time)
        features_default = stream.features()
        assert features_default["buy_vol"] == 50.0  # Trade at 1000 should still be in 5s window from 1005


class TestMicrostructureFeatures:
    """Test MicrostructureFeatures dataclass."""

    def test_microstructure_features_creation(self):
        """Test MicrostructureFeatures creation with default values."""
        features = MicrostructureFeatures()
        assert features.obi_depth_5 == 0.0
        assert features.obi_depth_10 == 0.0
        assert features.obi_weighted == 0.0
        assert features.micro_price == 0.0
        assert features.micro_price_depth == 5
        assert features.effective_spread == 0.0
        assert features.realized_spread == 0.0
        assert features.quoted_spread == 0.0
        assert features.volume_imbalance == 0.0
        assert features.volume_ratio == 0.0
        assert features.absorption_ratio == 0.0
        assert features.absorption_depth == 0.0
        assert features.ttf_estimate == 0.0
        assert features.queue_position == 0.0
        assert features.market_depth == 0.0
        assert features.liquidity_ratio == 0.0
        assert features.timestamp == 0.0

    def test_microstructure_features_custom_values(self):
        """Test MicrostructureFeatures with custom values."""
        features = MicrostructureFeatures(
            obi_depth_5=0.3,
            micro_price=100.05,
            quoted_spread=0.04,
            volume_ratio=0.6,
            timestamp=1000.0
        )
        assert features.obi_depth_5 == 0.3
        assert features.micro_price == 100.05
        assert features.quoted_spread == 0.04
        assert features.volume_ratio == 0.6
        assert features.timestamp == 1000.0


class TestMicrostructureEngine:
    """Test MicrostructureEngine class."""

    def test_engine_initialization(self):
        """Test MicrostructureEngine initialization."""
        engine = MicrostructureEngine()
        assert engine.max_depth == 20
        assert engine._prev_trades == []
        assert engine._trade_window_s == 30.0

    def test_engine_custom_initialization(self):
        """Test MicrostructureEngine with custom parameters."""
        engine = MicrostructureEngine(max_depth=10)
        assert engine.max_depth == 10

    def test_compute_features_basic(self):
        """Test basic feature computation."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0, 6.0],
            ask_volumes_l=[12.0, 9.0, 7.0],
            trades=[]
        )

        features = engine.compute_features(snapshot)

        assert features.timestamp == 1000.0
        assert abs(features.quoted_spread - 0.04) < 1e-10  # 100.02 - 99.98
        assert features.market_depth == 10.0 + 8.0 + 6.0 + 12.0 + 9.0 + 7.0  # 52.0
        assert features.liquidity_ratio == (10.0 + 8.0 + 6.0) / (12.0 + 9.0 + 7.0)  # 24.0 / 28.0

    def test_compute_features_with_trades(self):
        """Test feature computation with recent trades."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0],
            ask_volumes_l=[12.0, 9.0],
            trades=[]
        )
        trades = [
            Trade(995.0, 100.00, 5.0, Side.BUY),
            Trade(996.0, 100.01, 3.0, Side.SELL),
            Trade(997.0, 100.00, 4.0, Side.BUY),
        ]

        features = engine.compute_features(snapshot, trades)

        # Volume profile should be computed
        expected_buy_vol = 5.0 + 4.0  # 9.0
        expected_sell_vol = 3.0  # 3.0
        expected_total = 12.0
        expected_imbalance = 9.0 - 3.0  # 6.0
        expected_ratio = 9.0 / 12.0  # 0.75

        assert features.volume_imbalance == expected_imbalance
        assert features.volume_ratio == expected_ratio

    def test_compute_obi_depth_5(self):
        """Test OBI computation with depth 5."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0, 6.0, 4.0, 2.0],
            ask_volumes_l=[12.0, 9.0, 7.0, 5.0, 3.0],
            trades=[]
        )

        obi_5 = engine._compute_obi(snapshot, depth=5)

        bid_vol_5 = 10.0 + 8.0 + 6.0 + 4.0 + 2.0  # 30.0
        ask_vol_5 = 12.0 + 9.0 + 7.0 + 5.0 + 3.0  # 36.0
        total_vol = 30.0 + 36.0  # 66.0
        expected_obi = (30.0 - 36.0) / 66.0  # -6.0 / 66.0 = -0.0909...

        assert abs(obi_5 - expected_obi) < 1e-10

    def test_compute_obi_zero_total_volume(self):
        """Test OBI with zero total volume."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[],
            ask_volumes_l=[],
            trades=[]
        )

        obi = engine._compute_obi(snapshot, depth=5)
        assert obi == 0.0

    def test_compute_weighted_obi(self):
        """Test weighted OBI computation."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0, 6.0],
            ask_volumes_l=[12.0, 9.0, 7.0],
            trades=[]
        )

        weighted_obi = engine._compute_weighted_obi(snapshot)

        # Calculate expected weighted values
        bid_weighted = 10.0/1 + 8.0/2 + 6.0/3  # 10.0 + 4.0 + 2.0 = 16.0
        ask_weighted = 12.0/1 + 9.0/2 + 7.0/3  # 12.0 + 4.5 + 2.333... = 18.833...
        total_weighted = 16.0 + 18.833  # 34.833...
        expected = (16.0 - 18.833) / 34.833  # -2.833 / 34.833 = -0.0813...

        assert abs(weighted_obi - expected) < 1e-3

    def test_compute_micro_price(self):
        """Test micro-price computation."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0],
            ask_volumes_l=[12.0, 9.0],
            trades=[]
        )

        micro_price = engine._compute_micro_price(snapshot, depth=2)

        bid_vol = 10.0 + 8.0  # 18.0
        ask_vol = 12.0 + 9.0  # 21.0
        expected = (99.98 * 21.0 + 100.02 * 18.0) / (18.0 + 21.0)
        # = (2099.58 + 1803.6) / 39.0 = 3903.18 / 39.0 = 100.082564...

        assert abs(micro_price - expected) < 1e-6

    def test_compute_micro_price_zero_volumes(self):
        """Test micro-price with zero volumes."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[],
            ask_volumes_l=[],
            trades=[]
        )

        micro_price = engine._compute_micro_price(snapshot)
        assert micro_price == snapshot.mid  # Should return mid price

    def test_compute_volume_profile(self):
        """Test volume profile computation."""
        engine = MicrostructureEngine()
        trades = [
            Trade(995.0, 100.00, 10.0, Side.BUY),
            Trade(996.0, 100.01, 6.0, Side.SELL),
            Trade(997.0, 100.00, 8.0, Side.BUY),
        ]

        imbalance, ratio = engine._compute_volume_profile(trades)

        buy_vol = 10.0 + 8.0  # 18.0
        sell_vol = 6.0  # 6.0
        total_vol = 24.0

        assert imbalance == 18.0 - 6.0  # 12.0
        assert ratio == 18.0 / 24.0  # 0.75

    def test_compute_volume_profile_empty_trades(self):
        """Test volume profile with empty trades."""
        engine = MicrostructureEngine()
        imbalance, ratio = engine._compute_volume_profile([])
        assert imbalance == 0.0
        assert ratio == 0.5  # Default balanced ratio

    def test_compute_absorption(self):
        """Test absorption computation."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0],
            ask_volumes_l=[12.0, 9.0, 7.0, 5.0],
            trades=[]
        )

        absorption_ratio, absorption_depth = engine._compute_absorption(snapshot)

        # This is a simplified test - the actual absorption calculation is complex
        assert absorption_ratio >= 0.0
        assert absorption_depth == sum(snapshot.ask_volumes_l)  # 12+9+7+5 = 33.0

    def test_estimate_ttf(self):
        """Test TTF estimation."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0],
            ask_volumes_l=[12.0, 9.0],
            trades=[]
        )

        ttf_estimate, queue_position = engine._estimate_ttf(snapshot)

        total_depth = 10.0 + 8.0 + 12.0 + 9.0  # 39.0
        assert ttf_estimate == 1.0 / (39.0 / 10.0)  # 1.0 / 3.9 = 0.2564...
        assert queue_position == 1.0 / 39.0  # 0.02564...

    def test_estimate_ttf_zero_depth(self):
        """Test TTF estimation with zero depth."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[],
            ask_volumes_l=[],
            trades=[]
        )

        ttf_estimate, queue_position = engine._estimate_ttf(snapshot)

        assert ttf_estimate == float('inf')
        assert queue_position == 1.0

    def test_compute_realized_spread(self):
        """Test realized spread computation."""
        engine = MicrostructureEngine()

        # Simulate round-trip trades
        engine._prev_trades = [
            Trade(995.0, 100.00, 5.0, Side.BUY),
            Trade(996.0, 100.02, 5.0, Side.SELL),
        ]

        realized_spread = engine._compute_realized_spread(100.01)

        # Round-trip spread: 2 * |100.02 - 100.00| = 2 * 0.02 = 0.04
        assert abs(realized_spread - 0.04) < 1e-10

    def test_compute_realized_spread_insufficient_trades(self):
        """Test realized spread with insufficient trades."""
        engine = MicrostructureEngine()
        engine._prev_trades = [Trade(995.0, 100.00, 5.0, Side.BUY)]

        realized_spread = engine._compute_realized_spread(100.01)
        assert realized_spread == 0.0

    def test_update_trade_history(self):
        """Test trade history update."""
        engine = MicrostructureEngine()
        trades = [
            Trade(995.0, 100.00, 5.0, Side.BUY),
            Trade(996.0, 100.01, 3.0, Side.SELL),
        ]

        engine._update_trade_history(trades)

        assert len(engine._prev_trades) == 2
        assert engine._prev_trades[0].timestamp == 995.0
        assert engine._prev_trades[1].timestamp == 996.0

    def test_update_trade_history_with_cutoff(self):
        """Test trade history update with time cutoff."""
        engine = MicrostructureEngine()
        engine._trade_window_s = 5.0  # Short window for testing

        # Add old trades
        engine._prev_trades = [
            Trade(990.0, 100.00, 5.0, Side.BUY),  # Will be cut off
            Trade(995.0, 100.01, 3.0, Side.SELL), # Will remain
        ]

        # Add new trades with timestamp 1000.0
        new_trades = [Trade(1000.0, 100.02, 4.0, Side.BUY)]
        engine._update_trade_history(new_trades)

        # Should keep only recent trades (995.0 and 1000.0)
        assert len(engine._prev_trades) == 2
        assert engine._prev_trades[0].timestamp == 995.0
        assert engine._prev_trades[1].timestamp == 1000.0


class TestMicrostructureSelfTests:
    """Test the self-test functions."""

    def test_create_test_snapshot(self):
        """Test _create_test_snapshot creates valid snapshot."""
        from core.features.microstructure import _create_test_snapshot

        snapshot = _create_test_snapshot()

        assert snapshot.timestamp == 1000.0
        assert snapshot.bid_price == 99.98
        assert snapshot.ask_price == 100.02
        assert len(snapshot.bid_volumes_l) == 7
        assert len(snapshot.ask_volumes_l) == 7
        assert len(snapshot.trades) == 2
        assert snapshot.mid == (99.98 + 100.02) / 2  # 100.0
        assert snapshot.spread == 100.02 - 99.98  # 0.04

    def test_create_test_trades(self):
        """Test _create_test_trades creates valid trades."""
        from core.features.microstructure import _create_test_trades

        trades = _create_test_trades()

        assert len(trades) == 4
        assert trades[0].timestamp == 995.0
        assert trades[0].size == 10.0
        assert trades[0].side == Side.BUY
        assert trades[1].side == Side.SELL

    def test_self_test_microstructure_features(self):
        """Test _test_microstructure_features runs without errors."""
        from core.features.microstructure import _test_microstructure_features

        # This should not raise any exceptions
        _test_microstructure_features()


class TestMicrostructureEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_order_book(self):
        """Test with completely empty order book."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.001,  # Very small spread
            bid_volumes_l=[],
            ask_volumes_l=[],
            trades=[]
        )

        features = engine.compute_features(snapshot)

        assert abs(features.quoted_spread - 0.001) < 1e-10  # Small spread between bid and ask
        assert features.market_depth == 0.0
        assert features.liquidity_ratio == 1.0  # Default when ask_vol = 0
        assert features.obi_depth_5 == 0.0
        assert features.obi_weighted == 0.0
        assert abs(features.micro_price - 100.0005) < 1e-10  # Should equal mid price

    def test_single_level_order_book(self):
        """Test with single level order book."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.99,
            ask_price=100.01,
            bid_volumes_l=[10.0],
            ask_volumes_l=[12.0],
            trades=[]
        )

        features = engine.compute_features(snapshot)

        assert abs(features.quoted_spread - 0.02) < 1e-10
        assert features.market_depth == 22.0
        assert features.liquidity_ratio == 10.0 / 12.0  # 0.833...
        assert features.obi_depth_5 == (10.0 - 12.0) / (10.0 + 12.0)  # -2.0/22.0 = -0.0909...

    def test_extreme_imbalance(self):
        """Test with extreme order book imbalance."""
        engine = MicrostructureEngine()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0, 0.0, 0.0],
            ask_volumes_l=[1.0, 0.0, 0.0],
            trades=[]
        )

        features = engine.compute_features(snapshot)

        # Should be heavily biased towards buy side
        assert features.obi_depth_5 > 0.9  # Very positive
        assert features.liquidity_ratio > 10.0  # Much more bid than ask

    def test_micro_price_edge_cases(self):
        """Test micro-price edge cases."""
        engine = MicrostructureEngine()

        # Test with only bid volume
        snapshot1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0],
            ask_volumes_l=[0.0],
            trades=[]
        )
        micro_price1 = engine._compute_micro_price(snapshot1, depth=1)
        assert micro_price1 == 100.02  # Should equal ask price when only bid volume

        # Test with only ask volume
        snapshot2 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[0.0],
            ask_volumes_l=[10.0],
            trades=[]
        )
        micro_price2 = engine._compute_micro_price(snapshot2, depth=1)
        assert micro_price2 == 99.98  # Should equal bid price when only ask volume

    def test_volume_profile_edge_cases(self):
        """Test volume profile edge cases."""
        engine = MicrostructureEngine()

        # Only buy trades
        buy_only_trades = [Trade(1000.0, 100.0, 10.0, Side.BUY)]
        imbalance, ratio = engine._compute_volume_profile(buy_only_trades)
        assert imbalance == 10.0
        assert ratio == 1.0

        # Only sell trades
        sell_only_trades = [Trade(1000.0, 100.0, 10.0, Side.SELL)]
        imbalance, ratio = engine._compute_volume_profile(sell_only_trades)
        assert imbalance == -10.0
        assert ratio == 0.0

    def test_absorption_edge_cases(self):
        """Test absorption computation edge cases."""
        engine = MicrostructureEngine()

        # Empty ask side
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0],
            ask_volumes_l=[],
            trades=[]
        )

        absorption_ratio, absorption_depth = engine._compute_absorption(snapshot)
        assert absorption_ratio == 0.0  # No ask depth
        assert absorption_depth == 0.0

    def test_realized_spread_edge_cases(self):
        """Test realized spread edge cases."""
        engine = MicrostructureEngine()

        # Same side trades (no round trip)
        same_side_trades = [
            Trade(995.0, 100.00, 5.0, Side.BUY),
            Trade(996.0, 100.01, 5.0, Side.BUY),
        ]
        engine._prev_trades = same_side_trades
        realized_spread = engine._compute_realized_spread(100.01)
        assert realized_spread == 0.0

        # Multiple round trips
        round_trip_trades = [
            Trade(990.0, 100.00, 5.0, Side.BUY),
            Trade(991.0, 100.02, 5.0, Side.SELL),
            Trade(992.0, 100.01, 3.0, Side.BUY),
            Trade(993.0, 100.03, 3.0, Side.SELL),
        ]
        engine._prev_trades = round_trip_trades
        realized_spread = engine._compute_realized_spread(100.02)

        # Should average the two round-trip spreads
        spread1 = 2 * abs(100.02 - 100.00)  # 0.04
        spread2 = 2 * abs(100.03 - 100.01)  # 0.04
        expected_avg = (0.04 + 0.04) / 2  # 0.04

        assert abs(realized_spread - expected_avg) < 1e-10


# =============================
# Absorption Tests
# =============================

class TestEMA:
    """Test _EMA exponential moving average functionality."""

    def test_ema_initialization(self):
        """Test EMA initialization."""
        from core.features.absorption import _EMA

        ema = _EMA(half_life_s=2.0)
        assert ema.half_life_s == 2.0
        assert ema.value == 0.0
        assert ema._last_ts is None

    def test_ema_first_update(self):
        """Test first EMA update sets value directly."""
        from core.features.absorption import _EMA

        ema = _EMA(half_life_s=2.0)
        result = ema.update(10.0, 1000.0)

        assert result == 10.0
        assert ema.value == 10.0
        assert ema._last_ts == 1000.0

    def test_ema_subsequent_updates(self):
        """Test EMA smoothing over multiple updates."""
        from core.features.absorption import _EMA
        import math

        ema = _EMA(half_life_s=1.0)  # Fast decay for testing

        # First update
        ema.update(10.0, 1000.0)

        # Second update after 1 second
        result = ema.update(20.0, 1001.0)

        # Expected: w * old_value + (1-w) * new_value
        # w = exp(-ln(2)/half_life * dt) = exp(-ln(2)/1 * 1) = exp(-ln(2)) = 0.5
        # result = 0.5 * 10.0 + 0.5 * 20.0 = 15.0
        assert abs(result - 15.0) < 1e-10
        assert abs(ema.value - 15.0) < 1e-10

    def test_ema_zero_half_life(self):
        """Test EMA with zero half-life (should not crash)."""
        from core.features.absorption import _EMA

        ema = _EMA(half_life_s=0.0)
        result = ema.update(10.0, 1000.0)
        assert result == 10.0

    def test_ema_negative_dt(self):
        """Test EMA handles negative time differences."""
        from core.features.absorption import _EMA

        ema = _EMA(half_life_s=2.0)
        ema.update(10.0, 1000.0)

        # Time going backwards should be treated as zero dt
        result = ema.update(20.0, 999.0)
        assert result == 10.0  # Should keep previous value due to zero dt


class TestSumTrades:
    """Test _sum_trades helper function."""

    def test_sum_trades_empty(self):
        """Test summing empty trades list."""
        from core.features.absorption import _sum_trades

        trades = []
        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 0.0

    def test_sum_trades_single_side(self):
        """Test summing trades of single side."""
        from core.features.absorption import _sum_trades

        trades = [
            Trade(1001.0, 100.0, 10.0, Side.BUY),
            Trade(1002.0, 100.0, 5.0, Side.BUY),
            Trade(1003.0, 100.0, 8.0, Side.SELL),
        ]

        buy_sum = _sum_trades(trades, Side.BUY, 1000.0)
        sell_sum = _sum_trades(trades, Side.SELL, 1000.0)

        assert buy_sum == 15.0  # 10 + 5
        assert sell_sum == 8.0

    def test_sum_trades_time_filter(self):
        """Test that trades before ts_from are excluded."""
        from core.features.absorption import _sum_trades

        trades = [
            Trade(999.0, 100.0, 10.0, Side.BUY),  # Before ts_from
            Trade(1001.0, 100.0, 5.0, Side.BUY),  # After ts_from
            Trade(1002.0, 100.0, 8.0, Side.SELL), # After ts_from
        ]

        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 5.0  # Only the trade after ts_from

    def test_sum_trades_string_side(self):
        """Test summing trades with string side values."""
        from core.features.absorption import _sum_trades

        trades = [
            Trade(1001.0, 100.0, 10.0, "BUY"),  # String side
            Trade(1002.0, 100.0, 5.0, Side.BUY), # Enum side
        ]

        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 15.0


class TestAbsorptionStream:
    """Test AbsorptionStream functionality."""

    def test_absorption_stream_initialization(self):
        """Test AbsorptionStream initialization."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream(window_s=5.0, ema_half_life_s=2.0)

        assert stream.window_s == 5.0
        assert stream.hl == 2.0
        assert stream.st.last_ts is None
        assert stream.st.bid_p is None
        assert stream.st.ask_p is None
        assert stream.st.bid_q1 == 0.0
        assert stream.st.ask_q1 == 0.0

    def test_absorption_stream_first_update(self):
        """Test first update initializes state and returns features."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()
        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0, 80.0],
            ask_volumes_l=[120.0, 90.0],
            trades=[]
        )

        features = stream.update(snapshot)

        # Check state was initialized
        assert stream.st.last_ts == 1000.0
        assert stream.st.bid_p == 99.98
        assert stream.st.ask_p == 100.02
        assert stream.st.bid_q1 == 100.0
        assert stream.st.ask_q1 == 120.0

        # Check features are initialized to zero/defaults
        assert features["rate_sell_mo_hit_bid"] == 0.0
        assert features["rate_buy_mo_hit_ask"] == 0.0
        assert features["absorption_frac_bid"] == 0.0
        assert features["absorption_frac_ask"] == 0.0

    def test_absorption_stream_basic_update(self):
        """Test basic absorption stream update with trades."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream(ema_half_life_s=1.0)  # Fast decay for testing

        # First snapshot
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Second snapshot with trades and queue changes
        snap2 = MarketSnapshot(
            timestamp=1001.0,  # 1 second later
            bid_price=99.98,   # Same price
            ask_price=100.02,  # Same price
            bid_volumes_l=[80.0],   # Decreased by 20 (some removal)
            ask_volumes_l=[110.0],  # Decreased by 10 (some removal)
            trades=[
                Trade(1000.5, 99.98, 15.0, Side.SELL),  # Hit bid
                Trade(1000.7, 100.02, 5.0, Side.BUY),   # Hit ask
            ]
        )

        features = stream.update(snap2)

        # Check rates are calculated
        assert features["rate_sell_mo_hit_bid"] > 0
        assert features["rate_buy_mo_hit_ask"] > 0
        assert features["rate_cancel_bid"] >= 0
        assert features["rate_cancel_ask"] >= 0

        # Check absorption fractions
        assert 0.0 <= features["absorption_frac_bid"] <= 1.0
        assert 0.0 <= features["absorption_frac_ask"] <= 1.0

    def test_absorption_stream_price_step_up(self):
        """Test absorption stream with bid price stepping up."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initial snapshot
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Price steps up (new liquidity)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=100.00,  # Stepped up
            ask_price=100.02,
            bid_volumes_l=[150.0],  # New size at new price
            ask_volumes_l=[120.0],
            trades=[]
        )

        features = stream.update(snap2)

        # Should have replenishment at bid
        assert features["rate_replenish_bid"] > 0

    def test_absorption_stream_price_step_up_bid(self):
        """Test absorption stream with bid price stepping up."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Bid price steps up (new liquidity)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=100.00,  # Stepped up
            ask_price=100.02,
            bid_volumes_l=[80.0],   # New size at new price
            ask_volumes_l=[120.0],
            trades=[]
        )

        features = stream.update(snap2)

        # Should have replenishment at bid (new liquidity at new price)
        assert features["rate_replenish_bid"] > 0

    def test_absorption_stream_price_step_down_ask(self):
        """Test absorption stream with ask price stepping down."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Ask price steps down (new liquidity)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=99.98,
            ask_price=100.00,  # Stepped down
            bid_volumes_l=[100.0],
            ask_volumes_l=[90.0],   # New size at new price
            trades=[]
        )

        features = stream.update(snap2)

        # Should have replenishment at ask (new liquidity at new price)
        assert features["rate_replenish_ask"] > 0

    def test_absorption_stream_price_step_down_bid_depletion(self):
        """Test absorption stream with bid price stepping down (depletion)."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.00,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Bid price steps down (depletion event - no replenishment)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=99.98,  # Stepped down
            ask_price=100.02,
            bid_volumes_l=[80.0],   # New size at new price
            ask_volumes_l=[120.0],
            trades=[]
        )

        features = stream.update(snap2)

        # Should NOT have replenishment at bid (depletion event)
        # The replenishment should be 0 because it's a depletion
        assert features["rate_replenish_bid"] == 0.0

    def test_absorption_stream_price_step_up_ask_depletion(self):
        """Test absorption stream with ask price stepping up (depletion)."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.00,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Ask price steps up (depletion event - no replenishment)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=99.98,
            ask_price=100.02,  # Stepped up
            bid_volumes_l=[100.0],
            ask_volumes_l=[90.0],   # New size at new price
            trades=[]
        )

        features = stream.update(snap2)

        # Should NOT have replenishment at ask (depletion event)
        assert features["rate_replenish_ask"] == 0.0


class TestAbsorptionStreamQueueAhead:
    """Test queue-ahead estimation functionality."""

    def test_estimate_queue_ahead_buy_side(self):
        """Test queue-ahead estimation for buy side."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize with some state
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap)

        # Test queue-ahead for BUY (resting at ask)
        qa = stream.estimate_queue_ahead(Side.BUY, horizon_s=0.0)
        assert qa == 120.0  # Current ask queue size

        # Test with horizon
        qa_horizon = stream.estimate_queue_ahead(Side.BUY, horizon_s=1.0)
        assert qa_horizon >= 120.0  # Should include replenishment

    def test_estimate_queue_ahead_sell_side(self):
        """Test queue-ahead estimation for sell side."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize with some state
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap)

        # Test queue-ahead for SELL (resting at bid)
        qa = stream.estimate_queue_ahead(Side.SELL, horizon_s=0.0)
        assert qa == 100.0  # Current bid queue size

    def test_estimate_queue_ahead_string_side(self):
        """Test queue-ahead with string side values."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize with some state
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap)

        # Test with string side
        qa = stream.estimate_queue_ahead("BUY", horizon_s=0.0)
        assert qa == 120.0

    def test_estimate_queue_ahead_uninitialized(self):
        """Test queue-ahead before any updates."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Should handle uninitialized state gracefully
        qa = stream.estimate_queue_ahead(Side.BUY, horizon_s=0.0)
        assert qa >= 0  # Should not crash


class TestAbsorptionStreamEdgeCases:
    """Test edge cases for AbsorptionStream."""

    def test_empty_volumes_lists(self):
        """Test with empty bid/ask volumes lists."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[],  # Empty
            ask_volumes_l=[],  # Empty
            trades=[]
        )

        features = stream.update(snapshot)

        # Should handle empty volumes gracefully
        assert features["ttd_bid_s"] >= 0
        assert features["ttd_ask_s"] >= 0

    def test_zero_dt_handling(self):
        """Test handling of zero time difference."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # First snapshot
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Same timestamp (zero dt)
        snap2 = MarketSnapshot(
            timestamp=1000.0,  # Same timestamp
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[90.0],
            ask_volumes_l=[110.0],
            trades=[]
        )

        features = stream.update(snap2)

        # Should handle zero dt (use minimum dt of 1e-6)
        assert features["rate_cancel_bid"] >= 0

    def test_extreme_queue_changes(self):
        """Test with extreme queue size changes."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Extreme reduction
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[1.0],    # Almost depleted
            ask_volumes_l=[1.0],    # Almost depleted
            trades=[]
        )

        features = stream.update(snap2)

        # Should handle extreme changes
        assert features["rate_cancel_bid"] >= 0
        assert features["rate_cancel_ask"] >= 0

    def test_no_trades_with_queue_change(self):
        """Test queue changes without trades (pure cancels/replenish)."""
        from core.features.absorption import AbsorptionStream

        stream = AbsorptionStream()

        # Initialize
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[120.0],
            trades=[]
        )
        stream.update(snap1)

        # Queue reduction without trades (cancels)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[80.0],   # Reduced by 20
            ask_volumes_l=[100.0],  # Reduced by 20
            trades=[]  # No trades
        )

        features = stream.update(snap2)

        # Should attribute all removal to cancels
        assert features["rate_cancel_bid"] > 0
        assert features["rate_cancel_ask"] > 0
        assert features["rate_sell_mo_hit_bid"] == 0.0
        assert features["rate_buy_mo_hit_ask"] == 0.0


# =============================
# Scaling Module Tests
# =============================


class TestClip:
    """Test _clip utility function."""

    def test_clip_no_bounds(self):
        """Test clipping with no bounds."""
        assert _clip(5.0, None, None) == 5.0
        assert _clip(-3.0, None, None) == -3.0
        assert _clip(0.0, None, None) == 0.0

    def test_clip_lower_bound(self):
        """Test clipping with lower bound only."""
        assert _clip(5.0, 0.0, None) == 5.0
        assert _clip(-3.0, 0.0, None) == 0.0
        assert _clip(0.0, 0.0, None) == 0.0

    def test_clip_upper_bound(self):
        """Test clipping with upper bound only."""
        assert _clip(5.0, None, 10.0) == 5.0
        assert _clip(15.0, None, 10.0) == 10.0
        assert _clip(10.0, None, 10.0) == 10.0

    def test_clip_both_bounds(self):
        """Test clipping with both bounds."""
        assert _clip(5.0, 0.0, 10.0) == 5.0
        assert _clip(-3.0, 0.0, 10.0) == 0.0
        assert _clip(15.0, 0.0, 10.0) == 10.0
        assert _clip(0.0, 0.0, 10.0) == 0.0
        assert _clip(10.0, 0.0, 10.0) == 10.0


class TestWelford:
    """Test Welford online statistics."""

    def test_welford_empty(self):
        """Test Welford with no data."""
        w = Welford()
        assert w.n == 0
        assert w.mean == 0.0
        assert w.var == 0.0
        assert w.std == 0.0

    def test_welford_single_value(self):
        """Test Welford with single value."""
        w = Welford()
        w.update(5.0)
        assert w.n == 1
        assert w.mean == 5.0
        assert w.var == 0.0
        assert w.std == 0.0

    def test_welford_two_values(self):
        """Test Welford with two values."""
        w = Welford()
        w.update(2.0)
        w.update(4.0)
        assert w.n == 2
        assert w.mean == 3.0
        assert w.var == 2.0
        assert w.std == math.sqrt(2.0)

    def test_welford_multiple_values(self):
        """Test Welford with multiple values."""
        w = Welford()
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            w.update(v)
        assert w.n == 5
        assert abs(w.mean - 3.0) < 1e-12
        expected_var = 2.5  # population variance
        assert abs(w.var - expected_var) < 1e-12
        assert abs(w.std - math.sqrt(expected_var)) < 1e-12

    def test_welford_constant_values(self):
        """Test Welford with constant values."""
        w = Welford()
        for _ in range(10):
            w.update(7.0)
        assert w.n == 10
        assert w.mean == 7.0
        assert w.var == 0.0
        assert w.std == 0.0

    def test_welford_negative_values(self):
        """Test Welford with negative values."""
        w = Welford()
        values = [-5.0, -3.0, -1.0, 1.0, 3.0, 5.0]
        for v in values:
            w.update(v)
        assert w.n == 6
        assert abs(w.mean - 0.0) < 1e-12
        expected_var = 14.0  # sample variance
        assert abs(w.var - expected_var) < 1e-12


class TestP2Quantile:
    """Test P² quantile estimator."""

    def test_p2_quantile_invalid_q(self):
        """Test P² quantile with invalid q values."""
        pq = P2Quantile(0.5)
        # Valid q should work
        pq.update(1.0)
        
        # Invalid q should raise error on update
        pq_invalid_low = P2Quantile(0.0)
        with pytest.raises(ValueError, match="quantile q must be in \\(0,1\\)"):
            pq_invalid_low.update(1.0)
            
        pq_invalid_high = P2Quantile(1.0)
        with pytest.raises(ValueError, match="quantile q must be in \\(0,1\\)"):
            pq_invalid_high.update(1.0)

    def test_p2_quantile_median_few_values(self):
        """Test P² median with fewer than 5 values."""
        pq = P2Quantile(0.5)
        assert pq.value() == 0.0  # No values

        pq.update(3.0)
        assert pq.value() == 3.0  # One value

        pq.update(1.0)
        assert pq.value() == 1.0  # Two values, returns first (sorted)

        pq.update(5.0)
        assert pq.value() == 3.0  # Three values, returns middle (sorted: 1,3,5)

        pq.update(2.0)
        # Four values: sorted [1,2,3,5], median at index 1.5 -> interpolated between 2 and 3
        result = pq.value()
        assert 2.0 <= result <= 3.0

    def test_p2_quantile_median_many_values(self):
        """Test P² median with many values."""
        pq = P2Quantile(0.5)
        values = [1.0, 3.0, 5.0, 7.0, 9.0, 2.0, 4.0, 6.0, 8.0, 10.0]
        for v in values:
            pq.update(v)

        # Should be close to actual median (5.5), but P² is approximate
        result = pq.value()
        assert 4.0 <= result <= 7.0  # Wider range for approximation

    def test_p2_quantile_quartiles(self):
        """Test P² with different quantiles."""
        pq25 = P2Quantile(0.25)
        pq75 = P2Quantile(0.75)

        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        for v in values:
            pq25.update(v)
            pq75.update(v)

        # Q1 should be around 3.25, Q3 around 7.75
        q1 = pq25.value()
        q3 = pq75.value()
        assert 2.5 <= q1 <= 4.0
        assert 7.0 <= q3 <= 8.5
        assert q1 < q3

    def test_p2_quantile_extreme_values(self):
        """Test P² with extreme values."""
        pq = P2Quantile(0.5)
        values = [100.0, 1.0, 1000.0, 0.1, 50.0]
        for v in values:
            pq.update(v)

        result = pq.value()
        assert 0.1 <= result <= 1000.0


class TestRobustMedianMAD:
    """Test RobustMedianMAD estimator."""

    def test_robust_median_mad_empty(self):
        """Test RobustMedianMAD with no data."""
        rmm = RobustMedianMAD()
        assert rmm.median == 0.0
        assert rmm.mad == 0.0

    def test_robust_median_mad_single_value(self):
        """Test RobustMedianMAD with single value."""
        rmm = RobustMedianMAD()
        rmm.update(5.0)
        assert rmm.median == 5.0
        # MAD for single value is not well-defined, but implementation uses |x - 0|
        # which gives |5.0 - 0.0| / c = 5.0 / 0.6745 ≈ 7.41
        assert abs(rmm.mad - 5.0 / 0.6744897501960817) < 1e-6

    def test_robust_median_mad_multiple_values(self):
        """Test RobustMedianMAD with multiple values."""
        rmm = RobustMedianMAD()
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            rmm.update(v)

        # Median should be around 3.0
        assert 2.5 <= rmm.median <= 3.5
        # MAD should be positive
        assert rmm.mad > 0

    def test_robust_median_mad_outliers(self):
        """Test RobustMedianMAD robustness to outliers."""
        rmm = RobustMedianMAD()
        # Normal values
        for i in range(10):
            rmm.update(float(i))

        median_before = rmm.median
        mad_before = rmm.mad

        # Add extreme outliers
        rmm.update(1000.0)
        rmm.update(-1000.0)

        # Should be relatively stable
        assert abs(rmm.median - median_before) < 100.0
        assert abs(rmm.mad - mad_before) < 100.0


class TestZScoreScaler:
    """Test ZScoreScaler."""

    def test_zscore_scaler_empty(self):
        """Test ZScoreScaler with no data."""
        zs = ZScoreScaler()
        result = zs.transform(5.0)
        assert result == 0.0  # No variance yet

    def test_zscore_scaler_single_value(self):
        """Test ZScoreScaler with single value."""
        zs = ZScoreScaler()
        zs.update(5.0)
        result = zs.transform(5.0)
        assert result == 0.0  # No variance

    def test_zscore_scaler_multiple_values(self):
        """Test ZScoreScaler with multiple values."""
        zs = ZScoreScaler()
        values = [10.0, 12.0, 11.0, 9.0, 13.0]
        for v in values:
            zs.update(v)

        # Test transform
        z = zs.transform(12.0)
        assert -3.0 <= z <= 3.0  # Should be within reasonable range

        # Test inverse
        x_back = zs.inverse(z)
        assert abs(x_back - 12.0) < 1e-6

    def test_zscore_scaler_clipping(self):
        """Test ZScoreScaler with clipping."""
        zs = ZScoreScaler(clip_lo=-2.0, clip_hi=2.0)
        values = [0.0, 10.0, -10.0]  # Extreme values to trigger clipping
        for v in values:
            zs.update(v)

        # Extreme z-scores should be clipped
        z_low = zs.transform(-100.0)
        z_high = zs.transform(100.0)
        assert z_low >= -2.0
        assert z_high <= 2.0

    def test_zscore_scaler_no_clipping(self):
        """Test ZScoreScaler without clipping."""
        zs = ZScoreScaler(clip_lo=None, clip_hi=None)
        values = [0.0, 1.0, 2.0]
        for v in values:
            zs.update(v)

        # Should not clip
        z = zs.transform(10.0)
        assert z > 2.0  # Should be able to go beyond typical ranges

    def test_zscore_scaler_inverse_consistency(self):
        """Test ZScoreScaler inverse consistency."""
        zs = ZScoreScaler()
        test_values = [-5.0, -1.0, 0.0, 1.0, 5.0]

        for x in test_values:
            zs.update(x)
            z = zs.transform(x)
            x_back = zs.inverse(z)
            assert abs(x_back - x) < 1e-6


class TestRobustScaler:
    """Test RobustScaler."""

    def test_robust_scaler_empty(self):
        """Test RobustScaler with no data."""
        rs = RobustScaler()
        result = rs.transform(5.0)
        assert result == 0.0

    def test_robust_scaler_single_value(self):
        """Test RobustScaler with single value."""
        rs = RobustScaler()
        rs.update(5.0)
        result = rs.transform(5.0)
        assert result == 0.0

    def test_robust_scaler_multiple_values(self):
        """Test RobustScaler with multiple values."""
        rs = RobustScaler()
        values = [10.0, 12.0, 11.0, 9.0, 13.0]
        for v in values:
            rs.update(v)

        # Test transform
        z = rs.transform(12.0)
        assert -3.0 <= z <= 3.0

        # Test inverse
        x_back = rs.inverse(z)
        assert abs(x_back - 12.0) < 1e-6

    def test_robust_scaler_outlier_resistance(self):
        """Test RobustScaler resistance to outliers."""
        rs = RobustScaler()
        # Normal values
        for i in range(10):
            rs.update(float(i))

        z_before = rs.transform(5.0)

        # Add extreme outliers
        rs.update(1000.0)
        rs.update(-1000.0)

        z_after = rs.transform(5.0)

        # Should be relatively stable
        assert abs(z_after - z_before) < 1.0

    def test_robust_scaler_clipping(self):
        """Test RobustScaler with clipping."""
        rs = RobustScaler(clip_lo=-2.0, clip_hi=2.0)
        values = [0.0, 1.0, 2.0, 100.0, -100.0]
        for v in values:
            rs.update(v)

        # Extreme values should be clipped
        z_low = rs.transform(-1000.0)
        z_high = rs.transform(1000.0)
        assert z_low >= -2.0
        assert z_high <= 2.0


class TestHysteresisMinMax:
    """Test HysteresisMinMax scaler."""

    def test_hysteresis_minmax_empty(self):
        """Test HysteresisMinMax with no data."""
        hmm = HysteresisMinMax()
        result = hmm.transform(5.0)
        assert result == 0.5  # Neutral value

    def test_hysteresis_minmax_single_value(self):
        """Test HysteresisMinMax with single value."""
        hmm = HysteresisMinMax()
        result = hmm.update(5.0)
        assert result == 0.5  # Neutral value
        assert hmm.lo == 5.0
        assert hmm.hi == 5.0

    def test_hysteresis_minmax_multiple_values(self):
        """Test HysteresisMinMax with multiple values."""
        hmm = HysteresisMinMax(alpha_expand=0.5, alpha_shrink=0.9)
        values = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]

        for v in values:
            hmm.update(v)

        # Should have expanded bounds
        assert hmm.lo < hmm.hi
        assert hmm.lo <= 0.0
        # With alpha_expand=0.5, bounds expand but don't reach exactly the max value
        assert hmm.hi > 3.0  # Should be greater than some intermediate value

        # Transform should be in [0, 1]
        t = hmm.transform(2.5)
        assert 0.0 <= t <= 1.0

        # Inverse should work
        x_back = hmm.inverse(t)
        assert abs(x_back - 2.5) < 1e-6

    def test_hysteresis_minmax_expansion(self):
        """Test HysteresisMinMax expansion behavior."""
        hmm = HysteresisMinMax(alpha_expand=0.1, alpha_shrink=0.99)

        # Initialize
        hmm.update(5.0)

        # Expand up
        hmm.update(10.0)
        assert hmm.hi > 5.0

        # Expand down
        hmm.update(0.0)
        assert hmm.lo < 5.0

        # Shrink toward middle
        hmm.update(5.0)
        old_range = hmm.hi - hmm.lo
        hmm.update(5.0)
        new_range = hmm.hi - hmm.lo
        assert new_range <= old_range  # Should shrink

    def test_hysteresis_minmax_bounds(self):
        """Test HysteresisMinMax bounds handling."""
        hmm = HysteresisMinMax()

        # Test with equal bounds
        hmm.lo = 5.0
        hmm.hi = 5.0
        result = hmm.transform(5.0)
        assert result == 0.5

        # Test inverse with equal bounds
        # When lo == hi, inverse returns 0.0 by design (degenerate case)
        result = hmm.inverse(0.5)
        assert result == 0.0  # This is the current implementation behavior

    def test_hysteresis_minmax_inverse_clipping(self):
        """Test HysteresisMinMax inverse with clipping."""
        hmm = HysteresisMinMax()
        hmm.lo = 0.0
        hmm.hi = 10.0

        # Test clipping in inverse
        x_low = hmm.inverse(-1.0)  # Should clip to 0
        x_high = hmm.inverse(2.0)  # Should clip to 1
        assert x_low == 0.0
        assert x_high == 10.0


class TestDictFeatureScaler:
    """Test DictFeatureScaler."""

    def test_dict_feature_scaler_zscore_mode(self):
        """Test DictFeatureScaler with zscore mode."""
        dfs = DictFeatureScaler(mode="zscore", clip=(-3.0, 3.0))

        # Update different features
        dfs.update("obi", 1.0)
        dfs.update("tfi", 10.0)
        dfs.update("obi", 2.0)
        dfs.update("tfi", 20.0)

        # Transform values
        z1 = dfs.transform("obi", 1.5)
        z2 = dfs.transform("tfi", 15.0)

        assert isinstance(z1, float)
        assert isinstance(z2, float)
        assert -3.0 <= z1 <= 3.0
        assert -3.0 <= z2 <= 3.0

    def test_dict_feature_scaler_robust_mode(self):
        """Test DictFeatureScaler with robust mode."""
        dfs = DictFeatureScaler(mode="robust", clip=(-5.0, 5.0))

        # Update features
        for i in range(10):
            dfs.update("feature1", float(i))
            dfs.update("feature2", float(i * 2))

        # Transform
        z1 = dfs.transform("feature1", 5.0)
        z2 = dfs.transform("feature2", 10.0)

        assert -5.0 <= z1 <= 5.0
        assert -5.0 <= z2 <= 5.0

    def test_dict_feature_scaler_minmax_mode(self):
        """Test DictFeatureScaler with minmax mode."""
        dfs = DictFeatureScaler(mode="minmax")

        # Update features
        dfs.update("price", 100.0)
        dfs.update("price", 110.0)
        dfs.update("price", 90.0)

        # Transform should be in [0, 1]
        z = dfs.transform("price", 105.0)
        assert 0.0 <= z <= 1.0

    def test_dict_feature_scaler_invalid_mode(self):
        """Test DictFeatureScaler with invalid mode."""
        with pytest.raises(ValueError, match="Unknown mode"):
            dfs = DictFeatureScaler(mode="invalid")
            dfs.update("test", 1.0)

    def test_dict_feature_scaler_update_batch(self):
        """Test DictFeatureScaler update_batch method."""
        dfs = DictFeatureScaler(mode="zscore")

        batch = {"a": 1.0, "b": 2.0, "c": 3.0}
        results = dfs.update_batch(batch)

        assert len(results) == 3
        assert all(isinstance(v, float) for v in results.values())

        # Second batch should use existing scalers
        batch2 = {"a": 2.0, "b": 3.0}
        results2 = dfs.update_batch(batch2)

        assert len(results2) == 2
        assert "a" in results2
        assert "b" in results2

    def test_dict_feature_scaler_new_feature_transform(self):
        """Test DictFeatureScaler transform with new feature."""
        dfs = DictFeatureScaler(mode="zscore")

        # Transform without prior updates should create new scaler
        z = dfs.transform("new_feature", 5.0)
        assert isinstance(z, float)

        # Subsequent transforms should use same scaler
        z2 = dfs.transform("new_feature", 6.0)
        assert isinstance(z2, float)


class TestScalingIntegration:
    """Integration tests for scaling module."""

    def test_scaling_pipeline_consistency(self):
        """Test that scaling pipeline maintains consistency."""
        # Create scalers
        zscore = ZScoreScaler()
        robust = RobustScaler()
        minmax = HysteresisMinMax()

        # Same data for all
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0]

        # Update all scalers
        for v in values:
            zscore.update(v)
            robust.update(v)
            minmax.update(v)

        # Test point
        test_val = 3.5

        # All should produce valid outputs
        z_zscore = zscore.transform(test_val)
        z_robust = robust.transform(test_val)
        z_minmax = minmax.transform(test_val)

        assert isinstance(z_zscore, float)
        assert isinstance(z_robust, float)
        assert isinstance(z_minmax, float)

        # MinMax should be in [0, 1]
        assert 0.0 <= z_minmax <= 1.0

        # Test inverses
        x_zscore = zscore.inverse(z_zscore)
        x_robust = robust.inverse(z_robust)
        x_minmax = minmax.inverse(z_minmax)

        assert abs(x_zscore - test_val) < 1e-6
        assert abs(x_robust - test_val) < 1e-6
        assert abs(x_minmax - test_val) < 1e-6

    def test_scaling_with_extreme_values(self):
        """Test scaling behavior with extreme values."""
        scalers = [
            ZScoreScaler(clip_lo=-10.0, clip_hi=10.0),
            RobustScaler(clip_lo=-10.0, clip_hi=10.0),
            HysteresisMinMax()
        ]

        # Mix of normal and extreme values
        values = [0.0, 1.0, -1.0, 1000.0, -1000.0, 0.5, -0.5]

        for scaler in scalers:
            for v in values:
                scaler.update(v)

            # All should handle extreme transform values
            z_extreme_low = scaler.transform(-10000.0)
            z_extreme_high = scaler.transform(10000.0)

            assert isinstance(z_extreme_low, float)
            assert isinstance(z_extreme_high, float)

            # Should not be NaN or infinite
            assert not math.isnan(z_extreme_low)
            assert not math.isnan(z_extreme_high)
            assert not math.isinf(z_extreme_low)
            assert not math.isinf(z_extreme_high)

    def test_scaling_memory_efficiency(self):
        """Test that scalers don't accumulate excessive memory."""
        dfs = DictFeatureScaler(mode="robust")

        # Add many features
        for i in range(100):
            dfs.update(f"feature_{i}", float(i))

        # Should have 100 scalers
        assert len(dfs._scalers) == 100

        # Transform existing features (should reuse scalers)
        for i in range(100):
            z = dfs.transform(f"feature_{i}", float(i + 0.5))
            assert isinstance(z, float)

        # Still should have 100 scalers
        assert len(dfs._scalers) == 100
