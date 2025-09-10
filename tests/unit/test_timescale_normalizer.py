import pytest

from core.utils.timescale import to_ns


def test_ns():
    assert to_ns(123, "ns") == 123

def test_ms():
    assert to_ns(1.5, "ms") == 1_500_000

def test_s():
    assert to_ns(2, "s") == 2_000_000_000

def test_unknown():
    with pytest.raises(SystemExit) as e:
        to_ns(1, "us")
    assert e.value.code == 62
