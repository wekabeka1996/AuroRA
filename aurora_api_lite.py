#!/usr/bin/env python3
"""
Aurora API Lite - Спрощений API для тестування інтеграції з WiseScalp
"""

import json
import time
import asyncio
from fastapi import FastAPI, HTTPException
import uvicorn

# --- Створюємо FastAPI ---
app = FastAPI(
    title="Aurora API Lite",
    version="1.0.0",
    description="Спрощений API для тестування інтеграції з WiseScalp"
)

# --- Ендпоінти ---

@app.get("/health")
async def health():
    """Простий health check"""
    return {"status": "healthy", "timestamp": time.time()}

@app.get("/healthz")  
async def healthz():
    """Kubernetes style health check"""
    return {"status": "ok"}

@app.post("/pretrade/check")
async def pretrade_check(request: dict):
    """
    Перевірка можливості виконання торгової операції
    Формат сумісний з WiseScalp AuroraGate
    """
    # Симуляція обробки (не блокуємо event loop)
    await asyncio.sleep(0.001)
    
    order = request.get("order", {})
    market = request.get("market", {})
    account = request.get("account", {})
    
    symbol = (market or {}).get("symbol") or (request.get("order") or {}).get("symbol") or "UNKNOWN"
    qty = order.get("qty", 0)
    side = order.get("side", "buy")
    
    # Базова валідація
    if qty <= 0:
        return {
            "allow": False,
            "max_qty": 0,
            "risk_scale": 0.0,
            "cooldown_ms": 1000,
            "reason": "Invalid quantity",
            "hard_gate": True,
            "quotas": {"trades_pm_left": 999, "symbol_exposure_left_usdt": 1e12},
            "observability": {
                "gate_state": "BLOCK",
                "confidence": 0.0,
                "regime": 1,
                "latency_ms": 1.2,
                "reasons": ["invalid_qty"],
            }
        }
    
    # Симуляція Aurora логіки
    confidence = 0.85
    regime = 2
    
    # Симуляція обмежень
    if "BTC" in symbol and qty > 0.1:
        return {
            "allow": False,
            "max_qty": 0.1,
            "risk_scale": 0.0,
            "cooldown_ms": 5000,
            "reason": "Position limit exceeded for BTC",
            "hard_gate": False,
            "quotas": {"trades_pm_left": 999, "symbol_exposure_left_usdt": 1e12},
            "observability": {
                "gate_state": "BLOCK",
                "confidence": 0.4,
                "regime": 3,
                "latency_ms": 1.8,
                "reasons": ["pos_limit"],
            }
        }
    
    # Дозволити операцію
    return {
        "allow": True,
        "max_qty": qty,
        "risk_scale": 1.0,
        "cooldown_ms": 0,
        "reason": "Trade approved by Aurora",
        "hard_gate": False,
        "quotas": {"trades_pm_left": 998, "symbol_exposure_left_usdt": 1e12},
        "observability": {
            "gate_state": "PASS",
            "confidence": confidence,
            "regime": regime,
            "latency_ms": 0.8,
            "reasons": [],
        }
    }

@app.post("/posttrade/log")
async def posttrade_log(request: dict):
    """
    Логування виконаної торгової операції
    Формат сумісний з WiseScalp AuroraGate
    """
    # Симуляція збереження в базу/файл
    trade_log = {
        "timestamp": time.time(),
        "request": request
    }
    
    print(f"[TRADE LOG] {json.dumps(trade_log, indent=2)}")
    
    return {
        "status": "logged",
        "trade_id": f"tr_{int(time.time()*1000)}",
        "timestamp": trade_log["timestamp"]
    }

@app.get("/version")
async def version():
    """Версія API"""
    return {
        "version": "1.0.0",
        "mode": "lite",
        "description": "Aurora API Lite for WiseScalp integration testing"
    }

if __name__ == "__main__":
    print("🚀 Starting Aurora API Lite...")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )