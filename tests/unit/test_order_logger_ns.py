import pytest

ol = pytest.importorskip("core.order_logger", reason="order_logger missing")


def test_to_ns_and_ascii():
    assert ol._to_ns("ns") == 1
    assert ol._to_ns("ms") == 1_000_000
    assert ol._to_ns("s") == 1_000_000_000
    with pytest.raises(ValueError):
        ol._to_ns("unknown")

