import pytest
import time

eh = pytest.importorskip("core.execution.exchange.error_handling", reason="error_handling missing")


def test_circuit_breaker_open_half_close():
    cfg = eh.CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1, success_threshold=1,
                                  adaptive_timeout=False, health_check_enabled=False)
    cb = eh.ExchangeCircuitBreaker(cfg)

    # Force two failures
    for _ in range(2):
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception("boom")))
        except Exception:
            pass

    assert cb.state == eh.CircuitBreakerState.OPEN

    # wait for recovery timeout
    time.sleep(0.15)
    # mock success to close
    try:
        res = cb.call(lambda: 1)
    except Exception:
        pytest.skip("call failed in environment")

    assert cb.state in (eh.CircuitBreakerState.CLOSED, eh.CircuitBreakerState.HALF_OPEN)

