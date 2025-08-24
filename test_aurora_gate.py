#!/usr/bin/env python3
"""
Тестування AuroraGate з новим форматом API
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'skalp_bot'))

from skalp_bot.integrations.aurora_gate import AuroraGate

def test_aurora_gate():
    """Тестуємо AuroraGate з Aurora API Lite"""
    print("🧪 Тестування AuroraGate з Aurora API Lite")
    print("=" * 50)
    
    # Ініціалізуємо Aurora Gate
    aurora = AuroraGate(base_url="http://127.0.0.1:8000", mode="shadow", timeout_s=1.0)
    
    # Тест 1: Валідна операція
    print("\n1️⃣ Тест: Валідна BTC операція")
    account = {"user_id": "test_user", "balance_usdt": 1000.0}
    order = {"side": "buy", "qty": 0.05, "price": 50000.0}
    market = {"symbol": "BTC/USDT", "min_qty": 0.001}
    
    result = aurora.check(account, order, market)
    print(f"   Результат: {result}")
    
    # Тест 2: Великий розмір позиції
    print("\n2️⃣ Тест: BTC операція з великим розміром")
    order_large = {"side": "buy", "qty": 0.2, "price": 50000.0}
    
    result = aurora.check(account, order_large, market)
    print(f"   Результат: {result}")
    
    # Тест 3: Невалідний розмір
    print("\n3️⃣ Тест: Невалідний розмір позиції")
    order_invalid = {"side": "sell", "qty": -0.1, "price": 50000.0}
    
    result = aurora.check(account, order_invalid, market)
    print(f"   Результат: {result}")
    
    # Тест 4: Post-trade логування
    print("\n4️⃣ Тест: Post-trade логування")
    trade_data = {
        "symbol": "BTC/USDT",
        "side": "buy",
        "qty": 0.05,
        "price": 50000.0,
        "executed_qty": 0.05,
        "executed_price": 50001.5,
        "commission": 0.25,
        "timestamp": 1755997839000
    }
    
    logged = aurora.posttrade(**trade_data)
    print(f"   Логування успішне: {logged}")
    
    print("\n✅ Тестування AuroraGate завершено!")

if __name__ == "__main__":
    test_aurora_gate()