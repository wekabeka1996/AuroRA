from __future__ import annotations

from typing import Any, Dict, Optional

# API contracts
from api.models import AccountInfo, OrderInfo, MarketInfo
# Core schemas (downstream event/order structures)
from core.schemas import OrderDenied, OrderSuccess, OrderFailed


def api_order_to_denied_schema(
    *,
    decision_id: str,
    order: OrderInfo | Dict[str, Any],
    deny_reason: str,
    reasons: list[str] | None = None,
    observability: Dict[str, Any] | None = None,
) -> OrderDenied:
    """Map API pretrade 'order' + decision context -> core OrderDenied schema.

    Minimal safe mapping to keep logs consistent even if upstream fields are missing.
    """
    if not isinstance(order, dict):
        try:
            o = order.model_dump()  # type: ignore[attr-defined]
        except Exception:
            o = {}
    else:
        o = dict(order)

    symbol = str(o.get('symbol') or '')
    side = str(o.get('side') or '')
    qty = float(o.get('qty') or 0.0)

    # In pretrade denial there is no actual order_id yet, use decision_id as placeholder for correlation
    order_id = f"deny::{decision_id}"

    # Build gate_detail/snapshot
    gate_detail = {
        'reason': deny_reason,
        'reasons': list(reasons or []),
    }
    snapshot = dict(observability or {})

    return OrderDenied(
        ts_iso=snapshot.get('ts_iso') or '',
        decision_id=decision_id,
        order_id=order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        gate_code=deny_reason,
        gate_detail=gate_detail,
        snapshot=snapshot,
        reason_normalized='UNKNOWN',
    )


__all__ = [
    'api_order_to_denied_schema',
    'posttrade_to_success_schema',
    'posttrade_to_failed_schema',
]


def _get_ts_iso(snapshot: Dict[str, Any] | None) -> str:
    try:
        v = (snapshot or {}).get('ts_iso')
        return str(v) if v is not None else ''
    except Exception:
        return ''


def posttrade_to_success_schema(
    payload: Dict[str, Any],
    *,
    decision_id: str | None = None,
    snapshot: Dict[str, Any] | None = None,
) -> OrderSuccess:
    """Map a posttrade success payload into core OrderSuccess schema.
    decision_id may be unknown; pass None and keep it empty for now.
    """
    d = dict(payload or {})
    return OrderSuccess(
        ts_iso=_get_ts_iso(snapshot),
        decision_id=decision_id or '',
        order_id=str(d.get('order_id') or d.get('id') or ''),
        symbol=str(d.get('symbol') or ''),
        side=str(d.get('side') or ''),
        qty=float(d.get('qty') or d.get('amount') or 0.0),
        avg_price=float(d.get('average') or d.get('avg_price') or d.get('price') or 0.0),
        fees=float((d.get('fee') or 0.0) if not isinstance(d.get('fee'), dict) else (d.get('fee') or {}).get('cost') or 0.0),
        filled_pct=float(d.get('filled_pct') or 1.0 if float(d.get('filled') or 0.0) > 0 else 0.0),
        exchange_ts=(d.get('exchange_ts') or None),
        client_order_id=d.get('client_order_id') or d.get('clientOrderId') or None,
        exchange_order_id=d.get('exchange_order_id') or d.get('orderId') or None,
    )


def posttrade_to_failed_schema(
    payload: Dict[str, Any],
    *,
    decision_id: str | None = None,
    snapshot: Dict[str, Any] | None = None,
) -> OrderFailed:
    """Map a posttrade failure payload into core OrderFailed schema."""
    d = dict(payload or {})
    return OrderFailed(
        ts_iso=_get_ts_iso(snapshot),
        decision_id=decision_id or '',
        order_id=str(d.get('order_id') or d.get('id') or ''),
        symbol=str(d.get('symbol') or ''),
        side=str(d.get('side') or ''),
        qty=float(d.get('qty') or d.get('amount') or 0.0),
        error_code=str(d.get('error_code') or ''),
        error_msg=str(d.get('error_msg') or d.get('reason_detail') or ''),
        attempts=int(d.get('attempts') or 1),
        final_status=str(d.get('status') or d.get('final_status') or ''),
        client_order_id=d.get('client_order_id') or d.get('clientOrderId') or None,
        exchange_order_id=d.get('exchange_order_id') or d.get('orderId') or None,
    )
