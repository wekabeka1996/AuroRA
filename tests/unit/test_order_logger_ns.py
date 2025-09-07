import pytest

ol = pytest.importorskip("core.order_logger", reason="order_logger missing")


def test_to_ns_timestamp_conversion():
    """Test OrderLoggers._to_ns timestamp conversion functionality."""
    # Test None returns current time in ns
    result = ol.OrderLoggers._to_ns(None)
    assert isinstance(result, int)
    assert result > 1_000_000_000_000_000_000  # Should be > 1e18 (current time in ns)

    # Test already in nanoseconds (large numbers)
    ns_timestamp = 1_600_000_000_000_000_000  # ~2020 in ns
    assert ol.OrderLoggers._to_ns(ns_timestamp) == ns_timestamp

    # Test microseconds (us) - numbers > 1e15 but < 1e18
    us_timestamp = 1_600_000_000_000_000  # ~2020 in us
    expected_ns = us_timestamp * 1_000
    assert ol.OrderLoggers._to_ns(us_timestamp) == expected_ns

    # Test milliseconds (ms) - numbers > 1e12 but < 1e15
    ms_timestamp = 1_600_000_000_000  # ~2020 in ms
    expected_ns = ms_timestamp * 1_000_000
    assert ol.OrderLoggers._to_ns(ms_timestamp) == expected_ns

    # Test seconds with decimal (float seconds) - numbers > 1e9 but < 1e12
    s_timestamp = 1_600_000_000.5  # ~2020.5 in seconds
    expected_ns = int(s_timestamp * 1_000_000_000)
    assert ol.OrderLoggers._to_ns(s_timestamp) == expected_ns

    # Test integer seconds - numbers < 1e9
    s_timestamp_int = 1_600_000_000  # ~2020 in seconds
    expected_ns = s_timestamp_int * 1_000_000_000
    assert ol.OrderLoggers._to_ns(s_timestamp_int) == expected_ns

    # Test invalid input falls back to current time
    result = ol.OrderLoggers._to_ns("invalid")
    assert isinstance(result, int)
    assert result > 1_000_000_000_000_000_000  # Should be > 1e18 (current time in ns)

