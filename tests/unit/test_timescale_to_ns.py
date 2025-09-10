import pytest

from core.utils.timescale import to_ns


def test_to_ns_ok():
    assert to_ns(123, "ns") == 123
    assert to_ns(1.5, "ms") == 1_500_000
    assert to_ns(2, "s") == 2_000_000_000


def test_to_ns_unknown():
    with pytest.raises(SystemExit) as e:
        to_ns(1, "minutes")
    assert int(str(e.value)) == 62
