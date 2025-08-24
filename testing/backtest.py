
import pandas as pd
import numpy as np
from tqdm import tqdm

# Припускаємо, що TradingSystem знаходиться в trading.main_loop
from trading.main_loop import TradingSystem

class Backtester:
    """
    Клас для проведення бектестування торгової системи на історичних даних.
    """
    def __init__(self, system: TradingSystem, historical_data: pd.DataFrame):
        """
        :param system: Екземпляр TradingSystem.
        :param historical_data: DataFrame з історичними даними (OHLCV та фічами).
        """
        self.system = system
        self.data = historical_data
        self.results = {
            'returns': [],
            'positions': [],
            'metrics': [],
            'coverage': []
        }

    def _calculate_pnl(self, prev_weights, new_weights, price_change_vector):
        """
        Розраховує прибуток/збиток (PnL) від перебалансування.
        :param prev_weights: Попередні ваги портфеля.
        :param new_weights: Нові ваги портфеля.
        :param price_change_vector: Вектор зміни цін активів.
        :return: Скалярне значення PnL.
        """
        # Проста модель: PnL = ваги_попереднього_кроку * зміна_ціни
        # Ігноруємо транзакційні витрати для простоти
        if prev_weights is None:
            return 0
        
        return np.sum(prev_weights * price_change_vector)

    def run(self):
        """Запускає повний цикл бектестування."""
        print("--- Starting Backtest ---")
        
        # Ітеруємо по всіх часових кроках у даних
        for i in tqdm(range(1, len(self.data))):
            # Дані до поточного моменту (для прогнозу)
            market_data_at_t = self.data.iloc[i-1]
            
            # 1. Отримуємо прогноз та рішення від системи
            pred = self.system.predict(market_data_at_t)
            new_weights = pred['weights']
            
            # 2. Розраховуємо PnL
            # Вектор зміни цін: (ціна_зараз - ціна_вчора) / ціна_вчора
            # Припускаємо, що 'close' - це вектор цін для всіх активів
            # У нашому випадку система працює з одним активом, тому це просто число
            price_t = self.data.iloc[i]['close']
            price_t_minus_1 = self.data.iloc[i-1]['close']
            price_change = (price_t - price_t_minus_1) / price_t_minus_1
            
            prev_weights = self.results['positions'][-1] if self.results['positions'] else None
            # Для одного активу вага = 1, тому PnL = зміна ціни
            # У реальному портфелі тут буде векторна операція
            pnl = self._calculate_pnl(prev_weights, new_weights, price_change)
            self.results['returns'].append(pnl)
            
            # 3. Зберігаємо результати кроку
            self.results['positions'].append(new_weights)
            self.results['metrics'].append(pred)
            
            # 4. Перевіряємо покриття довірчого інтервалу
            in_interval = pred['interval'][0] <= price_t <= pred['interval'][1]
            self.results['coverage'].append(in_interval)

        print("--- Backtest Finished ---")
        return self.compute_statistics()

    def max_drawdown(self, returns):
        """Розраховує максимальну просадку."""
        cumulative_returns = (1 + returns).cumprod()
        peak = cumulative_returns.expanding(min_periods=1).max()
        drawdown = (cumulative_returns - peak) / peak
        return drawdown.min()

    def compute_statistics(self):
        """Розраховує фінальну статистику бектесту."""
        returns = np.array(self.results['returns'])
        
        # Переконуємось, що є дані для розрахунку
        if len(returns) < 2:
            return {"error": "Not enough data for statistics"}

        # Кількість торгових періодів на рік (для денних даних ~252)
        trading_days_per_year = 252
        
        # Розрахунок метрик згідно з планом
        sharpe_ratio = np.sqrt(trading_days_per_year) * returns.mean() / (returns.std() + 1e-9)
        
        negative_returns = returns[returns < 0]
        sortino_std = negative_returns.std() if len(negative_returns) > 0 else 1e-9
        sortino_ratio = np.sqrt(trading_days_per_year) * returns.mean() / (sortino_std + 1e-9)
        
        max_dd = self.max_drawdown(pd.Series(returns))
        
        cvar_95 = np.mean(returns[returns < np.percentile(returns, 5)])
        
        coverage = np.mean(self.results['coverage'])
        avg_latency = np.mean([m['latency_ms'] for m in self.results['metrics']])

        stats = {
            'sharpe_ratio': sharpe_ratio,
            'sortino_ratio': sortino_ratio,
            'max_drawdown': max_dd,
            'cvar_95': cvar_95,
            'coverage_rate': coverage,
            'avg_latency_ms': avg_latency,
            'total_return': np.expm1(np.log(1 + returns).sum())
        }
        
        print("--- Backtest Statistics ---")
        for key, value in stats.items():
            print(f"{key:<20}: {value:.4f}")
        print("-------------------------")
        
        return stats
''