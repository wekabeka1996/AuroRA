# core/governance/composite_sprt.py
"""
Композитний SPRT/GLR з підтримкою складних гіпотез
Виправлено згідно вердикту архітектора:
- t-LR для невідомої σ
- Субекспоненційні хвости для PnL
- α-spending ledger 
- Уніфікований API
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import logging
import time
from typing import Any

import numpy as np
from scipy.special import gammaln
import scipy.stats as stats

from core.aurora_event_logger import AuroraEventLogger

# Import event codes and logger
from observability.codes import SPRT_CONTINUE, SPRT_DECISION_H0, SPRT_DECISION_H1, SPRT_ERROR

logger = logging.getLogger(__name__)

class HypothesisType(Enum):
    """Типи гіпотез"""
    GAUSSIAN_KNOWN_VAR = "gaussian_known_var"
    GAUSSIAN_UNKNOWN_VAR = "gaussian_unknown_var"  # t-test
    SUBEXPONENTIAL = "subexponential"  # Heavy tails
    BERNOULLI = "bernoulli"
    COMPOSITE = "composite"

@dataclass
class AlphaSpendingEntry:
    """Запис у α-spending ledger"""
    timestamp: float
    test_id: str
    policy_id: str
    alpha_spent: float
    cumulative_alpha: float
    decision: str | None
    llr: float
    n_observations: int
    test_type: str

@dataclass
class SPRTResult:
    """Результат SPRT тесту з повною інформацією"""
    decision: str | None  # 'accept_h1', 'accept_h0', 'continue'
    log_likelihood_ratio: float
    n_samples: int
    p_value: float
    confidence: float
    boundaries: dict[str, float]
    test_statistic: float
    alpha_spent: float

class HypothesisModel(ABC):
    """Абстрактний клас для моделей гіпотез"""

    @abstractmethod
    def log_likelihood(self, observation: float, **params) -> float:
        """Обчислити log-likelihood для спостереження"""
        pass

    @abstractmethod
    def sufficient_statistics(self, observations: np.ndarray) -> dict[str, float | int]:
        """Обчислити достатні статистики"""
        pass

class GaussianKnownVarModel(HypothesisModel):
    """Gaussian модель з відомою дисперсією"""

    def log_likelihood(self, observation: float, **params) -> float:
        mu = params.get('mu', 0)
        sigma = params.get('sigma', 1)
        return -0.5 * np.log(2 * np.pi * sigma**2) - 0.5 * ((observation - mu) / sigma) ** 2

    def sufficient_statistics(self, observations: np.ndarray) -> dict[str, float]:
        return {
            'sum': np.sum(observations),
            'sum_squares': np.sum(observations**2),
            'n': len(observations)
        }

class StudentTModel(HypothesisModel):
    """Student's t-model для невідомої дисперсії"""

    def log_likelihood(self, observation: float, **params) -> float:
        mu = params.get('mu', 0)
        nu = params.get('nu', 1)
        scale = params.get('scale', 1)
        """Log-likelihood для t-розподілу"""
        return (gammaln((nu + 1) / 2) - gammaln(nu / 2) -
                0.5 * np.log(np.pi * nu * scale**2) -
                (nu + 1) / 2 * np.log(1 + ((observation - mu) / scale)**2 / nu))

    def sufficient_statistics(self, observations: np.ndarray) -> dict[str, float | int]:
        n = len(observations)
        if n < 2:
            return {'sum': 0.0, 'sum_squares': 0.0, 'n': 0}

        sample_mean = float(np.mean(observations))
        sample_var = float(np.var(observations, ddof=1))

        return {
            'sum': float(np.sum(observations)),
            'sum_squares': float(np.sum(observations**2)),
            'n': int(n),
            'sample_mean': sample_mean,
            'sample_var': sample_var,
            't_statistic': float(sample_mean * np.sqrt(n) / np.sqrt(sample_var)) if sample_var > 0 else 0.0
        }

class SubexponentialModel(HypothesisModel):
    """Субекспоненційна модель для важких хвостів PnL"""

    def __init__(self, tail_index: float = 2.5):
        self.tail_index = tail_index

    def log_likelihood(self, observation: float, **params) -> float:
        location = params.get('location', 0)
        scale = params.get('scale', 1)
        shape = params.get('shape', 0.1)
        """Generalized Pareto log-likelihood для обох хвостів"""

        # Для лівого хвоста (від'ємні значення) віддзеркалюємо
        if observation < location:
            # Віддзеркалюємо відносно location для моделювання лівого хвоста
            mirrored_obs = 2 * location - observation
            z = (mirrored_obs - location) / scale
        else:
            z = (observation - location) / scale

        if shape == 0:
            return -np.log(scale) - z
        else:
            if 1 + shape * z <= 0:
                return -np.inf
            return -np.log(scale) - (1 + 1/shape) * np.log(1 + shape * z)

    def sufficient_statistics(self, observations: np.ndarray) -> dict[str, float]:
        """Обчислити статистики для субекспоненційного розподілу з використанням POT та bootstrap CI"""
        if len(observations) == 0:
            return {'n': 0}

        # Використовуємо метод моментів для оцінки параметрів
        sample_mean = float(np.mean(observations))
        sample_var = float(np.var(observations))
        sample_skew = float(stats.skew(observations))
        sample_kurt = float(stats.kurtosis(observations))

        # POT (Peak-Over-Threshold) для важких хвостів
        # Використовуємо тільки додатні спостереження для оцінки хвоста
        positive_obs = observations[observations > 0]
        if len(positive_obs) < 10:  # Недостатньо даних для POT
            tail_index = self.tail_index
            threshold = 0.0
            excesses = np.array([])
            tail_index_ci = (tail_index, tail_index)
        else:
            # Визначаємо threshold як 90-й перцентиль додатніх значень
            threshold = float(np.percentile(positive_obs, 90))
            excesses = positive_obs[positive_obs > threshold] - threshold

            if len(excesses) > 5:  # Мінімум для оцінки
                # Hill-оцінка для excesses (вже додатні)
                sorted_excesses = np.sort(excesses)
                k = max(1, len(excesses) // 4)  # Використовуємо верхні 25%
                if k > 1:
                    # excesses вже додатні, тому log безпечний
                    hill_estimate = np.mean(np.log(sorted_excesses[-k:]) - np.log(sorted_excesses[-k]))
                    tail_index = 1 / hill_estimate if hill_estimate > 0 else self.tail_index

                    # Bootstrap CI для tail index
                    tail_index_ci = self._bootstrap_tail_index_ci(excesses, k, n_bootstrap=1000)
                else:
                    tail_index = self.tail_index
                    tail_index_ci = (tail_index, tail_index)
            else:
                tail_index = self.tail_index
                tail_index_ci = (tail_index, tail_index)

        return {
            'n': len(observations),
            'mean': sample_mean,
            'var': sample_var,
            'skewness': sample_skew,
            'kurtosis': sample_kurt,
            'tail_index': tail_index,
            'tail_index_ci_lower': tail_index_ci[0],
            'tail_index_ci_upper': tail_index_ci[1],
            'pot_threshold': threshold,
            'n_excesses': len(excesses),
            'max': float(np.max(observations)),
            'min': float(np.min(observations))
        }

    def _bootstrap_tail_index_ci(self, excesses: np.ndarray, k: int,
                                n_bootstrap: int = 1000, ci_level: float = 0.95) -> tuple[float, float]:
        """
        Обчислити bootstrap confidence interval для tail index
        
        Args:
            excesses: Масив excesses для Hill оцінки
            k: Кількість верхніх значень для Hill оцінки
            n_bootstrap: Кількість bootstrap вибірок
            ci_level: Рівень confidence interval
            
        Returns:
            Tuple (lower_ci, upper_ci) для tail index
        """
        if len(excesses) < k:
            return (self.tail_index, self.tail_index)

        tail_indices = []

        for _ in range(n_bootstrap):
            # Bootstrap вибірка
            bootstrap_sample = np.random.choice(excesses, size=len(excesses), replace=True)
            sorted_bootstrap = np.sort(bootstrap_sample)

            if len(sorted_bootstrap) >= k:
                # Hill оцінка для bootstrap вибірки
                hill_est = np.mean(np.log(sorted_bootstrap[-k:]) - np.log(sorted_bootstrap[-k]))
                if hill_est > 0:
                    tail_indices.append(1 / hill_est)

        if not tail_indices:
            return (self.tail_index, self.tail_index)

        # Обчислити CI
        tail_indices = np.array(tail_indices)
        lower_percentile = (1 - ci_level) / 2 * 100
        upper_percentile = (1 + ci_level) / 2 * 100

        lower_ci = float(np.percentile(tail_indices, lower_percentile))
        upper_ci = float(np.percentile(tail_indices, upper_percentile))

        return (lower_ci, upper_ci)

class CompositeHypothesis:
    """Композитна гіпотеза з множинними компонентами"""

    def __init__(self, components: list[tuple[HypothesisModel, dict, float]]):
        """
        components: List[(model, params, weight)]
        """
        self.components = components
        self.weights = np.array([w for _, _, w in components])
        self.weights /= np.sum(self.weights)  # Normalize

    def log_likelihood(self, observation: float) -> float:
        """Змішана log-likelihood"""
        ll_components = []

        for (model, params, weight) in self.components:
            try:
                ll = model.log_likelihood(observation, **params)
                ll_components.append(ll + np.log(weight))
            except Exception:
                # If a component fails, treat its contribution as negligible
                ll_components.append(-np.inf)

        if not ll_components:
            return -np.inf

        # Log-sum-exp trick
        max_ll = max(ll_components)
        if max_ll == -np.inf:
            return -np.inf

        return max_ll + np.log(sum(np.exp(ll - max_ll) for ll in ll_components))

class AlphaSpendingLedger:
    """Ledger для контролю витрат α при множинних тестах з підтримкою різних політик"""

    def __init__(self, total_alpha: float = 0.05, policy: str = "pocock"):
        """
        Args:
            total_alpha: Загальний бюджет α
            policy: Політика витрат α
                - "pocock": Постійна α на тест (α_total / n_tests)
                - "obf": O'Brien-Fleming (α зменшується з часом)
                - "bh-fdr": Benjamini-Hochberg FDR контроль
        """
        self.total_alpha = total_alpha
        self.policy = policy.lower()
        self.entries: list[AlphaSpendingEntry] = []
        self.cumulative_alpha = 0.0
        self.n_tests = 0

        # Ініціалізувати функцію витрат залежно від політики
        self._alpha_spending_function = self._get_alpha_spending_function()

    def _get_alpha_spending_function(self):
        """Отримати функцію витрат α для даної політики"""
        if self.policy == "pocock":
            return self._pocock_spending
        elif self.policy == "obf":
            return self._obrien_fleming_spending
        elif self.policy == "bh-fdr":
            return self._bh_fdr_spending
        else:
            logger.warning(f"Unknown policy {self.policy}, using pocock")
            return self._pocock_spending

    def _pocock_spending(self, test_idx: int, total_tests: int) -> float:
        """Pocock: постійна α на тест"""
        if total_tests <= 0:
            return self.total_alpha
        return self.total_alpha / total_tests

    def _obrien_fleming_spending(self, test_idx: int, total_tests: int) -> float:
        """O'Brien-Fleming: α зменшується з часом"""
        if total_tests <= 0 or test_idx < 0:
            return self.total_alpha

        # α(t) = 2 * (1 - Φ(z_α/2 / √t))
        # Спрощена версія: α(t) = α_total * (2 / t)
        t = test_idx + 1
        return min(self.total_alpha, self.total_alpha * 2 / t)

    def _bh_fdr_spending(self, test_idx: int, total_tests: int) -> float:
        """Benjamini-Hochberg FDR контроль"""
        if total_tests <= 0:
            return self.total_alpha

        # BH: α(t) = α_total * t / total_tests
        t = test_idx + 1
        return self.total_alpha * t / total_tests

    def can_spend_alpha(self, requested_alpha: float, test_idx: int | None = None) -> bool:
        """Перевірити чи можна витратити α з урахуванням політики"""
        if test_idx is None:
            test_idx = len(self.entries)

        # Обчислити дозволену α для цього тесту
        allowed_alpha = self._alpha_spending_function(test_idx, max(1, self.n_tests))

        return self.cumulative_alpha + min(requested_alpha, allowed_alpha) <= self.total_alpha

    def spend_alpha(self, entry: AlphaSpendingEntry, test_idx: int | None = None) -> bool:
        """Витратити α та записати в ledger з урахуванням політики"""
        if test_idx is None:
            test_idx = len(self.entries)

        # Обчислити дозволену α для цього тесту
        allowed_alpha = self._alpha_spending_function(test_idx, max(1, self.n_tests))
        actual_spend = min(entry.alpha_spent, allowed_alpha)

        if not self.can_spend_alpha(actual_spend, test_idx):
            logger.warning(f"Cannot spend α={actual_spend}, cumulative={self.cumulative_alpha}, policy={self.policy}")
            return False

        # Оновити entry з фактичною витратою
        entry.alpha_spent = actual_spend

        self.cumulative_alpha += actual_spend
        entry.cumulative_alpha = self.cumulative_alpha
        self.entries.append(entry)

        logger.info(f"Alpha spent: {actual_spend}, cumulative: {self.cumulative_alpha}, policy: {self.policy}")
        return True

    def set_expected_tests(self, n_tests: int) -> None:
        """Встановити очікувану кількість тестів для планування витрат α"""
        self.n_tests = max(1, n_tests)
        logger.info(f"Set expected tests: {self.n_tests}, policy: {self.policy}")

    def get_remaining_alpha(self) -> float:
        """Повернути залишок α, доступний для витрачання."""
        remaining = self.total_alpha - self.cumulative_alpha
        return float(remaining) if remaining > 0.0 else 0.0

    def reset(self) -> None:
        """Скинути ledger до початкового стану"""
        self.entries.clear()
        self.cumulative_alpha = 0.0
        self.n_tests = 0
        logger.info(f"AlphaSpendingLedger reset, policy: {self.policy}")

    def get_policy_info(self) -> dict[str, Any]:
        """Отримати інформацію про поточну політику"""
        return {
            'policy': self.policy,
            'total_alpha': self.total_alpha,
            'cumulative_alpha': self.cumulative_alpha,
            'remaining_alpha': self.get_remaining_alpha(),
            'n_tests': self.n_tests,
            'n_entries': len(self.entries)
        }

class CompositeSPRT:
    """
    Композитний SPRT з підтримкою складних гіпотез
    Згідно вимог архітектора - уніфікований API
    """

    def __init__(self,
                 alpha: float = 0.05,
                 beta: float = 0.20,
                 alpha_ledger: AlphaSpendingLedger | None = None,
                 alpha_policy: str = "pocock"):
        """
        Args:
            alpha: Рівень значущості (Type I error)
            beta: Рівень потужності (Type II error) 
            alpha_ledger: Ledger для контролю витрат α
            alpha_policy: Політика витрат α ("pocock", "obf", "bh-fdr")
        """
        self.alpha = alpha
        self.beta = beta
        self.alpha_policy = alpha_policy

        if alpha_ledger is None:
            alpha_ledger = AlphaSpendingLedger(alpha * 10, policy=alpha_policy)
        self.alpha_ledger = alpha_ledger

        # Границі рішень
        self.log_A = np.log((1 - self.beta) / self.alpha)
        self.log_B = np.log(self.beta / (1 - self.alpha))

        # Стан тесту
        self.reset()

        # Моделі та параметри для фабричних функцій
        self.model_h0: HypothesisModel | None = None
        self.model_h1: HypothesisModel | None = None
        self.params_h0: dict[str, float] = {}
        self.params_h1: dict[str, float] = {}

    def reset(self) -> None:
        """Скинути стан тесту"""
        self.observations: list[float] = []
        self.log_lr = 0.0
        self.n_samples = 0
        self.sufficient_stats_h0 = {}
        self.sufficient_stats_h1 = {}

    def update(self,
               observation: float,
               model_h0: HypothesisModel | CompositeHypothesis,
               model_h1: HypothesisModel | CompositeHypothesis,
               weight: float = 1.0,
               test_id: str = "default",
               policy_id: str = "default") -> SPRTResult:
        """
        Уніфікований API для оновлення SPRT
        
        Args:
            observation: Нове спостереження
            model_h0: Модель нульової гіпотези
            model_h1: Модель альтернативної гіпотези  
            weight: Вага спостереження
            test_id: ID тесту для α-ledger
            policy_id: ID політики
            
        Returns:
            SPRTResult з рішенням та метриками
        """

        self.observations.append(observation)
        self.n_samples += 1

        # Обчислити log-likelihoods
        try:
            if isinstance(model_h0, CompositeHypothesis):
                ll_h0 = model_h0.log_likelihood(observation)
            else:
                # Для простих моделей потрібні параметри
                ll_h0 = self._calculate_likelihood(observation, model_h0, 'h0')

            if isinstance(model_h1, CompositeHypothesis):
                ll_h1 = model_h1.log_likelihood(observation)
            else:
                ll_h1 = self._calculate_likelihood(observation, model_h1, 'h1')

        except Exception as e:
            logger.error(f"Error calculating likelihoods: {e}")
            return self._create_error_result()

        # Оновити log-likelihood ratio з вагою
        self.log_lr += weight * (ll_h1 - ll_h0)

        # Прийняти рішення
        decision = self._make_decision()

        # Обчислити p-value
        p_value = self._calculate_p_value()

        # Обчислити confidence
        confidence = self._calculate_confidence()

        # Створити результат
        result = SPRTResult(
            decision=decision,
            log_likelihood_ratio=self.log_lr,
            n_samples=self.n_samples,
            p_value=p_value,
            confidence=confidence,
            boundaries={'log_A': self.log_A, 'log_B': self.log_B},
            test_statistic=self.log_lr,
            alpha_spent=0.0  # Буде оновлено нижче
        )

        # Alpha spending
        alpha_spent = 0.0
        if decision is not None:
            alpha_spent = self._calculate_alpha_spent(decision)
            result.alpha_spent = alpha_spent

            # Записати в ledger тільки якщо є витрата α
            if alpha_spent > 0:
                entry = AlphaSpendingEntry(
                    timestamp=time.time(),
                    test_id=test_id,
                    policy_id=policy_id,
                    alpha_spent=alpha_spent,
                    cumulative_alpha=0,  # Буде оновлено в ledger
                    decision=decision,
                    llr=self.log_lr,
                    n_observations=self.n_samples,
                    test_type=f"{type(model_h0).__name__}_vs_{type(model_h1).__name__}"
                )

                success = self.alpha_ledger.spend_alpha(entry)
                if success:
                    result.alpha_spent = entry.alpha_spent  # Update with actual spent amount
                    logger.info(f"Alpha spent successfully: {entry.alpha_spent}")
                else:
                    logger.warning(f"Failed to spend alpha: {alpha_spent}")

            # Логувати рішення до XAI
            self._log_sprt_decision(decision, result, test_id, policy_id)

        return result

    def _calculate_likelihood(self, observation: float,
                            model: HypothesisModel,
                            hypothesis: str) -> float:
        """Обчислити likelihood для простої моделі"""

        # Для простих моделей використовуємо збережені параметри
        if hasattr(self, 'params_h0') and hasattr(self, 'params_h1'):
            params = self.params_h0 if hypothesis == 'h0' else self.params_h1
            return model.log_likelihood(observation, **params)

        # Fallback для моделей без параметрів
        if isinstance(model, StudentTModel):
            return self._t_test_likelihood(observation, {}, hypothesis)
        elif isinstance(model, SubexponentialModel):
            # Use current observations for stats
            if self.observations:
                stats = model.sufficient_statistics(np.array(self.observations))
                return self._subexp_likelihood(observation, stats)
            else:
                return -1  # No data yet
        else:
            # Gaussian з відомою дисперсією - fallback
            mu = 0.0 if hypothesis == 'h0' else 1.0
            return model.log_likelihood(observation, mu=mu)

    def _t_test_likelihood(self, observation: float,
                          stat_dict: dict, hypothesis: str) -> float:
        """t-test likelihood для невідомої дисперсії"""

        n = stat_dict.get('n', 0)
        if n < 2:
            return 0.0

        sample_mean = stat_dict.get('sample_mean', 0)
        sample_var = stat_dict.get('sample_var', 1)

        # Використовуємо t-розподіл з n-1 ступенями свободи
        if hypothesis == 'h0':
            mu_0 = 0.0  # Null hypothesis mean
        else:
            mu_0 = sample_mean  # Alternative uses sample mean

        if sample_var <= 0:
            return -np.inf

        t_stat = (observation - mu_0) / np.sqrt(sample_var / n)
        return float(stats.t.logpdf(t_stat, df=n-1))

    def _subexp_likelihood(self, observation: float, stats: dict) -> float:
        """Субекспоненційна likelihood"""
        # Use safe defaults if stats are missing or invalid
        tail_index = max(stats.get('tail_index', 2.5), 1.1)  # Ensure > 1
        location = stats.get('min', 0)
        scale = max(stats.get('var', 1) ** 0.5, 1e-6)  # Ensure positive
        shape = 1 / tail_index if tail_index > 0 else 0.1

        # For subexponential, we typically work with positive observations
        if observation <= location:
            return -10  # Penalize observations below location

        z = (observation - location) / scale

        if shape == 0:
            return -np.log(scale) - z
        else:
            if 1 + shape * z <= 0:
                return -100  # Very unlikely
            try:
                log_term = np.log(1 + shape * z)
                if np.isnan(log_term) or np.isinf(log_term):
                    return -100
                return -np.log(scale) - (1 + 1/shape) * log_term
            except Exception:
                return -100

    def _make_decision(self) -> str | None:
        """Прийняти рішення на основі boundaries"""
        if self.log_lr >= self.log_A:
            return 'accept_h1'
        elif self.log_lr <= self.log_B:
            return 'accept_h0'
        else:
            return None  # Continue testing

    def _calculate_p_value(self) -> float:
        """
        Обчислити p-value для діагностики
        
        УВАГА: Цей p-value використовується ТІЛЬКИ для діагностики та моніторингу!
        Governance рішення приймаються ВИКЛЮЧНО на основі перетину меж A/B,
        а не на основі p-value. Асимптотична апроксимація χ² може бути неточною
        для малих вибірок або складних розподілів.
        
        Returns:
            p-value як діагностичну метрику (не для прийняття рішень)
        """
        if self.n_samples < 2:
            return 0.5

        # Використовуємо асимптотичний розподіл LLR
        # Під H0: 2*LLR ~ χ²(df)
        test_stat = 2 * abs(self.log_lr)
        df = 1  # Degrees of freedom

        p_value = 1 - stats.chi2.cdf(test_stat, df)
        return max(1e-10, min(1.0, float(p_value)))

    def _calculate_confidence(self) -> float:
        """Обчислити впевненість у рішенні"""
        if self.n_samples < 2:
            return 0.0  # Return 0 for insufficient samples

        # Відстань від boundaries
        dist_to_A = abs(self.log_lr - self.log_A)
        dist_to_B = abs(self.log_lr - self.log_B)

        if self.log_lr >= self.log_A:
            # Accept H1 - confidence based on distance from boundary
            confidence = min(1.0, 0.5 + dist_to_A / max(self.log_A - self.log_B, 1e-6))
        elif self.log_lr <= self.log_B:
            # Accept H0
            confidence = min(1.0, 0.5 + dist_to_B / max(self.log_A - self.log_B, 1e-6))
        else:
            # Continue testing - partial confidence based on position
            boundary_range = self.log_A - self.log_B
            if boundary_range > 0:
                progress = (self.log_lr - self.log_B) / boundary_range
                confidence = 0.5 + 0.4 * (abs(progress - 0.5) / 0.5)  # Scale to 0.5-0.9 range
            else:
                confidence = 0.5

        return np.clip(confidence, 0.0, 1.0)

    def _calculate_alpha_spent(self, decision: str) -> float:
        """Обчислити витрачену α"""
        if decision == 'accept_h1':
            # Type I error probability - more conservative estimate
            if self.log_lr > self.log_A:
                return min(self.alpha, self.alpha * np.exp(-(self.log_lr - self.log_A)))
            else:
                return self.alpha * 0.1  # Small spending for boundary decisions
        elif decision == 'accept_h0':
            # Type II error probability - counted as alpha for conservatism
            if self.log_lr < self.log_B:
                return min(self.beta, self.beta * np.exp(-(self.log_B - self.log_lr)))
            else:
                return self.beta * 0.1  # Small spending for boundary decisions
        else:
            return 0.0

    def _create_error_result(self) -> SPRTResult:
        """Створити результат при помилці"""
        return SPRTResult(
            decision=None,
            log_likelihood_ratio=self.log_lr,
            n_samples=self.n_samples,
            p_value=1.0,  # Error should have p_value=1.0 (no evidence)
            confidence=0.0,  # Error should have 0 confidence
            boundaries={'log_A': self.log_A, 'log_B': self.log_B},
            test_statistic=self.log_lr,
            alpha_spent=0.0
        )

    def _log_sprt_decision(self, decision: str | None, result: SPRTResult,
                          test_id: str, policy_id: str) -> None:
        """Логувати рішення SPRT до XAI з повною інформацією"""
        try:
            # Ініціалізувати логгер якщо потрібно
            if not hasattr(self, '_event_logger'):
                self._event_logger = AuroraEventLogger()

            # Визначити код події
            if decision == 'accept_h1':
                event_code = SPRT_DECISION_H1
            elif decision == 'accept_h0':
                event_code = SPRT_DECISION_H0
            elif decision is None:
                event_code = SPRT_CONTINUE
            else:
                event_code = SPRT_ERROR

            # Підготувати деталі для логування
            details = {
                'test_id': test_id,
                'policy_id': policy_id,
                'llr': result.log_likelihood_ratio,
                'n_samples': result.n_samples,
                'p_value': result.p_value,
                'confidence': result.confidence,
                'boundaries': result.boundaries,
                'alpha_spent': result.alpha_spent,
                'test_statistic': result.test_statistic,
                'decision': decision or 'continue',
                'alpha_policy': self.alpha_policy,
                'alpha_ledger_info': self.alpha_ledger.get_policy_info()
            }

            # Додати специфічні метрики залежно від типу моделі
            if hasattr(self, 'model_h0') and self.model_h0:
                details['model_h0_type'] = type(self.model_h0).__name__
            if hasattr(self, 'model_h1') and self.model_h1:
                details['model_h1_type'] = type(self.model_h1).__name__

            # Додати EVT метрики якщо доступні
            if hasattr(self, 'sufficient_stats_h1') and self.sufficient_stats_h1:
                stats = self.sufficient_stats_h1
                if 'tail_index' in stats:
                    details['tail_index'] = stats['tail_index']
                    if 'tail_index_ci_lower' in stats and 'tail_index_ci_upper' in stats:
                        details['tail_index_ci'] = {
                            'lower': stats['tail_index_ci_lower'],
                            'upper': stats['tail_index_ci_upper']
                        }
                    if 'pot_threshold' in stats:
                        details['pot_threshold'] = stats['pot_threshold']
                    if 'n_excesses' in stats:
                        details['n_excesses'] = stats['n_excesses']

            # Логувати подію
            self._event_logger.emit(
                event_code=event_code,
                details=details,
                src='composite_sprt'
            )

        except Exception as e:
            logger.error(f"Failed to log SPRT decision: {e}")
            # Не дозволяти помилкам логування зривати основну логіку

# Factory functions для зручності
def create_gaussian_sprt(mu_0: float = 0, mu_1: float = 1,
                        sigma: float = 1, alpha_policy: str = "pocock", **kwargs) -> CompositeSPRT:
    """Створити SPRT для Gaussian гіпотез з відомою σ"""
    sprt = CompositeSPRT(alpha_policy=alpha_policy, **kwargs)

    # Додаємо моделі як атрибути для use в update
    sprt.model_h0 = GaussianKnownVarModel()
    sprt.model_h1 = GaussianKnownVarModel()
    sprt.params_h0 = {'mu': mu_0, 'sigma': sigma}
    sprt.params_h1 = {'mu': mu_1, 'sigma': sigma}

    return sprt

def create_t_test_sprt(mu_0: float = 0, alpha_policy: str = "pocock", **kwargs) -> CompositeSPRT:
    """Створити SPRT для t-test (невідома σ)"""
    sprt = CompositeSPRT(alpha_policy=alpha_policy, **kwargs)
    sprt.model_h0 = StudentTModel()
    sprt.model_h1 = StudentTModel()
    return sprt

def create_subexponential_sprt(tail_index: float = 2.5, alpha_policy: str = "pocock", **kwargs) -> CompositeSPRT:
    """Створити SPRT для субекспоненційних хвостів"""
    sprt = CompositeSPRT(alpha_policy=alpha_policy, **kwargs)
    sprt.model_h0 = SubexponentialModel(tail_index)
    sprt.model_h1 = SubexponentialModel(tail_index * 0.8)  # Alternative has heavier tails
    return sprt
