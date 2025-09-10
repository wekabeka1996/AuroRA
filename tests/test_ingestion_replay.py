import pytest

from core.ingestion.normalizer import Normalizer
from core.ingestion.replay import Replay
from core.ingestion.sync_clock import ManualClock


def _collect(it):
    return list(it)


def test_replay_basic_with_manual_clock_pacing():
    raw = [
        {"ts": 100, "type": "trade", "symbol": "BTCUSDT", "price": 100.0, "qty": 0.5},
        {"timestamp": 200, "symbol": "BTCUSDT", "bid_px": 99.5, "ask_px": 100.5, "bid_size": 1.0, "ask_size": 2.0},
    ]
    clk = ManualClock(start_wall_ns=0)
    r = Replay(source=raw, normalizer=Normalizer(strict=True), clock=clk, strict=True, pace=True)

    out = _collect(r.stream())

    # Two events emitted in order with canonical fields
    assert len(out) == 2
    assert out[0]["type"] == "trade" and out[0]["ts_ns"] == 100
    assert out[1]["type"] == "quote" and out[1]["ts_ns"] == 200

    # ManualClock should have been advanced to the last event ts
    assert clk.now_ns() == 200

    # Stats consistent
    st = r.stats.as_dict()
    assert st["processed"] == 2
    assert st["normalized"] == 2
    assert st["emitted"] == 2
    assert st["dropped_invalid"] == 0
    assert st["dropped_filtered"] == 0
    assert st["errors"] == 0


def test_replay_filters_start_end_symbols_types_post_filter():
    raw = [
        {"ts": 100, "type": "trade", "symbol": "ETHUSDT", "price": 10.0, "qty": 1.0},  # below start -> drop
        {"ts": 200, "type": "quote", "symbol": "ETHUSDT", "bid": 9.9, "ask": 10.1, "bid_size": 2.0, "ask_size": 3.0},  # post_filter drops
        {"ts": 220, "type": "trade", "symbol": "ETHUSDT", "price": 10.2, "qty": 0.4},  # keep
        {"ts": 210, "type": "trade", "symbol": "BTCUSDT", "price": 20.0, "qty": 0.1},  # symbol filter drops
    ]
    clk = ManualClock(start_wall_ns=0)
    r = Replay(source=raw, normalizer=Normalizer(strict=True), clock=clk, strict=True, pace=True)

    out = _collect(
        r.stream(
            start_ts_ns=150,
            end_ts_ns=250,
            symbols={"ETHUSDT"},
            types={"trade", "quote"},
            post_filter=lambda e: e["type"] == "trade",
        )
    )
    # Only one remains
    assert len(out) == 1 and out[0]["symbol"] == "ETHUSDT" and out[0]["type"] == "trade" and out[0]["ts_ns"] == 220

    # Stats
    st = r.stats.as_dict()
    assert st["processed"] == 4
    assert st["normalized"] == 4
    assert st["emitted"] == 1
    assert st["dropped_invalid"] == 0
    assert st["dropped_filtered"] == 3


def test_replay_strict_false_handles_invalid_and_transform_errors():
    raw = [
        {"ts": 100, "type": "trade", "symbol": "BTCUSDT", "price": 100.0, "qty": 0.5},
        {"ts": 150, "type": "trade", "symbol": "BTCUSDT", "price": 101.0},  # invalid (missing size)
        {"ts": 200, "type": "trade", "symbol": "BTCUSDT", "price": 102.0, "qty": 0.1, "tag": "boom"},
    ]

    def transform(evt):
        if evt.get("tag") == "boom":
            raise RuntimeError("transform failure")
        return evt

    clk = ManualClock(start_wall_ns=0)
    r = Replay(source=raw, normalizer=Normalizer(strict=False), clock=clk, strict=False, pace=True)

    out = _collect(r.stream(transform=transform))

    # First event emitted; second invalid dropped; third transformed raises -> dropped (strict=False)
    assert [e["ts_ns"] for e in out] == [100]

    # ManualClock advanced to ts of last normalized (even if transform failed)
    assert clk.now_ns() == 200

    st = r.stats.as_dict()
    assert st["processed"] == 3
    assert st["normalized"] == 2
    assert st["emitted"] == 1
    assert st["dropped_invalid"] == 1  # from invalid event (Normalizer returned None)
    assert st["dropped_filtered"] == 0
    assert st["errors"] == 1  # transform error


def test_replay_strict_true_raises_on_transform_error():
    raw = [{"ts": 100, "type": "trade", "symbol": "BTCUSDT", "price": 100.0, "qty": 0.5, "tag": "boom"}]

    def transform(evt):
        raise RuntimeError("transform failure")

    clk = ManualClock(start_wall_ns=0)
    r = Replay(source=raw, normalizer=Normalizer(strict=True), clock=clk, strict=True, pace=True)

    with pytest.raises(RuntimeError):
        _collect(r.stream(transform=transform))


def test_replay_strict_false_property_never_raises():
    """Property test: strict=False never raises exceptions, only increments dropped_invalid|errors."""
    raw = [
        {"ts": 100, "type": "trade", "symbol": "BTCUSDT", "price": 100.0, "qty": 0.5},
        {"ts": 150, "type": "trade", "symbol": "BTCUSDT", "price": 101.0},  # invalid (missing size)
        {"ts": 200, "type": "trade", "symbol": "BTCUSDT", "price": 102.0, "qty": 0.1, "tag": "boom"},
    ]

    def transform(evt):
        if evt.get("tag") == "boom":
            raise RuntimeError("transform failure")
        return evt

    clk = ManualClock(start_wall_ns=0)
    r = Replay(source=raw, normalizer=Normalizer(strict=False), clock=clk, strict=False, pace=True)

    # Should not raise any exceptions
    out = _collect(r.stream(transform=transform))

    # Verify stats reflect the issues without raising
    st = r.stats.as_dict()
    assert st["processed"] == 3
    assert st["normalized"] == 2  # one invalid
    assert st["emitted"] == 1     # one transform error
    assert st["dropped_invalid"] == 1
    assert st["errors"] == 1
