from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, Counter

from living_latent.service.api import create_app
from living_latent.service.context import CTX

class DummyAcceptance:
    def __init__(self, state="PASS"):
        self._state = state
    def stats(self):  # minimal stub used by api
        return {
            "current_state": self._state,
            "last_decision": self._state,
            "kappa_plus_last": 0.82,
            "surprisal_p95": 2.1,
            "coverage_ema": 0.92,
            "latency_p95": 80.0,
            "alpha": 0.11,
            "alpha_target": 0.10,
        }

def test_api_endpoints_basic():
    # Prepare context
    CTX.set_profile("test")
    CTX.set_acceptance(DummyAcceptance())
    reg = CollectorRegistry()
    c = Counter("aurora_acceptance_decision_total", "desc", labelnames=("decision","profile"), registry=reg)
    c.labels("PASS","test").inc()
    CTX.set_registry(reg)

    app = create_app()
    client = TestClient(app)

    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"

    r = client.get("/readyz")
    assert r.status_code == 200 and r.json()["ready"] is True and r.json()["profile"] == "test"

    r = client.get("/state")
    js = r.json()
    assert js["profile"] == "test" and js["state"] == "PASS" and abs(js["kappa_plus"] - 0.82) < 1e-9

    r = client.get("/metrics")
    assert r.status_code == 200 and "aurora_acceptance_decision_total" in r.text
