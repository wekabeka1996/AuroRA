import pytest

norm = pytest.importorskip("core.ingestion.normalizer", reason="normalizer missing")


def test_detect_ts_unit_small_is_ns():
    assert norm._detect_ts_unit(100) == "ns"
    assert norm._detect_ts_unit(1_000_000_000) in ("s", "ms", "ns")

