import importlib
import os


def setup_module(module):
    # Ensure memory backend for unit test isolation
    os.environ["AURORA_IDEM_BACKEND"] = "memory"
    import core.execution.idempotency as idem

    importlib.reload(idem)


def test_pre_submit_and_conflict():
    from core.execution.idem_guard import mark_status, pre_submit_check

    coid = "test-oid-1"
    h1 = "abc123"
    h2 = "def456"

    # First call should return None and mark PENDING
    assert pre_submit_check(coid, h1) is None
    # Second call with same hash returns payload (duplicate)
    cached = pre_submit_check(coid, h1)
    assert cached is not None
    assert cached.get("status") == "PENDING"

    # Update status and verify persistence
    mark_status(coid, "ACK")
    again = pre_submit_check(coid, h1)
    assert again is not None
    assert again.get("status") == "ACK"

    # Conflict on different hash
    try:
        pre_submit_check(coid, h2)
        assert False, "expected conflict"
    except ValueError as e:
        assert "IDEMPOTENCY_CONFLICT" in str(e)
