from __future__ import annotations

import os
from fastapi.testclient import TestClient

from api.service import app


def test_ops_token_rotate_flow(monkeypatch):
    client = TestClient(app)
    # seed token in env
    monkeypatch.setenv('AURORA_OPS_TOKEN', 'old')
    # snapshot unauthorized
    r = client.get('/risk/snapshot', headers={'X-OPS-TOKEN': 'wrong'})
    assert r.status_code in (401, 403)
    # rotate with correct token
    r = client.post('/ops/rotate_token', json={'new_token': 'new'}, headers={'X-OPS-TOKEN': 'old'})
    assert r.status_code == 200
    # old token should be invalid now
    r = client.get('/risk/snapshot', headers={'X-OPS-TOKEN': 'old'})
    assert r.status_code in (401, 403)
    # new token works
    r = client.get('/risk/snapshot', headers={'X-OPS-TOKEN': 'new'})
    assert r.status_code == 200
