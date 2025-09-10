"""
CREATED BY ASSISTANT: Tests for aurora_api_lite.py.
Purpose: ensure basic endpoint logic works without requiring FastAPI runtime
by stubbing minimal interfaces; validates health, pretrade, and version flows.
"""

import asyncio
import sys
import types


def _install_fastapi_stub():
    if 'fastapi' in sys.modules:
        return
    m = types.ModuleType('fastapi')

    class HTTPException(Exception):
        def __init__(self, status_code: int, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class FastAPI:
        def __init__(self, *args, **kwargs):
            self.routes = []
        def get(self, path):
            def deco(fn):
                self.routes.append(('GET', path, fn))
                return fn
            return deco
        def post(self, path):
            def deco(fn):
                self.routes.append(('POST', path, fn))
                return fn
            return deco

    m.FastAPI = FastAPI
    m.HTTPException = HTTPException
    sys.modules['fastapi'] = m


def _install_uvicorn_stub():
    if 'uvicorn' in sys.modules:
        return
    uv = types.ModuleType('uvicorn')
    def run(*args, **kwargs):
        return None
    uv.run = run
    sys.modules['uvicorn'] = uv


_install_fastapi_stub()
_install_uvicorn_stub()


def test_health_and_version_endpoints():
    import aurora_api_lite as api
    # health
    res = asyncio.run(api.health())
    assert res["status"] == "healthy"
    assert isinstance(res.get("timestamp"), float)
    # version
    ver = asyncio.run(api.version())
    assert ver["version"] == "1.0.0"
    assert ver["mode"] == "lite"


def test_pretrade_check_invalid_qty_blocks():
    import aurora_api_lite as api
    req = {"order": {"symbol": "ETHUSDT", "qty": 0, "side": "buy"}}
    out = asyncio.run(api.pretrade_check(req))
    assert out["allow"] is False
    assert out["hard_gate"] is True
    assert out["reason"].lower().startswith("invalid")


def test_pretrade_check_btc_position_limit():
    import aurora_api_lite as api
    req = {"order": {"symbol": "BTCUSDT", "qty": 0.2, "side": "buy"}}
    out = asyncio.run(api.pretrade_check(req))
    assert out["allow"] is False
    assert out["hard_gate"] is False
    assert out["max_qty"] == 0.1
    assert out["observability"]["gate_state"] == "BLOCK"


def test_pretrade_check_passes_otherwise():
    import aurora_api_lite as api
    req = {"order": {"symbol": "ETHUSDT", "qty": 1.0, "side": "buy"}}
    out = asyncio.run(api.pretrade_check(req))
    assert out["allow"] is True
    assert out["risk_scale"] == 1.0
    assert out["observability"]["gate_state"] == "PASS"

