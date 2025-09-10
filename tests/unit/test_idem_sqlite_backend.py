import importlib
import os
import time


def test_sqlite_backend_persists_across_instances(tmp_path, monkeypatch):
    db_path = tmp_path / "idem.db"
    monkeypatch.setenv("AURORA_IDEM_BACKEND", "sqlite")
    monkeypatch.setenv("AURORA_IDEM_SQLITE_PATH", str(db_path))

    # Import/reload to apply backend selection from env
    import core.execution.idempotency as idem_mod

    importlib.reload(idem_mod)

    s1 = idem_mod.IdempotencyStore()
    key = "k1"
    assert not s1.seen(key)
    s1.mark(key, ttl_sec=5)
    assert s1.seen(key)

    # New instance over same DB should see the key (persistence)
    s2 = idem_mod.IdempotencyStore()
    assert s2.seen(key)

    # Expiry cleanup works
    exp_key = "exp"
    s2.mark(exp_key, ttl_sec=0.01)
    time.sleep(0.05)
    removed = s2.cleanup_expired()
    assert removed >= 1
    assert not s2.seen(exp_key)
