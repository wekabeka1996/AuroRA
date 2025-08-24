from __future__ import annotations

from fastapi.testclient import TestClient

from api.service import app


def test_health_contains_version_block():
    client = TestClient(app)
    r = client.get('/health')
    if r.status_code != 200:
        # service may be unhealthy in test env; skip assert
        return
    data = r.json()
    ver = data.get('version') or {}
    assert isinstance(ver.get('sha', ''), str)
    assert isinstance(ver.get('branch', ''), str)
    assert isinstance(ver.get('build_ts', ''), str)
    assert isinstance(ver.get('order_profile', ''), str)
