import pytest


def error_trap(fn, *, fallback, known_exceptions=(ValueError, TimeoutError), logger=None, why_code="WHY_TRAP_KNOWN"):
    """Generic error wrapper: returns fallback for known exceptions, re-raises unknown.

    If logger is provided, it must have a .write(record: dict) method. We emit a
    minimal record with 'why_code', 'exception_type', and 'message'.
    """
    try:
        return fn()
    except known_exceptions as e:  # known -> return fallback and log
        if logger is not None:
            logger.write({
                'why_code': why_code,
                'exception_type': type(e).__name__,
                'message': str(e),
            })
        return fallback


class _SpyLogger:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


def test_trap_returns_fallback_and_logs_known_exception(monkeypatch):
    # Arrange
    def boom_known():
        raise ValueError("bad input")

    spy = _SpyLogger()

    # Act
    out = error_trap(boom_known, fallback=42, known_exceptions=(ValueError, TimeoutError), logger=spy)

    # Assert
    assert out == 42
    assert len(spy.records) == 1
    rec = spy.records[0]
    assert rec.get('why_code') == 'WHY_TRAP_KNOWN'
    assert rec.get('exception_type') == 'ValueError'
    assert 'bad input' in rec.get('message', '')


def test_trap_reraises_unknown_exception():
    # Arrange
    class CustomError(RuntimeError):
        pass

    def boom_unknown():
        raise CustomError("oops")

    spy = _SpyLogger()

    # Act / Assert: unknown -> re-raise, no log
    with pytest.raises(CustomError):
        _ = error_trap(boom_unknown, fallback=0, known_exceptions=(ValueError, TimeoutError), logger=spy)
    assert spy.records == []


def test_trap_passthrough_on_success():
    # Arrange
    def ok():
        return 7

    spy = _SpyLogger()

    # Act
    out = error_trap(ok, fallback=0, known_exceptions=(ValueError, TimeoutError), logger=spy)

    # Assert: idempotent pass-through, no error logs
    assert out == 7
    assert spy.records == []

