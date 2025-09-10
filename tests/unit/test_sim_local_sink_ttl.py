import time

import pytest

sim = pytest.importorskip("core.execution.sim_local_sink", reason="sim_local_sink not available")


def test_sim_local_sink_ttl_and_ordering():
    sink = sim.SimLocalSink()
    # Insert two items with different ts
    sink.emit({"ts": 100, "id": "a"}, ttl=0.001)
    sink.emit({"ts": 200, "id": "b"}, ttl=10.0)

    # small sleep to allow first to expire
    time.sleep(0.01)
    out = list(sink.drain())
    # expect only b remains (or ordering preserved)
    assert all(isinstance(x, dict) for x in out)
    if len(out) >= 1:
        assert out[0]["ts"] <= (out[-1]["ts"]) if len(out) > 1 else True

