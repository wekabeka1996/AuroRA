# Execution Map: Signal → Risk → OMS → Біржа

## Огляд
Цей документ описує карту викликів від джерела сигналу до реального запиту на біржу та назад (callbacks/fills). Включає всі знайдені точки виклику, їх сигнатури, вхід/вихід, side-effects та виклики logger/XAI.

## Знайдені точки виклику

### 1. place_order
- **Файл:рядки**: `skalp_bot/exch/ccxt_binance.py:296-350`
- **Сигнатура**: `def place_order(side: Literal["buy", "sell"], qty: float, price: float | None = None, *, reduce_only: bool = False)`
- **Вхід**: side, qty, price (optional), reduce_only
- **Вихід**: dict з order info (id, status, etc.)
- **Side-effects**: Відправляє запит на біржу через ccxt.create_order, квантизує qty/price, перевіряє ліміти (minQty, minCost)
- **Виклики logger/XAI**: Немає прямо, але через ccxt (якщо помилка, exception)

### 2. create_order
- **Файл:рядки**: `skalp_bot/exch/ccxt_binance.py:350`
- **Сигнатура**: `self.ex.create_order(self.symbol, order_type, side, qty_q, price_q, params)`
- **Вхід**: symbol, order_type, side, qty_q, price_q, params
- **Вихід**: order response від ccxt
- **Side-effects**: Реальний запит на біржу
- **Виклики logger/XAI**: Через ccxt, немає Aurora logger

### 3. close_position
- **Файл:рядки**: `skalp_bot/exch/ccxt_binance.py:352-358`
- **Сигнатура**: `def close_position(side_current: Literal["LONG", "SHORT"], qty: float)`
- **Вхід**: side_current, qty
- **Вихід**: результат place_order
- **Side-effects**: Викликає place_order з reduce_only=True
- **Виклики logger/XAI**: Немає

### 4. cancel_all
- **Файл:рядки**: `skalp_bot/exch/ccxt_binance.py:360-366`
- **Сигнатура**: `def cancel_all()`
- **Вхід**: немає
- **Вихід**: результат cancel_all_orders або False
- **Side-effects**: Скасовує всі ордери на символі
- **Виклики logger/XAI**: Немає

### 5. ORDER.SUBMIT
- **Файл:рядки**: `skalp_bot/runner/run_live_aurora.py:466,537`
- **Сигнатура**: `_log_events("ORDER.SUBMIT", {...})`
- **Вхід**: event_code, payload
- **Вихід**: логування у aurora_events.jsonl
- **Side-effects**: Запис події
- **Виклики logger/XAI**: AuroraEventLogger

### 6. ORDER.ACK
- **Файл:рядки**: `skalp_bot/runner/run_live_aurora.py:490,502,537`
- **Сигнатура**: `_log_events("ORDER.ACK", {...})`
- **Вхід**: event_code, payload
- **Вихід**: логування у aurora_events.jsonl
- **Side-effects**: Запис події
- **Виклики logger/XAI**: AuroraEventLogger

### 7. ORDER.REJECT
- **Файл:рядки**: `skalp_bot/runner/run_live_aurora.py:510,550`
- **Сигнатура**: `_log_events("ORDER.REJECT", {...})`
- **Вхід**: event_code, payload
- **Вихід**: логування у aurora_events.jsonl
- **Side-effects**: Запис події
- **Виклики logger/XAI**: AuroraEventLogger

### 8. ORDER.CANCEL.REQUEST
- **Файл:рядки**: `skalp_bot/runner/run_live_aurora.py:525`
- **Сигнатура**: `_log_events("ORDER.CANCEL.REQUEST", {...})`
- **Вхід**: event_code, payload
- **Вихід**: логування у aurora_events.jsonl
- **Side-effects**: Запис події
- **Виклики logger/XAI**: AuroraEventLogger

### 9. ORDER.CANCEL.ACK
- **Файл:рядки**: `skalp_bot/runner/run_live_aurora.py:527`
- **Сигнатура**: `_log_events("ORDER.CANCEL.ACK", {...})`
- **Вхід**: event_code, payload
- **Вихід**: логування у aurora_events.jsonl
- **Side-effects**: Запис події
- **Виклики logger/XAI**: AuroraEventLogger

### 10. _reconcile_flow
- **Файл:рядки**: `tests/e2e/test_trade_flow_simulator.py:235-317`
- **Сигнатура**: `def _reconcile_flow(self, flow_id: str, signal: Dict[str, Any], execution_result, pnl_result)`
- **Вхід**: flow_id, signal, execution_result, pnl_result
- **Вихід**: reconciliation dict
- **Side-effects**: Логує FLOW.RECONCILED
- **Виклики logger/XAI**: xai_logger.emit

### 11. _update_position
- **Файл:рядки**: `tests/e2e/test_trade_flow_simulator.py:89-116`
- **Сигнатура**: `def _update_position(self, order, execution_result)`
- **Вхід**: order, execution_result
- **Вихід**: position dict
- **Side-effects**: Оновлює позицію на основі fill
- **Виклики logger/XAI**: Немає прямо

## Послідовність викликів
1. Signal Generation (compute_alpha_score)
2. Risk Check (AuroraGate.check)
3. Idempotency Check (idem.seen)
4. Route Decision (Router.decide)
5. ORDER.SUBMIT
6. place_order
7. create_order (via CCXT)
8. Біржа
9. ORDER.ACK
10. ORDER.FILL (якщо fill)
11. Position Update

Дивіться діаграми у `docs/diagrams/` для візуалізації сценаріїв.