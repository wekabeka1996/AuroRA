import pytest
from core.utils.timescale import to_ns

def test_to_ns_more_units():
    # Test additional units if supported
    assert to_ns(1, "ns") == 1
    assert to_ns(1, "ms") == 1_000_000
    assert to_ns(1, "s") == 1_000_000_000
    
    # Test unknown unit raises SystemExit
    with pytest.raises(SystemExit) as exc_info:
        to_ns(1, "unknown")
    assert exc_info.value.code == 62