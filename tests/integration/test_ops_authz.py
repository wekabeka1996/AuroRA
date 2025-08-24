from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from api.service import app


@contextmanager
def envvar(k: str, v: str):
    old = os.environ.get(k)
    os.environ[k] = v
    try:
        yield
    finally:
        if old is None:
            del os.environ[k]
        else:
            os.environ[k] = old


@pytest.mark.anyio
def test_ops_requires_token_and_validates():
    with envvar("AURORA_OPS_TOKEN", "secret"):
        with TestClient(app) as client:
            # No token → 401
            r1 = client.post("/ops/reset")
            assert r1.status_code in (401, 403)
            # Wrong token → 403
            r2 = client.post("/ops/reset", headers={"X-OPS-TOKEN": "bad"})
            assert r2.status_code == 403
            # Correct token → 200
            r3 = client.post("/ops/reset", headers={"X-OPS-TOKEN": "secret"})
            assert r3.status_code == 200

            # /risk/snapshot: no token -> 401/403, wrong -> 403, correct -> 200
            r4 = client.get("/risk/snapshot")
            assert r4.status_code in (401, 403)
            r5 = client.get("/risk/snapshot", headers={"X-OPS-TOKEN": "bad"})
            assert r5.status_code == 403
            r6 = client.get("/risk/snapshot", headers={"X-OPS-TOKEN": "secret"})
            assert r6.status_code == 200

            # /risk/set: no token -> 401/403, wrong -> 403, correct -> 200
            r7 = client.post("/risk/set", json={"size_scale": 0.2})
            assert r7.status_code in (401, 403)
            r8 = client.post("/risk/set", json={"size_scale": 0.2}, headers={"X-OPS-TOKEN": "bad"})
            assert r8.status_code == 403
            r9 = client.post("/risk/set", json={"size_scale": 0.2}, headers={"X-OPS-TOKEN": "secret"})
            assert r9.status_code == 200
