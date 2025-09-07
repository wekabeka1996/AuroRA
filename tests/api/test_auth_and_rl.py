import os
import importlib
import time
from fastapi.testclient import TestClient


def make_client(tmp_path, ip_allowlist: str | None = None) -> TestClient:
    # Configure environment before importing the service module
    os.environ['AURORA_API_TOKEN'] = 'x' * 32
    if ip_allowlist is not None:
        os.environ['AURORA_IP_ALLOWLIST'] = ip_allowlist
    else:
        os.environ.pop('AURORA_IP_ALLOWLIST', None)

    # Isolate filesystem writes
    os.chdir(tmp_path)

    # Import or reload service with new env
    import api.service as svc
    importlib.reload(svc)
    return TestClient(svc.app)


def test_mutating_requires_xauth(tmp_path):
    client = make_client(tmp_path, ip_allowlist="127.0.0.1")
    # Missing X-Auth -> 401
    r = client.post('/overlay/apply', json={"foo": "bar"})
    assert r.status_code == 401
    assert 'Missing X-Auth-Token' in r.text


def test_mutating_wrong_xauth_forbidden(tmp_path):
    client = make_client(tmp_path, ip_allowlist="127.0.0.1")
    r = client.post('/overlay/apply', json={"foo": "bar"}, headers={"X-Auth-Token": "wrong"})
    assert r.status_code == 403


def test_rate_limit_returns_429(tmp_path):
    client = make_client(tmp_path, ip_allowlist="127.0.0.1")
    # Reset limiter state for deterministic run
    from api.service import _rate_limiter
    _rate_limiter.state.clear()

    # Test with more aggressive rate limiting by using a temporary limiter
    from api.service import RateLimiter
    test_limiter = RateLimiter(rps_general=5.0, rps_mutating=2.0)  # Much lower limits

    # Patch the global rate limiter
    import api.service
    original_limiter = api.service._rate_limiter
    api.service._rate_limiter = test_limiter

    try:
        too_many = 0
        import time
        for i in range(20):  # More requests to trigger rate limit
            r = client.get('/version')
            if r.status_code == 429:
                too_many += 1
            # Smaller delay
            if i % 5 == 0:
                time.sleep(0.05)
        assert too_many >= 1, f"Expected at least 1 rate limit response, got {too_many}"
    finally:
        # Restore original limiter
        api.service._rate_limiter = original_limiter


def test_mutating_success_with_correct_token(tmp_path):
    client = make_client(tmp_path, ip_allowlist="127.0.0.1")
    hdr = {"X-Auth-Token": os.environ['AURORA_API_TOKEN']}
    r = client.post('/overlay/apply', json={"foo": "bar"}, headers=hdr)
    assert r.status_code in (200, 400)
    from importlib import reload
    import api.service as svc
    reload(svc)
    c = TestClient(svc.app)
    # hammer mutating endpoint to exceed 10 rps
    headers={"X-Auth-Token": os.environ['AURORA_API_TOKEN']}
    codes = []
    start = time.time()
    for _ in range(20):
        resp = c.post('/overlay/apply', json={"a": 1}, headers=headers)
        codes.append(resp.status_code)
    took = time.time() - start
    # Within 1 second, at least some 429 expected
    assert any(code == 429 for code in codes), codes
