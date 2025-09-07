import os
import importlib
from fastapi.testclient import TestClient
from pathlib import Path


def make_client(tmp_path) -> TestClient:
    os.environ['AURORA_API_TOKEN'] = 'y' * 40
    os.environ['AURORA_IP_ALLOWLIST'] = '127.0.0.1'
    os.chdir(tmp_path)
    import api.service as svc
    importlib.reload(svc)
    return TestClient(svc.app)


def test_overlay_apply_and_active_and_rollback(tmp_path):
    client = make_client(tmp_path)
    hdr = {"X-Auth-Token": os.environ['AURORA_API_TOKEN']}

    # Apply overlay
    body = {"pretrade": {"order_profile": "er_before_slip"}}
    r = client.post('/overlay/apply', json=body, headers=hdr)
    assert r.status_code == 200, r.text
    ver = r.json().get('version')
    assert ver

    # Apply second time to ensure a backup of previous version is created
    body2 = {"guards": {"spread_bps_limit": 10}}
    r_second = client.post('/overlay/apply', json=body2, headers=hdr)
    assert r_second.status_code == 200, r_second.text
    ver2 = r_second.json().get('version')
    assert ver2

    # Active overlay exists and returns body
    r2 = client.get('/overlay/active', headers=hdr)
    assert r2.status_code == 200
    data = r2.json()
    assert 'body' in data or 'overlay' in data or 'path' in data

    # Rollback to saved version (use the version from the second apply which created the backup)
    r3 = client.post('/overlay/rollback', json={"version": ver2}, headers=hdr)
    assert r3.status_code == 200

    # Active overlay still accessible after rollback
    r4 = client.get('/overlay/active', headers=hdr)
    assert r4.status_code == 200
