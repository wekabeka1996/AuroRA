import pytest
import numpy as np

regime = pytest.importorskip("core.regime.manager", reason="regime manager missing")


def test_quantile_trigger_simple():
    rm = regime.RegimeManager()
    # feed synthetic series
    series = np.linspace(0, 1, 100)
    changed = rm.update_with_series(series)
    assert isinstance(changed, bool)

