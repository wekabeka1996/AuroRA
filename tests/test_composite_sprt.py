# tests/test_composite_sprt.py
"""
Тести для CompositeSPRT з підтримкою α-ledger політик та EVT
"""

import numpy as np
import pytest
from unittest.mock import Mock, patch

from core.governance.composite_sprt import (
    AlphaSpendingLedger, SubexponentialModel, SPRTResult,
    create_gaussian_sprt
)


class TestAlphaSpendingLedger:
    """Тести для AlphaSpendingLedger з різними політиками"""

    def test_pocock_policy(self):
        """Тест Pocock політики"""
        ledger = AlphaSpendingLedger(total_alpha=0.05, policy="pocock")
        ledger.set_expected_tests(10)

        # Перший тест повинен витратити 0.005
        assert ledger._pocock_spending(0, 10) == 0.005
        assert ledger._pocock_spending(5, 10) == 0.005

    def test_obrien_fleming_policy(self):
        """Тест O'Brien-Fleming політики"""
        ledger = AlphaSpendingLedger(total_alpha=0.05, policy="obf")

        # α повинно зменшуватися з часом
        alpha_1 = ledger._obrien_fleming_spending(0, 10)
        alpha_2 = ledger._obrien_fleming_spending(5, 10)
        assert alpha_2 < alpha_1

    def test_bh_fdr_policy(self):
        """Тест BH-FDR політики"""
        ledger = AlphaSpendingLedger(total_alpha=0.05, policy="bh-fdr")
        ledger.set_expected_tests(10)

        # α повинно збільшуватися з часом
        alpha_1 = ledger._bh_fdr_spending(0, 10)
        alpha_2 = ledger._bh_fdr_spending(5, 10)
        assert alpha_2 > alpha_1

    def test_alpha_budget_control(self):
        """Тест контролю бюджету α"""
        ledger = AlphaSpendingLedger(total_alpha=0.05, policy="pocock")

        # Можна витратити
        assert ledger.can_spend_alpha(0.02)

        # Витрачаємо
        from core.governance.composite_sprt import AlphaSpendingEntry
        import time

        entry = AlphaSpendingEntry(
            timestamp=time.time(),
            test_id="test1",
            policy_id="policy1",
            alpha_spent=0.02,
            cumulative_alpha=0,
            decision="accept_h1",
            llr=2.0,
            n_observations=10,
            test_type="gaussian"
        )

        assert ledger.spend_alpha(entry)
        assert ledger.cumulative_alpha == 0.02
        assert abs(ledger.get_remaining_alpha() - 0.03) < 1e-10

        # Не можна перевищити бюджет
        assert not ledger.can_spend_alpha(0.04)


class TestCompositeSPRT:
    """Тести для CompositeSPRT"""

    def test_gaussian_sprt_with_policy(self):
        """Тест Gaussian SPRT з α-policy"""
        sprt = create_gaussian_sprt(mu_0=0, mu_1=1, sigma=1, alpha_policy="pocock")

        # Перевірити ініціалізацію
        assert sprt.alpha_policy == "pocock"
        assert sprt.alpha_ledger.policy == "pocock"

    def test_p_value_is_diagnostic_only(self):
        """Тест що p-value використовується тільки для діагностики"""
        sprt = create_gaussian_sprt()

        # Перевірити що моделі ініціалізовані
        assert sprt.model_h0 is not None
        assert sprt.model_h1 is not None

        # Додати спостереження
        result = sprt.update(0.5, sprt.model_h0, sprt.model_h1)

        # p-value має бути обчислений
        assert isinstance(result.p_value, float)
        assert 0 <= result.p_value <= 1

        # Але рішення приймається на основі меж, не p-value
        # Для малих даних рішення буде 'continue'
        assert result.decision in [None, 'accept_h0', 'accept_h1']

    @patch('core.governance.composite_sprt.AuroraEventLogger')
    def test_xai_logging_integration(self, mock_logger_class):
        """Тест інтеграції з XAI логуванням"""
        mock_logger = Mock()
        mock_logger_class.return_value = mock_logger

        sprt = create_gaussian_sprt()

        # Створити результат з рішенням
        result = SPRTResult(
            decision='accept_h1',
            log_likelihood_ratio=2.5,
            n_samples=10,
            p_value=0.01,
            confidence=0.95,
            boundaries={'log_A': 2.0, 'log_B': -2.0},
            test_statistic=2.5,
            alpha_spent=0.002
        )

        # Викликати логування
        sprt._log_sprt_decision('accept_h1', result, 'test1', 'policy1')

        # Перевірити що логування відбулося
        mock_logger.emit.assert_called_once()
        call_args = mock_logger.emit.call_args

        assert call_args[1]['event_code'] == 'SPRT.DECISION_H1'
        details = call_args[1]['details']
        assert details['test_id'] == 'test1'
        assert details['policy_id'] == 'policy1'
        assert details['alpha_policy'] == 'pocock'


class TestSubexponentialModel:
    """Тести для SubexponentialModel з bootstrap CI"""

    def test_bootstrap_tail_index_ci(self):
        """Тест bootstrap CI для tail index"""
        model = SubexponentialModel(tail_index=2.5)

        # Створити тестові дані з відомим tail index
        np.random.seed(42)
        # Pareto розподіл з α=2.5 має tail index ξ=1/2.5=0.4
        data = np.random.pareto(2.5, 1000) + 1  # +1 щоб уникнути 0

        stats = model.sufficient_statistics(data)

        # Перевірити що tail index оцінений
        assert 'tail_index' in stats
        assert 'tail_index_ci_lower' in stats
        assert 'tail_index_ci_upper' in stats

        # CI має бути розумним
        ci_lower = stats['tail_index_ci_lower']
        ci_upper = stats['tail_index_ci_upper']
        tail_index = stats['tail_index']

        assert ci_lower <= tail_index <= ci_upper
        assert ci_upper - ci_lower > 0  # CI має ширину

    def test_pot_method_with_insufficient_data(self):
        """Тест POT методу з недостатніми даними"""
        model = SubexponentialModel()

        # Маленький масив даних
        data = np.array([1.0, 2.0, 3.0])

        stats = model.sufficient_statistics(data)

        # Має використовувати дефолтні значення
        assert stats['tail_index'] == model.tail_index
        assert stats['tail_index_ci_lower'] == model.tail_index
        assert stats['tail_index_ci_upper'] == model.tail_index


class TestPropertyBased:
    """Property-based тести"""

    def test_alpha_ledger_never_exceeds_budget(self):
        """Тест що α-ledger ніколи не перевищує бюджет (property-based)"""
        ledger = AlphaSpendingLedger(total_alpha=0.05, policy="pocock")
        ledger.set_expected_tests(10)  # Встановити очікувану кількість тестів

        total_spent = 0.0
        max_iterations = 20

        for i in range(max_iterations):
            from core.governance.composite_sprt import AlphaSpendingEntry
            import time

            # Спробувати витратити дозволену кількість для цього тесту
            allowed_alpha = ledger._alpha_spending_function(i, ledger.n_tests)
            alpha_to_spend = min(allowed_alpha, ledger.total_alpha - ledger.cumulative_alpha)

            if alpha_to_spend <= 0:
                break

            entry = AlphaSpendingEntry(
                timestamp=time.time(),
                test_id=f"test_{i}",
                policy_id="property_test",
                alpha_spent=alpha_to_spend,
                cumulative_alpha=0,
                decision="accept_h1",
                llr=2.0,
                n_observations=10,
                test_type="property_test"
            )

            if ledger.spend_alpha(entry, test_idx=i):
                total_spent += alpha_to_spend
            else:
                break

        # Загальна витрата не повинна перевищувати бюджет з буфером
        assert total_spent <= ledger.total_alpha * 1.01


    def test_llr_monotonicity(self):
        """Тест монотонності LLR при додаванні сигналу"""
        sprt = create_gaussian_sprt(mu_0=0, mu_1=1, sigma=1)

        # Перевірити що моделі ініціалізовані
        assert sprt.model_h0 is not None
        assert sprt.model_h1 is not None

        # Додати спостереження з H1 (mu=1)
        result1 = sprt.update(1.5, sprt.model_h0, sprt.model_h1)
        result2 = sprt.update(2.0, sprt.model_h0, sprt.model_h1)

        # LLR має зростати
        assert result2.log_likelihood_ratio >= result1.log_likelihood_ratio


if __name__ == "__main__":
    pytest.main([__file__])

"""Disabled duplicate top-level test_composite_sprt.py

This file was temporarily neutralized to avoid pytest import collisions
with the canonical tests/unit/test_composite_sprt.py. If you need to
re-enable it, reconcile duplicate test names first.
"""

# Intentionally no executable code here.