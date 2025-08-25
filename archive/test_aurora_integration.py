#!/usr/bin/env python3
"""
Тестування інтеграції WiseScalp з Aurora API
Симуляція Aurora Gate без реального сервера
"""

import json
import time
from typing import Dict, Any

class AuroraGateSimulator:
    """Симулятор Aurora Gate для тестування інтеграції"""
    
    def __init__(self):
        self.call_count = 0
        
    def pretrade_check(self, symbol: str, side: str, amount: float, price: float) -> Dict[str, Any]:
        """Симуляція претрейд перевірки"""
        self.call_count += 1
        
        # Симуляція Aurora logic
        if amount <= 0:
            return {
                "allowed": False,
                "reason": "Invalid amount",
                "confidence": 0.0,
                "regime": 1,
                "latency_ms": 0.5
            }
        
        # Симуляція обмежень для великих позицій
        if symbol.startswith("BTC") and amount > 0.1:
            return {
                "allowed": False,
                "reason": "Position limit exceeded for BTC",
                "confidence": 0.4,
                "regime": 3,
                "latency_ms": 1.2
            }
        
        # Нормальний випадок - дозволити
        return {
            "allowed": True,
            "reason": "Trade approved by Aurora",
            "confidence": 0.87,
            "regime": 2,
            "latency_ms": 0.8
        }
    
    def posttrade_log(self, trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """Симуляція логування торгової операції"""
        trade_id = f"tr_{int(time.time()*1000)}_{self.call_count}"
        
        print(f"[AURORA LOG] Trade {trade_id}:")
        print(f"  Symbol: {trade_data.get('symbol')}")
        print(f"  Side: {trade_data.get('side')}")
        print(f"  Amount: {trade_data.get('amount')}")
        print(f"  Price: {trade_data.get('price')}")
        print(f"  Executed: {trade_data.get('executed_amount')} @ {trade_data.get('executed_price')}")
        
        return {
            "logged": True,
            "trade_id": trade_id,
            "timestamp": time.time()
        }

def test_wisescalp_aurora_integration():
    """Тестуємо інтеграцію WiseScalp з Aurora"""
    print("🧪 Тестування інтеграції WiseScalp з Aurora API")
    print("=" * 50)
    
    # Ініціалізуємо симулятор
    aurora = AuroraGateSimulator()
    
    # Тест 1: Валідна торгова операція
    print("\n1️⃣ Тест: Валідна BTC операція")
    result = aurora.pretrade_check("BTCUSDT", "buy", 0.05, 50000.0)
    print(f"   Результат: {result}")
    
    if result["allowed"]:
        # Симуляція виконання операції
        trade_data = {
            "symbol": "BTCUSDT",
            "side": "buy", 
            "amount": 0.05,
            "price": 50000.0,
            "executed_amount": 0.05,
            "executed_price": 50001.5,
            "commission": 0.25
        }
        log_result = aurora.posttrade_log(trade_data)
        print(f"   Логування: {log_result}")
    
    # Тест 2: Операція з перевищенням ліміту
    print("\n2️⃣ Тест: BTC операція з перевищенням ліміту")
    result = aurora.pretrade_check("BTCUSDT", "buy", 0.2, 50000.0)
    print(f"   Результат: {result}")
    
    # Тест 3: Невалідний розмір позиції
    print("\n3️⃣ Тест: Невалідний розмір позиції")
    result = aurora.pretrade_check("ETHUSDT", "sell", -0.1, 3000.0)
    print(f"   Результат: {result}")
    
    # Тест 4: Звичайна ETH операція
    print("\n4️⃣ Тест: Звичайна ETH операція")
    result = aurora.pretrade_check("ETHUSDT", "sell", 1.5, 3000.0)
    print(f"   Результат: {result}")
    
    if result["allowed"]:
        trade_data = {
            "symbol": "ETHUSDT",
            "side": "sell",
            "amount": 1.5,
            "price": 3000.0,
            "executed_amount": 1.5,
            "executed_price": 2999.2,
            "commission": 1.8
        }
        log_result = aurora.posttrade_log(trade_data)
        print(f"   Логування: {log_result}")
    
    print("\n✅ Тестування інтеграції завершено!")
    print(f"📊 Всього викликів Aurora: {aurora.call_count}")

if __name__ == "__main__":
    test_wisescalp_aurora_integration()