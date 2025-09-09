import os
import pytest
from fastapi.testclient import TestClient

# Ensure token for OPS
os.environ.setdefault('AURORA_API_TOKEN', 'x'*32)
os.environ.setdefault('OPS_TOKEN', 'o'*32)

from api.service import app

client = TestClient(app)


def test_readiness_stable_shape_and_status():
    # When models are not loaded by design in tests, expect 503 but stable JSON body
    headers = {"X-OPS-TOKEN": os.environ['OPS_TOKEN']}
    bodies = []
    codes = []
    for _ in range(10):
        r = client.get('/readiness', headers=headers)
        codes.append(r.status_code)
        # Endpoint always returns a JSON dict body (200 or 503)
        bodies.append(r.json())
        # Cache-Control must be no-store
        assert r.headers.get('cache-control') == 'no-store'
    # Status codes should be consistent across calls
    assert len(set(codes)) == 1
    # Body shapes should be dicts with the same keys
    assert all(isinstance(b, dict) for b in bodies)
    keys0 = set(bodies[0].keys())
    for b in bodies[1:]:
        assert set(b.keys()) == keys0
    # Mandatory keys
    assert keys0 == {"config_loaded", "last_event_ts", "halt", "models_loaded"}
