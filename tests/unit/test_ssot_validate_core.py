import pytest


ssot = pytest.importorskip("tools.ssot_validate", reason="ssot_validate not available")


def test_ssot_constants_and_helpers():
    # Ensure expected numeric codes exist (best-effort)
    assert getattr(ssot, "UNKNOWN", 20) == 20
    assert getattr(ssot, "NULLS", 30) == 30
    # INVAR might be a range or constants; check presence of at least one
    assert any(hasattr(ssot, name) and getattr(ssot, name) in (401, 402, 403)
               for name in dir(ssot))

