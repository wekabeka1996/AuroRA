
from collections import deque

import numpy as np
from scipy.stats import norm


class DynamicICP:
    """
    Реалізація Inductive Conformal Prediction (ICP) з динамічною alpha,
    як описано в розділі 4.1 та плані імплементації.
    """
    def __init__(self, alpha_base=0.1, window=1000, aci_influence=0.01, transition_influence=0.02):
        """
        Ініціалізація.
        :param alpha_base: Базовий рівень значущості.
        :param window: Розмір ковзного вікна для калібрувальних скорів.
        :param aci_influence: Вплив ACI на alpha.
        :param transition_influence: Вплив перехідного режиму на alpha.
        """
        self.alpha_base = alpha_base
        self.window = window
        self.aci_influence = aci_influence
        self.transition_influence = transition_influence

        # Використовуємо deque для ефективного зберігання останніх N скорів
        self.calibration_scores = deque(maxlen=window)

    def _detect_transition(self, z):
        """
        ЗАГЛУШКА: Визначає, чи є поточний стан перехідним.
        У реальній системі це буде складна логіка, що аналізує латентний простір z.
        """
        # Простий приклад: перехід, якщо норма z змінилась сильно
        # Потребує зберігання попереднього стану z
        return False # Поки що завжди повертаємо False

    def compute_alpha(self, z, aci):
        """
        Обчислює динамічну alpha згідно з концепцією.
        alpha(z, ACI) = clip(alpha_0 + alpha_1*1_{TRANS} + alpha_2*ACI_EMA, alpha_min, alpha_max)
        """
        is_transition = self._detect_transition(z)

        # Розрахунок alpha
        alpha = self.alpha_base
        if is_transition:
            alpha += self.transition_influence

        # Додаємо вплив ACI (ARMA Crossbar Index)
        # ACI - це метрика, що показує розбіжність між AR та ARMA моделями.
        # Високий ACI -> висока невизначеність -> більша alpha (ширший інтервал)
        alpha += self.aci_influence * min(aci, 1.0) # Обмежуємо вплив ACI

        # Обмежуємо alpha в розумних межах
        alpha_final = np.clip(alpha, 0.01, 0.25)
        return alpha_final

    def predict_interval(self, y_hat, sigma_hat, z, aci):
        """
        Обчислює довірчий інтервал для прогнозу.
        
        :param y_hat: Прогноз моделі (середнє).
        :param sigma_hat: Прогнозоване стандартне відхилення.
        :param z: Латентний вектор від DSSM.
        :param aci: Поточне значення ACI.
        :return: (lower_bound, upper_bound, dynamic_alpha)
        """
        # 1. Обчислюємо динамічну alpha
        dynamic_alpha = self.compute_alpha(z, aci)

        # 2. Обчислюємо квантиль з калібрувального набору
        # Якщо калібрувальний набір ще замалий, використовуємо Гауссівський квантиль
        if len(self.calibration_scores) < 50:
            q = norm.ppf(1 - dynamic_alpha / 2)
        else:
            # Quantile_{1-alpha} {s_i}
            q = np.quantile(list(self.calibration_scores), 1 - dynamic_alpha)

        # 3. Розраховуємо межі інтервалу
        # [y_hat +- q_alpha * sigma_hat]
        margin = q * sigma_hat
        lower_bound = y_hat - margin
        upper_bound = y_hat + margin

        return lower_bound, upper_bound, dynamic_alpha

    def update(self, y_true, y_hat, sigma_hat):
        """
        Оновлює набір калібрувальних скорів новим значенням.
        Скор розраховується як s_i = |y_i - y_hat_i| / sigma_hat_i
        """
        if sigma_hat > 1e-6: # Уникаємо ділення на нуль
            score = np.abs(y_true - y_hat) / sigma_hat
            self.calibration_scores.append(score)
