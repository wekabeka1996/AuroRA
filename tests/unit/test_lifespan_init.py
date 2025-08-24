from fastapi.testclient import TestClient

from api.service import app


def test_lifespan_initializes_state():
    with TestClient(app) as client:
        st = client.app.state
        assert hasattr(st, "events_emitter")
        assert hasattr(st, "trap_window")
        # sprt config may be optional but should exist per design
        assert hasattr(st, "sprt_cfg")
