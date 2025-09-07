"""
Comprehensive test suite for core/features/tfi.py
Tests all functions, streaming functionality, and edge cases.
"""
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
import time
import math

from core.features.tfi import (
    tfi_increment,
    vpin_like,
    vpin_volume_buckets,
    TFIStream,
    _Rolling,
    _WinTrade
)
from core.types import Trade, Side


class TestTFIPureFunctions:
    """Test pure TFI calculation functions."""

    def test_tfi_increment_buy(self):
        """Test TFI increment for BUY trades."""
        trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=10.0,
            side=Side.BUY
        )
        increment = tfi_increment(trade)
        assert increment == 10.0

    def test_tfi_increment_sell(self):
        """Test TFI increment for SELL trades."""
        trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=15.0,
            side=Side.SELL
        )
        increment = tfi_increment(trade)
        assert increment == -15.0

    def test_tfi_increment_string_side(self):
        """Test TFI increment with string side values."""
        buy_trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=5.0,
            side="BUY"
        )
        sell_trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=8.0,
            side="SELL"
        )

        assert tfi_increment(buy_trade) == 5.0
        assert tfi_increment(sell_trade) == -8.0

    def test_vpin_like_basic(self):
        """Test basic VPIN-like calculation."""
        buy_vol = 100.0
        sell_vol = 80.0

        vpin = vpin_like(buy_vol, sell_vol)
        expected = abs(100.0 - 80.0) / (100.0 + 80.0)  # 20/180 = 1/9 ≈ 0.111
        assert abs(vpin - expected) < 1e-12

    def test_vpin_like_zero_denominator(self):
        """Test VPIN-like with zero total volume."""
        vpin = vpin_like(0.0, 0.0)
        assert vpin == 0.0

    def test_vpin_like_equal_volumes(self):
        """Test VPIN-like with equal buy/sell volumes."""
        vpin = vpin_like(50.0, 50.0)
        assert vpin == 0.0

    def test_vpin_volume_buckets_basic(self):
        """Test basic volume bucket VPIN calculation."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=60.0, side=Side.BUY),   # Bucket 1: B=60, S=0
            Trade(timestamp=2.0, price=100.0, size=40.0, side=Side.SELL),  # Bucket 1: B=60, S=40 → imbalance=20/100=0.2
            Trade(timestamp=3.0, price=100.0, size=80.0, side=Side.BUY),   # Bucket 2: B=80, S=0 → imbalance=80/100=0.8
        ]

        vpin = vpin_volume_buckets(trades, bucket_volume=100.0, max_buckets=50)
        expected = 0.2  # Only first bucket is complete: |60-40|/100 = 0.2, second bucket partial and ignored
        assert abs(vpin - expected) < 1e-12

    def test_vpin_volume_buckets_empty(self):
        """Test VPIN with empty trade list."""
        vpin = vpin_volume_buckets([], bucket_volume=100.0)
        assert vpin == 0.0

    def test_vpin_volume_buckets_single_bucket(self):
        """Test VPIN with single complete bucket."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=50.0, side=Side.BUY),
            Trade(timestamp=2.0, price=100.0, size=50.0, side=Side.SELL),
        ]

        vpin = vpin_volume_buckets(trades, bucket_volume=100.0)
        expected = abs(50.0 - 50.0) / 100.0  # 0/100 = 0.0
        assert abs(vpin - expected) < 1e-12

    def test_vpin_volume_buckets_partial_bucket_ignored(self):
        """Test that partial buckets are ignored."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=60.0, side=Side.BUY),   # Partial bucket: B=60, S=0, remain=40
            Trade(timestamp=2.0, price=100.0, size=30.0, side=Side.SELL),  # Partial bucket: B=60, S=30, remain=10
        ]

        vpin = vpin_volume_buckets(trades, bucket_volume=100.0)
        expected = 0.0  # No bucket reaches full volume, so all partial buckets ignored
        assert abs(vpin - expected) < 1e-12

    def test_vpin_volume_buckets_large_trade_split(self):
        """Test that large trades are properly split across buckets."""
        trades = [
            Trade(timestamp=1.0, price=100.0, size=250.0, side=Side.BUY),  # Spans 3 buckets
        ]

        vpin = vpin_volume_buckets(trades, bucket_volume=100.0)
        # First bucket: B=100, S=0 → imbalance=100/100=1.0
        # Second bucket: B=100, S=0 → imbalance=100/100=1.0
        # Third bucket: B=50, S=0 → imbalance=50/100=0.5 (partial, ignored)
        expected = (1.0 + 1.0) / 2  # Average of 2 complete buckets
        assert abs(vpin - expected) < 1e-12

    def test_vpin_volume_buckets_max_buckets_limit(self):
        """Test max_buckets parameter limits the number of buckets used."""
        # Create many small trades to generate many buckets
        trades = []
        for i in range(20):  # 20 trades of size 10 = 200 volume = 2 buckets
            side = Side.BUY if i % 2 == 0 else Side.SELL
            trades.append(Trade(timestamp=float(i), price=100.0, size=10.0, side=side))

        vpin = vpin_volume_buckets(trades, bucket_volume=100.0, max_buckets=1)
        # Should only use the last 1 bucket
        assert 0.0 <= vpin <= 1.0


class TestTFIStream:
    """Test TFIStream streaming functionality."""

    def test_initialization(self):
        """Test TFIStream initialization."""
        stream = TFIStream(window_s=5.0, bucket_volume=100.0, max_trades=1000)
        assert stream.win.h == 5.0
        assert stream.bucket_volume == 100.0
        assert stream.max_trades == 1000

    def test_initialization_defaults(self):
        """Test TFIStream with default parameters."""
        stream = TFIStream()
        assert stream.win.h == 5.0
        assert stream.bucket_volume == 100.0
        assert stream.max_trades == 5000

    def test_ingest_trade_buy(self):
        """Test ingesting a BUY trade."""
        stream = TFIStream(window_s=10.0)
        trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=50.0,
            side=Side.BUY
        )

        stream.ingest_trade(trade)

        # Check that trade was added to internal structures
        assert len(stream._trades) == 1
        assert stream._trades[0] == trade

        # Check rolling window
        buy_vol, sell_vol = stream.win.sums(1000.0)
        assert buy_vol == 50.0
        assert sell_vol == 0.0

    def test_ingest_trade_sell(self):
        """Test ingesting a SELL trade."""
        stream = TFIStream(window_s=10.0)
        trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=30.0,
            side=Side.SELL
        )

        stream.ingest_trade(trade)

        buy_vol, sell_vol = stream.win.sums(1000.0)
        assert buy_vol == 0.0
        assert sell_vol == 30.0

    def test_ingest_multiple_trades(self):
        """Test ingesting multiple trades."""
        stream = TFIStream(window_s=10.0)

        trades = [
            Trade(timestamp=1000.0, price=100.0, size=20.0, side=Side.BUY),
            Trade(timestamp=1001.0, price=100.0, size=15.0, side=Side.SELL),
            Trade(timestamp=1002.0, price=100.0, size=25.0, side=Side.BUY),
        ]

        for trade in trades:
            stream.ingest_trade(trade)

        buy_vol, sell_vol = stream.win.sums(1002.0)
        assert buy_vol == 45.0  # 20 + 25
        assert sell_vol == 15.0

    def test_trade_eviction_by_count(self):
        """Test that old trades are evicted when max_trades is exceeded."""
        stream = TFIStream(max_trades=3)

        # Add 5 trades
        for i in range(5):
            trade = Trade(timestamp=float(i), price=100.0, size=10.0, side=Side.BUY)
            stream.ingest_trade(trade)

        # Should only keep the last 3 trades
        assert len(stream._trades) == 3
        assert stream._trades[0].timestamp == 2.0  # Oldest remaining
        assert stream._trades[-1].timestamp == 4.0  # Newest

    def test_trade_eviction_by_time(self):
        """Test that old trades are evicted based on time window."""
        stream = TFIStream(window_s=2.0)

        # Add trades spanning more than 10x window
        trades = [
            Trade(timestamp=1000.0, price=100.0, size=10.0, side=Side.BUY),
            Trade(timestamp=1001.0, price=100.0, size=10.0, side=Side.SELL),
            Trade(timestamp=1020.0, price=100.0, size=10.0, side=Side.BUY),  # 20 seconds later
        ]

        for trade in trades:
            stream.ingest_trade(trade)

        # Check current features at timestamp 1020
        features = stream.features(now_ts=1020.0)

        # Only the recent trade should be in the window
        assert features["buy_vol"] == 10.0
        assert features["sell_vol"] == 0.0
        assert features["tfi"] == 10.0

    def test_features_basic(self):
        """Test basic features extraction."""
        stream = TFIStream(window_s=10.0, bucket_volume=0.0)  # Disable bucket VPIN

        trades = [
            Trade(timestamp=1000.0, price=100.0, size=40.0, side=Side.BUY),
            Trade(timestamp=1001.0, price=100.0, size=30.0, side=Side.SELL),
            Trade(timestamp=1002.0, price=100.0, size=20.0, side=Side.BUY),
        ]

        for trade in trades:
            stream.ingest_trade(trade)

        features = stream.features(now_ts=1002.0)

        expected_keys = ["buy_vol", "sell_vol", "tfi", "vpin_like", "vpin_bucketed"]
        for key in expected_keys:
            assert key in features

        assert features["buy_vol"] == 60.0  # 40 + 20
        assert features["sell_vol"] == 30.0
        assert features["tfi"] == 30.0  # 60 - 30
        assert abs(features["vpin_like"] - (30.0 / 90.0)) < 1e-12  # |60-30|/(60+30)
        assert features["vpin_bucketed"] == 0.0  # Disabled

    def test_features_with_bucket_vpin(self):
        """Test features with bucket VPIN enabled."""
        stream = TFIStream(window_s=10.0, bucket_volume=50.0)

        trades = [
            Trade(timestamp=1000.0, price=100.0, size=30.0, side=Side.BUY),   # Bucket 1: B=30
            Trade(timestamp=1001.0, price=100.0, size=20.0, side=Side.SELL),  # Bucket 1: B=30, S=20 → complete
            Trade(timestamp=1002.0, price=100.0, size=40.0, side=Side.BUY),   # Bucket 2: B=40
        ]

        for trade in trades:
            stream.ingest_trade(trade)

        features = stream.features(now_ts=1002.0)

        # Bucket 1: |30-20|/50 = 10/50 = 0.2
        # Bucket 2: partial, ignored
        assert abs(features["vpin_bucketed"] - 0.2) < 1e-12

    def test_features_empty_stream(self):
        """Test features with empty stream."""
        stream = TFIStream()

        features = stream.features(now_ts=1000.0)

        assert features["buy_vol"] == 0.0
        assert features["sell_vol"] == 0.0
        assert features["tfi"] == 0.0
        assert features["vpin_like"] == 0.0
        assert features["vpin_bucketed"] == 0.0

    def test_features_with_now_ts_none(self):
        """Test features with now_ts=None (uses current time)."""
        stream = TFIStream(window_s=1.0)  # Short window

        # Add a trade
        trade = Trade(timestamp=time.time() - 10.0, price=100.0, size=10.0, side=Side.BUY)
        stream.ingest_trade(trade)

        # Should work without specifying now_ts
        features = stream.features()

        # Trade should be evicted due to old timestamp
        assert features["buy_vol"] == 0.0
        assert features["sell_vol"] == 0.0


class TestRollingWindow:
    """Test the internal _Rolling window class."""

    def test_rolling_initialization(self):
        """Test _Rolling initialization."""
        rolling = _Rolling(horizon_s=5.0)
        assert rolling.h == 5.0
        assert rolling.bsum == 0.0
        assert rolling.ssum == 0.0
        assert len(rolling.q) == 0

    def test_rolling_add(self):
        """Test adding trades to rolling window."""
        rolling = _Rolling(horizon_s=10.0)

        rolling.add(ts=1000.0, buy=20.0, sell=0.0)
        assert rolling.bsum == 20.0
        assert rolling.ssum == 0.0
        assert len(rolling.q) == 1

        rolling.add(ts=1001.0, buy=0.0, sell=15.0)
        assert rolling.bsum == 20.0
        assert rolling.ssum == 15.0
        assert len(rolling.q) == 2

    def test_rolling_eviction(self):
        """Test eviction of old trades."""
        rolling = _Rolling(horizon_s=5.0)

        # Add trades at different times
        rolling.add(ts=1000.0, buy=10.0, sell=0.0)
        rolling.add(ts=1002.0, buy=0.0, sell=5.0)
        rolling.add(ts=1006.0, buy=15.0, sell=0.0)  # This should evict the first trade

        # Check sums at time 1006
        buy_vol, sell_vol = rolling.sums(1006.0)

        # First trade (ts=1000) should be evicted (1006 - 1000 = 6 > 5)
        assert buy_vol == 15.0  # Only the third trade
        assert sell_vol == 5.0   # Second trade still in window

    def test_rolling_sums(self):
        """Test sums calculation."""
        rolling = _Rolling(horizon_s=10.0)

        rolling.add(ts=1000.0, buy=25.0, sell=10.0)
        rolling.add(ts=1001.0, buy=30.0, sell=20.0)

        buy_vol, sell_vol = rolling.sums(1001.0)

        assert buy_vol == 55.0  # 25 + 30
        assert sell_vol == 30.0  # 10 + 20


class TestTFIEdgeCases:
    """Test edge cases and error conditions."""

    def test_vpin_bucket_volume_zero(self):
        """Test VPIN with zero bucket volume."""
        trades = [Trade(timestamp=1.0, price=100.0, size=10.0, side=Side.BUY)]
        vpin = vpin_volume_buckets(trades, bucket_volume=0.0)
        assert vpin == 0.0

    def test_vpin_bucket_volume_negative(self):
        """Test VPIN with negative bucket volume."""
        trades = [Trade(timestamp=1.0, price=100.0, size=10.0, side=Side.BUY)]
        vpin = vpin_volume_buckets(trades, bucket_volume=-10.0)
        # Should be clamped to minimum value
        assert vpin == 0.0

    def test_tfi_stream_bucket_volume_zero(self):
        """Test TFIStream with zero bucket volume."""
        stream = TFIStream(bucket_volume=0.0)
        trade = Trade(timestamp=1000.0, price=100.0, size=10.0, side=Side.BUY)
        stream.ingest_trade(trade)

        features = stream.features()
        assert features["vpin_bucketed"] == 0.0

    def test_large_trade_sizes(self):
        """Test with very large trade sizes."""
        stream = TFIStream(window_s=10.0)

        large_trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=1e9,  # Very large size
            side=Side.BUY
        )

        stream.ingest_trade(large_trade)

        features = stream.features(now_ts=1000.0)
        assert features["buy_vol"] == 1e9
        assert features["tfi"] == 1e9

    def test_zero_size_trades(self):
        """Test with zero-size trades."""
        stream = TFIStream(window_s=10.0)

        zero_trade = Trade(
            timestamp=1000.0,
            price=100.0,
            size=0.0,
            side=Side.BUY
        )

        stream.ingest_trade(zero_trade)

        features = stream.features(now_ts=1000.0)
        assert features["buy_vol"] == 0.0
        assert features["sell_vol"] == 0.0

    def test_very_old_trades(self):
        """Test with trades far in the past."""
        stream = TFIStream(window_s=1.0)  # Very short window

        old_trade = Trade(
            timestamp=time.time() - 1000.0,  # 1000 seconds ago
            price=100.0,
            size=10.0,
            side=Side.BUY
        )

        stream.ingest_trade(old_trade)

        features = stream.features()
        # Old trade should be evicted
        assert features["buy_vol"] == 0.0
        assert features["sell_vol"] == 0.0


class TestTFISelfTests:
    """Test the self-test functions to achieve 100% coverage."""

    def test_make_trades_imbalanced(self):
        """Test _make_trades_imbalanced function."""
        from core.features.tfi import _make_trades_imbalanced

        trades = _make_trades_imbalanced(n=10, seed=42)

        assert len(trades) == 10
        # Should have more BUY than SELL trades (70% buy probability)
        buy_count = sum(1 for t in trades if str(t.side) in ["Side.BUY", "BUY"])
        sell_count = len(trades) - buy_count
        assert buy_count >= sell_count

        # All trades should have valid data
        for trade in trades:
            assert trade.timestamp > 0
            assert trade.price == 100.0
            assert trade.size > 0
            assert str(trade.side) in ["Side.BUY", "BUY", "Side.SELL", "SELL"]

    def test_make_trades_balanced(self):
        """Test _make_trades_balanced function."""
        from core.features.tfi import _make_trades_balanced

        trades = _make_trades_balanced(n=10, seed=42)

        assert len(trades) == 10
        # Should have alternating BUY/SELL
        for i, trade in enumerate(trades):
            expected_side = "BUY" if i % 2 == 0 else "SELL"
            assert str(trade.side) in [f"Side.{expected_side}", expected_side]

    def test_test_event_time_tfi_vpin(self):
        """Test _test_event_time_tfi_vpin function."""
        from core.features.tfi import _test_event_time_tfi_vpin

        # Should not raise any exceptions
        _test_event_time_tfi_vpin()

    def test_test_vpin_contrast(self):
        """Test _test_vpin_contrast function."""
        from core.features.tfi import _test_vpin_contrast

        # Should not raise any exceptions
        _test_vpin_contrast()

    def test_main_block_execution(self):
        """Test execution of the main block by running the module as a script."""
        import runpy
        import sys
        from io import StringIO
        from unittest.mock import patch

        # Capture stdout to verify the print statement
        captured_output = StringIO()

        with patch('sys.stdout', captured_output):
            # Run the module as a script
            runpy.run_module('core.features.tfi', run_name='__main__')

        # Verify the success message was printed
        output = captured_output.getvalue()
        assert "OK - repo/core/features/tfi.py self-tests passed" in output


class TestTFIInvariants:
    """Test mathematical invariants and properties."""

    def test_vpin_range_invariant(self):
        """Test that VPIN values are always in [0, 1] range."""
        test_cases = [
            (0.0, 0.0),
            (100.0, 0.0),
            (0.0, 100.0),
            (50.0, 50.0),
            (30.0, 70.0),
        ]

        for buy_vol, sell_vol in test_cases:
            vpin = vpin_like(buy_vol, sell_vol)
            assert 0.0 <= vpin <= 1.0, f"VPIN out of range: {vpin} for buy={buy_vol}, sell={sell_vol}"

    def test_vpin_bucket_range_invariant(self):
        """Test that bucket VPIN values are always in [0, 1] range."""
        test_cases = [
            [Trade(timestamp=1.0, price=100.0, size=50.0, side=Side.BUY)],
            [Trade(timestamp=1.0, price=100.0, size=100.0, side=Side.SELL)],
            [],  # Empty
        ]

        for trades in test_cases:
            vpin = vpin_volume_buckets(trades, bucket_volume=100.0)
            assert 0.0 <= vpin <= 1.0, f"Bucket VPIN out of range: {vpin}"

    def test_tfi_increment_consistency(self):
        """Test TFI increment consistency with side values."""
        buy_trade = Trade(timestamp=1000.0, price=100.0, size=10.0, side=Side.BUY)
        sell_trade = Trade(timestamp=1000.0, price=100.0, size=10.0, side=Side.SELL)

        assert tfi_increment(buy_trade) == 10.0
        assert tfi_increment(sell_trade) == -10.0

        # String versions should work the same
        buy_trade_str = Trade(timestamp=1000.0, price=100.0, size=10.0, side="BUY")
        sell_trade_str = Trade(timestamp=1000.0, price=100.0, size=10.0, side="SELL")

        assert tfi_increment(buy_trade_str) == 10.0
        assert tfi_increment(sell_trade_str) == -10.0

    def test_rolling_window_eviction(self):
        """Test that rolling window properly evicts old data."""
        rolling = _Rolling(horizon_s=5.0)

        # Add trades at different times
        times_volumes = [
            (1000.0, 10.0, 0.0),
            (1003.0, 15.0, 0.0),
            (1008.0, 20.0, 0.0),  # This should evict first trade
        ]

        for ts, buy, sell in times_volumes:
            rolling.add(ts, buy, sell)

        # At time 1008, first trade should be evicted
        buy_vol, sell_vol = rolling.sums(1008.0)
        assert buy_vol == 35.0  # 15 + 20
        assert sell_vol == 0.0

    def test_stream_features_consistency(self):
        """Test that stream features are consistent with pure functions."""
        stream = TFIStream(window_s=10.0, bucket_volume=0.0)

        # Add some trades
        trades = [
            Trade(timestamp=1000.0, price=100.0, size=25.0, side=Side.BUY),
            Trade(timestamp=1001.0, price=100.0, size=15.0, side=Side.SELL),
        ]

        for trade in trades:
            stream.ingest_trade(trade)

        features = stream.features(now_ts=1001.0)

        # Manually calculate expected values
        expected_buy = 25.0
        expected_sell = 15.0
        expected_tfi = 25.0 - 15.0
        expected_vpin_like = abs(25.0 - 15.0) / (25.0 + 15.0)

        assert abs(features["buy_vol"] - expected_buy) < 1e-12
        assert abs(features["sell_vol"] - expected_sell) < 1e-12
        assert abs(features["tfi"] - expected_tfi) < 1e-12
        assert abs(features["vpin_like"] - expected_vpin_like) < 1e-12