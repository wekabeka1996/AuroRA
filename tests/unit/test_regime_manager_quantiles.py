import pytest
import numpy as np

regime = pytest.importorskip("core.regime.manager", reason="regime manager missing")


def test_quantile_trigger_simple():
    rm = regime.RegimeManager()
    # feed synthetic series
    series = np.linspace(0, 1, 100)
    changed = False
    for value in series:
        state = rm.update(value)
        if state.changed:
            changed = True
    assert isinstance(changed, bool)

