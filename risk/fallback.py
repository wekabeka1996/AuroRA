

class FallbackController:
    """
    Контролер для реалізації Kill-switch механізмів та захисних протоколів.
    """
    def __init__(self, config):
        """
        Ініціалізує контролер з пороговими значеннями з конфігурації.
        """
        self.triggers_config = config.get('fallback_triggers', {})
        # Приклад конфігурації тригерів:
        # fallback_triggers:
        #   latency_ms: 150
        #   kappa_plus: 0.9
        #   coverage_rate: 0.8
        #   max_drawdown: 0.15

        # Визначаємо умови спрацювання
        self.triggers = {
            'latency': lambda m: m.get('latency_ms', 0) > self.triggers_config.get('latency_ms', 150),
            'kappa': lambda m: m.get('kappa_plus', 0) > self.triggers_config.get('kappa_plus', 0.9),
            'coverage': lambda m: m.get('coverage_rate', 1) < self.triggers_config.get('coverage_rate', 0.8),
            'drawdown': lambda m: m.get('drawdown', 0) > self.triggers_config.get('max_drawdown', 0.15)
        }

    # --- Захисні дії (заглушки) ---
    def _switch_to_simple_model(self):
        print("[FALLBACK] ACTION: Switching to a simple, more robust model.")
        # Тут може бути логіка переключення на, наприклад, просту ковзну середню
        return {"action": "switch_to_simple_model", "status": "executed"}

    def _reduce_position_size(self, reduction_factor=0.5):
        print(f"[FALLBACK] ACTION: Reducing all position sizes by {reduction_factor*100}%.")
        # Ця дія модифікує ваги, що повертаються з DRO-ES
        return {"action": "reduce_position_size", "factor": reduction_factor, "status": "executed"}

    def _widen_intervals(self, widening_factor=1.2):
        print(f"[FALLBACK] ACTION: Widening all prediction intervals by {widening_factor*100}%.")
        # Ця дія модифікує `q` або `sigma_hat` в ICP
        return {"action": "widen_intervals", "factor": widening_factor, "status": "executed"}

    def _emergency_close_positions(self):
        print("[FALLBACK] ACTION: EMERGENCY! Closing all positions immediately.")
        # Ця дія надсилає сигнал на повний вихід з ринку
        return {"action": "emergency_close_positions", "status": "executed"}

    def execute_fallback(self, trigger_name):
        """Виконує відповідну дію на основі імені тригера."""
        # Маппінг тригерів на дії
        actions = {
            'latency': self._switch_to_simple_model,
            'kappa': self._reduce_position_size,
            'coverage': self._widen_intervals,
            'drawdown': self._emergency_close_positions
        }

        action_func = actions.get(trigger_name)
        if action_func:
            return action_func()
        else:
            print(f"[WARN] No fallback action defined for trigger: {trigger_name}")
            return None

    def check_triggers(self, metrics):
        """
        Перевіряє всі тригери на основі поточних метрик системи.
        
        :param metrics: Словник з поточними метриками (напр., {'latency_ms': 120, 'kappa_plus': 0.8, ...})
        :return: Результат виконання захисної дії, якщо тригер спрацював, інакше None.
        """
        print(f"[INFO] Fallback controller checking metrics: {metrics}")
        for name, condition in self.triggers.items():
            if condition(metrics):
                print(f"[ALERT] Fallback trigger '{name}' activated!")
                return self.execute_fallback(name)

        return None # Жоден тригер не спрацював
''
