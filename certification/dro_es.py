"""Distributionally Robust Optimization for Expected Shortfall (DRO-ES).

Graceful fallback: Якщо `cvxpy` не встановлено (наприклад, у легких тестових середовищах
або CI без solver'ів) – ми використовуємо деградований режим, що повертає рівномірні
ваги та позначає objective значенням np.inf. Це дозволяє тестам, які не валідують
якість оптимізації, проходити без важкої залежності.
"""

import numpy as np
try:  # pragma: no cover - шлях установки залежності змінний
    import cvxpy as cp  # type: ignore
except Exception:  # pragma: no cover
    cp = None  # Fallback режим

class DRO_ES:
    """Спрощена реалізація DRO-ES з підтримкою зайвих параметрів у конфігах.

    Параметри на кшталт `lambda_reg` (історичний) безпечно ігноруються для зворотної
    сумісності з існуючими YAML конфігами.
    """
    def __init__(self, alpha: float = 0.05, eps_base: float = 0.1, **kwargs):  # kwargs swallow legacy keys
        self.alpha = alpha
        self.eps_base = eps_base
        self._extra = kwargs  # зберігаємо для дебагу

    def _is_transition(self, regime_z):
        """ЗАГЛУШКА: Визначає перехідний режим."""
        return False

    def _compute_eps(self, regime_z, aci):
        """
        Розраховує динамічний радіус `eps` для кулі Вассерштейна.
        Більший радіус означає більшу невизначеність та більш консервативну політику.
        """
        eps = self.eps_base
        if self._is_transition(regime_z):
            eps *= 1.5 # Збільшуємо невизначеність у перехідних режимах
        
        # Збільшуємо невизначеність при високому ACI
        eps *= (1 + 0.2 * min(aci, 2.0))
        return eps

    def optimize(self, scenarios, regime_z, aci):
        """
        Вирішує задачу DRO-ES для знаходження оптимальних ваг портфеля.
        
        :param scenarios: np.array (n_scenarios, d_assets) - матриця можливих сценаріїв прибутків.
        :param regime_z: Латентний вектор поточного режиму.
        :param aci: Поточне значення ACI.
        :return: (оптимальні ваги, очікуваний ES)
        """
        n_scenarios, d_assets = scenarios.shape

        # Якщо немає cvxpy – fallback
        if cp is None:
            return np.ones(d_assets) / d_assets, np.inf

        # 1. Динамічно обчислюємо радіус невизначеності `eps`
        eps = self._compute_eps(regime_z, aci)

        # 2. Створюємо змінні для оптимізації в CVXPY
        try:
            w = cp.Variable(d_assets)  # Ваги портфеля
            t = cp.Variable()          # VaR proxy
            xi = cp.Variable(n_scenarios, nonneg=True)  # Excess losses
        except Exception as e:  # pragma: no cover
            print(f"[WARN] cvxpy variable creation failed: {e}")
            return np.ones(d_assets) / d_assets, np.inf

        # 3. Втрати портфеля
        loss = -scenarios @ w

        # 4. Обмеження
        constraints = [
            xi >= loss - t,
            cp.norm(w, 2) <= 1,
            cp.sum(w) == 1,
            w >= -0.2,
            w <= 0.5,
        ]

        # 5. Цільова функція
        objective = cp.Minimize(
            t + (1 / (self.alpha * n_scenarios)) * cp.sum(xi) + eps * cp.norm(w, 2)
        )

        # 6. Розв'язання
        try:
            problem = cp.Problem(objective, constraints)
            problem.solve(solver=cp.ECOS, verbose=False)
            if problem.status in ("optimal", "optimal_inaccurate"):
                return w.value, float(problem.value)
            print(f"[WARN] DRO-ES optimization status: {problem.status}")
            return np.ones(d_assets) / d_assets, np.inf
        except Exception as e:
            print(f"[ERROR] DRO-ES optimization error: {e}")
            return np.ones(d_assets) / d_assets, np.inf