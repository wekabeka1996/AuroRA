
import numpy as np
from dataclasses import dataclass
from typing import Sequence, Optional

@dataclass
class CTRResult:
    ctr: float
    source_coverage: float
    target_coverage: float
    nominal_coverage: float
    n_source: int
    n_target: int
    alpha: float
    def as_dict(self):
        return {
            "ctr": self.ctr,
            "source_coverage": self.source_coverage,
            "target_coverage": self.target_coverage,
            "nominal_coverage": self.nominal_coverage,
            "n_source": self.n_source,
            "n_target": self.n_target,
            "alpha": self.alpha,
        }


def compute_ctr(
    source_residuals: Sequence[float],
    target_residuals: Sequence[float],
    alpha: float = 0.1,
    method: str = "quantile",
    min_samples: int = 50,
    eps: float = 1e-9,
) -> CTRResult:
    """Обчислює Coverage Transfer Ratio (CTR).

    Ідея: якщо розподіл похибок (residuals) стабільний між source і target доменами,
    то емпіричне покриття інтервалу, побудованого на source, збережеться на target (CTR≈1).

    1. Оцінюємо симетричний (1-alpha) інтервал по source_residuals.
       Використовуємо квантилі (alpha/2, 1-alpha/2) або альтернативні методи.
    2. Рахуємо фактичне покриття у source (для sanity) і у target.
    3. CTR = min(source_cov, target_cov) / max(source_cov, target_cov)  (стиснутий у [0,1]).
       Альтернатива: target_cov / source_cov (але тоді >1 можливе). Обираємо симетричну форму.

    :param source_residuals: Послідовність резидуалів (y - y_hat) у вихідному домені.
    :param target_residuals: Послідовність резидуалів у цільовому домені.
    :param alpha: Рівень значущості (напр. 0.1 => 90% інтервал).
    :param method: Поки що тільки 'quantile'.
    :param min_samples: Мінімальна кількість зразків для кожного домену.
    :param eps: Числова стабільність.
    :return: CTRResult
    """
    source = np.asarray(source_residuals, dtype=float)
    target = np.asarray(target_residuals, dtype=float)
    if source.size < min_samples or target.size < min_samples:
        raise ValueError(f"Not enough samples for CTR: source={source.size}, target={target.size}, required>={min_samples}")
    if not (0 < alpha < 1):
        raise ValueError("alpha must be in (0,1)")
    if method != "quantile":
        raise ValueError("Only 'quantile' method supported currently")

    lower_q = alpha / 2
    upper_q = 1 - alpha / 2
    lo = np.quantile(source, lower_q)
    hi = np.quantile(source, upper_q)
    if hi - lo < eps:
        # Вироджений інтервал -> CTR поганий (0)
        return CTRResult(ctr=0.0, source_coverage=0.0, target_coverage=0.0, nominal_coverage=1-alpha,
                         n_source=source.size, n_target=target.size, alpha=alpha)

    source_hits = (source >= lo) & (source <= hi)
    target_hits = (target >= lo) & (target <= hi)
    source_cov = source_hits.mean()
    target_cov = target_hits.mean()
    ctr = min(source_cov, target_cov) / max(source_cov, target_cov) if max(source_cov, target_cov) > eps else 0.0

    return CTRResult(
        ctr=float(ctr),
        source_coverage=float(source_cov),
        target_coverage=float(target_cov),
        nominal_coverage=1 - alpha,
        n_source=source.size,
        n_target=target.size,
        alpha=alpha,
    )


class TVFValidator:
    """
    Реалізація Transferability Validation Framework (TVF) 2.0.
    Перевіряє, чи можна перенести існуючу модель на новий домен даних.
    """
    def __init__(self, ctr_threshold=0.8, dcts_threshold=0.7, delta_xi_threshold=0.1, delta_h_threshold=0.05):
        self.ctr_threshold = ctr_threshold
        self.dcts_threshold = dcts_threshold
        self.delta_xi_threshold = delta_xi_threshold
        self.delta_h_threshold = delta_h_threshold

    def _calculate_ctr(self, new_domain_data, model):
        """Реальний CTR на основі модельних резидуалів.

        Очікуємо, що model має метод predict(y) або схожий; для спрощення припускаємо
        що `new_domain_data` - масив фактичних y, а model.predict повертає y_hat того ж розміру.
        Тут ми НЕ маємо доступу до source_residuals, тому повертаємо псевдо-CTR
        і залишаємо інтеграцію в зовнішній пайплайн ( де буде виклик compute_ctr ).
        """
        print("[INFO] TVF: Calculating CTR (placeholder using random until integrated externally)...")
        return np.random.uniform(0.7, 0.9)

    def _calculate_dcts(self, new_domain_data, source_domain_data):
        """ЗАГЛУШКА: Розрахунок Distributional Consistency Test Score (DCTS)."""
        # У реальності тут буде статистичний тест (напр., KS-тест) на схожість розподілів.
        print("[INFO] TVF: Calculating DCTS...")
        return np.random.uniform(0.6, 0.8)

    def _calculate_delta_invariants(self, new_domain_data, source_domain_invariants):
        """
        ЗАГЛУШКА: Розрахунок зміни інваріантів (хвіст та пам'ять).
        :param source_domain_invariants: Словник {'xi': float, 'H': float} з оригінального домену.
        """
        # У реальності тут буде оцінка параметрів xi та H на нових даних.
        print("[INFO] TVF: Calculating invariant deltas...")
        new_xi = source_domain_invariants['xi'] + np.random.uniform(-0.15, 0.15)
        new_H = source_domain_invariants['H'] + np.random.uniform(-0.08, 0.08)
        
        delta_xi = np.abs(new_xi - source_domain_invariants['xi'])
        delta_h = np.abs(new_H - source_domain_invariants['H'])
        return delta_xi, delta_h

    def validate_domain(self, new_domain_data, source_domain_data, source_domain_invariants, model):
        """
        Запускає повну перевірку переносимості на новий домен.
        
        :return: 'READY' або 'NOT_READY'
        """
        print("--- Running TVF 2.0 Validation ---")
        
        # 1. Розраховуємо метрики переносимості
        ctr = self._calculate_ctr(new_domain_data, model)
        dcts = self._calculate_dcts(new_domain_data, source_domain_data)
        delta_xi, delta_h = self._calculate_delta_invariants(new_domain_data, source_domain_invariants)

        print(f"Calculated metrics: CTR={ctr:.2f}, DCTS={dcts:.2f}, |Δξ|={delta_xi:.3f}, |ΔH|={delta_h:.3f}")
        print(f"Thresholds:       CTR>={self.ctr_threshold}, DCTS>={self.dcts_threshold}, |Δξ|<{self.delta_xi_threshold}, |ΔH|<{self.delta_h_threshold}")

        # 2. Перевіряємо умови згідно з концепцією (розділ 6)
        is_ready = (
            ctr >= self.ctr_threshold and
            dcts >= self.dcts_threshold and
            delta_xi < self.delta_xi_threshold and
            delta_h < self.delta_h_threshold
        )

        if is_ready:
            print("[PASS] Domain is READY for transfer.")
            return "READY"
        else:
            print("[FAIL] Domain is NOT READY. Recommend conservative mode.")
            return "NOT_READY"