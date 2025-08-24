import pytest

from living_latent.execution.gating import DecisionHysteresis, DwellConfig


def test_dwell_efficiency_one_when_no_attempts():
    dh = DecisionHysteresis(DwellConfig(min_dwell_pass=3, min_dwell_derisk=3, min_dwell_block=1))
    # Один и тот же стабильный сигнал -> ни одной попытки смены состояния
    for _ in range(5):
        dh.update("PASS")
    assert dh.transitions == 0
    # attempts == 0 => по реализации возвращается 1.0 (нейтральная эффективность)
    assert dh.dwell_efficiency() == 1.0


def test_dwell_efficiency_decreases_with_stronger_dwell():
    # Одинаковая последовательность входных решений; более высокий dwell подавляет переходы => меньше успешных переходов
    seq = ["DERISK","DERISK","PASS","DERISK","DERISK","PASS"] * 3

    dh_lo = DecisionHysteresis(DwellConfig(min_dwell_pass=1, min_dwell_derisk=1, min_dwell_block=1))
    for s in seq:
        dh_lo.update(s)
    eff_lo = dh_lo.dwell_efficiency()

    dh_hi = DecisionHysteresis(DwellConfig(min_dwell_pass=4, min_dwell_derisk=4, min_dwell_block=1))
    for s in seq:
        dh_hi.update(s)
    eff_hi = dh_hi.dwell_efficiency()

    assert 0.0 <= eff_lo <= 1.0
    assert 0.0 <= eff_hi <= 1.0
    # Жесткий dwell должен давать <= эффективность (меньше разрешённых переходов из попыток)
    assert eff_hi <= eff_lo
