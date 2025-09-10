
from collections import deque

import numpy as np
import torch


class BCCTracker:
    """Простий трекер емпіричного покриття для оцінки калібрування (BCC)."""

    def __init__(self, window: int = 200):
        self.hits = deque(maxlen=window)

    def update(self, lower_bound: float, upper_bound: float, y_true: float):
        hit = (y_true >= lower_bound) and (y_true <= upper_bound)
        self.hits.append(1 if hit else 0)

    def get_score(self) -> float:
        if not self.hits:
            return 0.5
        return float(np.mean(list(self.hits)))


class UncertaintyMetrics:
    """Обчислення kappa та kappa+ з глобальним масштабуванням (kappa_scale)."""

    def __init__(self, gamma: float = 0.7, kappa_scale: float = 1.0, **kwargs):
        self.gamma = gamma
        self.kappa_scale = float(kappa_scale) if kappa_scale is not None else 1.0
        self._extra = kwargs  # зберігаємо невикористані параметри для дебагу
        self.bcc_tracker = BCCTracker()

    def compute_kappa(self, z, router_probs, pi_width: float, posterior: dict):
        # 1. Невизначеність стану
        state_u = torch.std(z).item()
        # 2. Ентропія режимів (модельна невизначеність)
        model_u = -torch.sum(router_probs * torch.log(router_probs + 1e-9)).item()
        # 3. Невизначеність прогнозу
        sigma = posterior.get('sigma', 1.0)
        forecast_u = pi_width / (sigma + 1e-9)
        kappa = 0.4 * state_u + 0.3 * model_u + 0.3 * forecast_u
        kappa *= self.kappa_scale
        return float(np.clip(kappa, 0, 1))

    def compute_kappa_plus(self, kappa: float, lower: float, upper: float, y_true=None):
        if y_true is not None:
            self.bcc_tracker.update(lower, upper, y_true)
        bcc_score = self.bcc_tracker.get_score()
        kappa_plus = self.gamma * kappa + (1 - self.gamma) * (1 - bcc_score)
        return float(np.clip(kappa_plus, 0, 1))
