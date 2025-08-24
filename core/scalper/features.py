from __future__ import annotations

"""
COPILOT_PROMPT:
Implement trade flow aggregation for Binance trades.
- isBuyerMaker=True => SELL aggressor; False => BUY.
- Support simple normalized TFI in [-1, 1].
- Provide helper to return debug volumes too.
- Add docstrings and type hints.
"""

from dataclasses import dataclass
from typing import Iterable, Mapping, Tuple

import numpy as np


@dataclass(frozen=True)
class TFIDebug:
    v_mkt_buy: float
    v_mkt_sell: float
    tfi: float


def tfi_from_binance_trades(trades: Iterable[Mapping[str, object]]) -> TFIDebug:
    """Compute normalized Trade Flow Imbalance (TFI) for Binance semantics.

    Binance trade field semantics:
    - isBuyerMaker == True  -> market SELL aggressor (taker was seller)
    - isBuyerMaker == False -> market BUY  aggressor (taker was buyer)

    TFI is defined as (V_buy - V_sell) / (V_buy + V_sell), clipped to [-1, 1].

    Parameters
    ----------
    trades : Iterable[Mapping[str, object]]
        Sequence of trade dict-like objects with keys: 'price', 'size', 'isBuyerMaker'.

    Returns
    -------
    TFIDebug
        Volumes and the normalized TFI value.
    """
    v_buy = 0.0
    v_sell = 0.0
    for t in trades:
        raw_size = t.get("size", 0.0)
        try:
            size = float(str(raw_size)) if raw_size is not None else 0.0
        except Exception:
            size = 0.0
        flag = t.get("isBuyerMaker", None)
        # True  -> SELL (aggressor sells)
        # False -> BUY  (aggressor buys)
        if flag is True:
            v_sell += size
        elif flag is False:
            v_buy += size
        else:
            # Unknown flag -> ignore
            continue

    denom = v_buy + v_sell
    if denom <= 0:
        tfi = 0.0
    else:
        tfi = (v_buy - v_sell) / denom
        tfi = float(np.clip(tfi, -1.0, 1.0))
    return TFIDebug(v_mkt_buy=v_buy, v_mkt_sell=v_sell, tfi=tfi)
