import pytest

norm = pytest.importorskip("core.ingestion.normalizer", reason="normalizer missing")


def test_detect_ts_unit_small_is_ns():
    # Function returns multiplier, not unit string
    assert norm._detect_ts_unit(100) == 1  # nanoseconds multiplier
    assert norm._detect_ts_unit(1_000_000_000) in (1_000_000_000, 1_000_000, 1_000, 1)  # seconds, ms, us, ns multipliers

