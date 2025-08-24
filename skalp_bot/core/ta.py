from __future__ import annotations
from typing import List, Optional, Tuple

def atr_wilder(high: List[float] | float, low: List[float] | float, close: List[float] | float,
               period: int = 14,
               prev_atr: Optional[float] = None,
               prev_close: Optional[float] = None) -> Optional[float]:
    """
    Wilder ATR (Average True Range)
    Modes:
      - batch: pass lists of high/low/close with len>=period+1 -> returns last ATR
      - streaming: pass scalar high/low/close for the latest bar and prev_atr & prev_close -> returns updated ATR
    TR_t = max(high-low, abs(high-prev_close), abs(low-prev_close))
    ATR_t = ATR_{t-1} + (TR_t - ATR_{t-1})/period
    """
    # Batch mode
    if isinstance(high, list) and isinstance(low, list) and isinstance(close, list):
        n = len(close)
        if n < period + 1:
            return None
        # Seed ATR as average TR over first 'period' bars (1..period)
        seed_tr_sum = 0.0
        for i in range(1, period + 1):
            h, l, c_prev = float(high[i]), float(low[i]), float(close[i - 1])
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            seed_tr_sum += tr
        atr = seed_tr_sum / period
        # Smooth for the rest
        for i in range(period + 1, n):
            h, l, c_prev = float(high[i]), float(low[i]), float(close[i - 1])
            tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
            atr = atr + (tr - atr) / period
        return float(atr)

    # Streaming mode
    try:
        h = float(high)  # type: ignore[arg-type]
        l = float(low)   # type: ignore[arg-type]
        c_prev = float(prev_close) if prev_close is not None else None  # type: ignore[assignment]
    except Exception:
        return None
    if prev_atr is None or c_prev is None:
        return None
    tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
    atr = prev_atr + (tr - prev_atr) / float(period)
    return float(atr)
