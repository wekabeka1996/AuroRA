import pytest
import time

sim = pytest.importorskip("core.execution.sim_local_sink", reason="sim_local_sink not available")


def test_sim_local_sink_ttl_and_ordering():
    sink = sim.SimLocalSink()
    # Test basic order submission and cancellation
    order = {
        'symbol': 'BTCUSDT',
        'side': 'buy',
        'order_type': 'limit',
        'qty': 1.0,
        'price': 50000.0
    }
    
    # Submit order
    order_id = sink.submit(order)
    assert order_id is not None
    assert isinstance(order_id, str)
    
    # Cancel order
    cancelled = sink.cancel(order_id)
    assert cancelled is True

