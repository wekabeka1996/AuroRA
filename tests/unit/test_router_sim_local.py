import os

import pytest

pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Legacy sim_local adapter wiring test; superseded by core/execution/sim; quarantined"
    ),
]

from skalp_bot.runner.run_live_aurora import create_adapter


def test_create_sim_adapter_from_cfg(tmp_path, monkeypatch):
    cfg = {
        "order_sink": {"mode": "sim_local", "sim_local": {"seed": 42}},
        "symbol": "TEST/USDT",
    }
    adapter = create_adapter(cfg)
    # Adapter should be SimAdapter
    assert adapter.__class__.__name__ == "SimAdapter"
    # place_order should return closed status when using sim adapter
    res = adapter.place_order("buy", 0.001, price=None)
    assert res.get("status") == "closed"
