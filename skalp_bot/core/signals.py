from __future__ import annotations
from typing import List, Tuple, Dict, Optional
import numpy as np
from collections import deque
import time

def micro_price(best_bid: Tuple[float, float], best_ask: Tuple[float, float]) -> Optional[float]:
    """Return micro-price weighted by opposite queue sizes."""
    try:
        pb, vb = float(best_bid[0]), float(best_bid[1])
        pa, va = float(best_ask[0]), float(best_ask[1])
    except Exception:
        return None
    tot = vb + va
    if tot <= 0:
        return (pb + pa) / 2
    return (pb * va + pa * vb) / tot

def obi_from_l5(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]], levels: int = 5) -> Optional[float]:
    """Order Book Imbalance using sum of sizes over L1..Lk (price, size) lists.
    Clamped to [-1, 1] to avoid saturation artifacts when one side is ~0.
    """
    if not bids or not asks:
        return None
    bsum = sum(max(0.0, float(sz)) for _, sz in bids[:levels])
    asum = sum(max(0.0, float(sz)) for _, sz in asks[:levels])
    denom = bsum + asum
    if denom <= 0:
        return None
    obi = (bsum - asum) / denom
    # clamp to [-1, 1]
    if obi > 1.0:
        obi = 1.0
    elif obi < -1.0:
        obi = -1.0
    return float(obi)

def tfi_from_trades(trades: List[Dict], side_key="side", qty_key="qty",
                    ask_side="buy", bid_side="sell") -> Optional[float]:
    """Trade Flow Imbalance from recent trades stream.
    Prefer exchange aggressor flag when present: on Binance isBuyerMaker=True → aggressor is seller.
    Fallback to side field ('buy'/'sell').
    """
    buy_aggr = 0.0
    sell_aggr = 0.0
    for t in trades:
        q = float(t.get(qty_key, 0) or 0.0)
        # Prefer explicit maker flag to infer aggressor
        ibm = t.get('isBuyerMaker')
        if ibm is not None:
            if ibm is False:
                buy_aggr += q  # buyer was taker → aggressive buy
            elif ibm is True:
                sell_aggr += q  # seller was taker → aggressive sell
            continue
        # Fallback: side semantics
        side = t.get(side_key)
        if side == ask_side:
            buy_aggr += q
        elif side == bid_side:
            sell_aggr += q
    denom = buy_aggr + sell_aggr
    if denom <= 0:
        return None
    tfi = (buy_aggr - sell_aggr) / denom
    # clamp
    if tfi > 1.0:
        tfi = 1.0
    elif tfi < -1.0:
        tfi = -1.0
    return float(tfi)

def combine_alpha(obi: Optional[float], tfi: Optional[float], mp: Optional[float], mid: float, weights=(1.0, 1.0, 1.0)) -> float:
    """Combine OBI, TFI and micro-price deviation from mid into a scalar score."""
    w_obi, w_tfi, w_micro = weights
    parts = []
    if obi is not None:
        parts.append(w_obi * float(obi))
    if tfi is not None:
        parts.append(w_tfi * float(tfi))
    if mp is not None and np.isfinite(mid):
        parts.append(w_micro * float((mp - mid)))
    if not parts:
        return 0.0
    return float(np.tanh(np.sum(parts)))

# --- New metrics (WS-α-01) ---

def ofi_simplified(prev_bid: Tuple[float, float], prev_ask: Tuple[float, float],
                   bid: Tuple[float, float], ask: Tuple[float, float]) -> Optional[float]:
    """Simplified OFI around best quotes: added-removed at best bid/ask with tick direction.
    Returns value in [-1,1] approx (normalized by size sum).
    """
    try:
        pb, qb = map(float, prev_bid)
        pa, qa = map(float, prev_ask)
        b, qb2 = map(float, bid)
        a, qa2 = map(float, ask)
    except Exception:
        return None
    d_bid = (qb2 - qb) * (1 if b >= pb else -1)
    d_ask = (qa2 - qa) * (-1 if a <= pa else 1)
    denom = abs(qb) + abs(qa) + abs(qb2) + abs(qa2)
    if denom <= 0:
        return 0.0
    return float((d_bid + d_ask) / denom)

def absorption(trades: List[Dict], side: str = 'bid', window_s: float = 3.0,
               now_ts: Optional[float] = None) -> float:
    """Absorption proxy: market sells at bid or buys at ask without price move.
    Expect trade dicts contain ts (ms), side ('buy'/'sell'), and optionally price.
    Returns volume at the chosen side over recent window.
    """
    if now_ts is None:
        now_ts = time.time()
    cutoff_ms = (now_ts - window_s) * 1000.0
    tgt = 'sell' if side == 'bid' else 'buy'
    vol = 0.0
    for t in trades:
        ts = t.get('ts') or t.get('timestamp') or 0
        if ts and ts < cutoff_ms:
            continue
        if t.get('side') == tgt:
            vol += float(t.get('qty', 0.0) or 0.0)
    return float(vol)

def cancel_replenish_rate(events: List[Dict], window_s: float = 5.0,
                          now_ts: Optional[float] = None) -> float:
    """Cancel/Replenish ratio from LOB update events with type in {'add','cancel'}.
    This requires a feed of LOB events. If unavailable, return 0.0.
    """
    if not events:
        return 0.0
    if now_ts is None:
        now_ts = time.time()
    cutoff_ms = (now_ts - window_s) * 1000.0
    add_q = 0.0
    cancel_q = 0.0
    for e in events:
        ts = e.get('ts') or e.get('timestamp') or 0
        if ts and ts < cutoff_ms:
            continue
        q = float(e.get('qty', 0.0) or 0.0)
        if e.get('type') == 'add':
            add_q += q
        elif e.get('type') == 'cancel':
            cancel_q += q
    if add_q <= 0:
        return float('inf') if cancel_q > 0 else 0.0
    return float(cancel_q / add_q)

def sweep_score(trades: List[Dict], dt_ms: int = 100) -> float:
    """Estimate sweep by counting unique price levels crossed within a short burst.
    Without L2 deltas, approximate via price range span over the burst.
    """
    if not trades:
        return 0.0
    # Group recent trades in a burst window
    trades_sorted = sorted(trades, key=lambda t: t.get('ts') or t.get('timestamp') or 0)
    if not trades_sorted:
        return 0.0
    last_ts = trades_sorted[-1].get('ts') or trades_sorted[-1].get('timestamp') or 0
    burst = [t for t in trades_sorted if (t.get('ts') or t.get('timestamp') or 0) >= last_ts - dt_ms]
    prices = [float(t.get('price', 0.0) or 0.0) for t in burst]
    if not prices:
        return 0.0
    pmin, pmax = min(prices), max(prices)
    # Return span in ticks approximated by bps of mid of burst
    mid = (pmin + pmax) / 2.0 if (pmin and pmax) else (pmin + pmax + 1e-9) / 2.0
    return float(abs(pmax - pmin) / (mid if mid else 1.0))

def liquidity_ahead(depth: List[Tuple[float, float]], levels: int = 5) -> float:
    """Average depth ahead on a side (e.g., asks for longs). Provide list of (price, size)."""
    if not depth:
        return 0.0
    d = [max(0.0, float(sz)) for _, sz in depth[:max(1, levels)]]
    if not d:
        return 0.0
    return float(sum(d) / len(d))

# --- WS-α-02: robust normalization & alpha score ---

def robust_scale(x: float, p05: float, p95: float, clip: bool = True) -> float:
    """Scale x to ~[-1, 1] using robust percentiles. Center at p50=(p05+p95)/2.
    If p95==p05 -> 0. Optionally clip to [-1,1].
    """
    try:
        x = float(x)
        p05 = float(p05)
        p95 = float(p95)
    except Exception:
        return 0.0
    if p95 == p05:
        return 0.0
    p50 = 0.5 * (p05 + p95)
    val = (x - p50) / (p95 - p05) * 2.0
    if clip:
        if val > 1.0:
            val = 1.0
        elif val < -1.0:
            val = -1.0
    return float(val)

class RollingPerc:
    """Maintain rolling percentiles (5/50/95) over a fixed-size window.
    For stability during warmup (<30 samples) return defaults (-1, 0, +1).
    """
    def __init__(self, window: int = 600):
        self.window = int(window)
        self.buf: deque[float] = deque(maxlen=self.window)
    def update(self, val: float) -> tuple[float, float, float]:
        try:
            v = float(val)
        except Exception:
            v = 0.0
        self.buf.append(v)
        if len(self.buf) < 30:
            return (-1.0, 0.0, 1.0)
        arr = np.asarray(self.buf, dtype=float)
        p05 = float(np.percentile(arr, 5))
        p50 = float(np.percentile(arr, 50))
        p95 = float(np.percentile(arr, 95))
        return (p05, p50, p95)

def compute_alpha_score(features: Dict[str, float], rp: Dict[str, tuple], weights: Dict[str, float] | None = None) -> float:
    """Compute weighted alpha score from normalized features using robust percentiles.
    Missing features default to 0. Features expected: OBI, TFI, ABSORB, MICRO_BIAS, OFI, TREND_ALIGN.
    """
    # --- PRE-SIGNAL DIAGNOSTICS (non-fatal, console print) ---
    try:
        # Try common keys for EMA/RSI/price (case-insensitive fallback)
        def _get_any(d: Dict[str, float], keys: list[str]):
            for k in keys:
                if k in d:
                    return d.get(k)
            # case-insensitive fallback
            kl = {str(x).lower(): x for x in d.keys()}
            for k in keys:
                x = kl.get(k.lower())
                if x is not None:
                    return d.get(x)
            return None

        ema_fast = _get_any(features, ["EMA_FAST", "ema_fast", "ema_fast_" , "ema_short", "ema_fast_price"])
        ema_slow = _get_any(features, ["EMA_SLOW", "ema_slow", "ema_long", "ema_slow_price"])
        ema_trend = _get_any(features, ["EMA_TREND", "ema_trend", "ema_mid", "ema_mid_price"])
        rsi = _get_any(features, ["RSI", "rsi", "rsi_14", "rsi_21"])
        price = _get_any(features, ["PRICE", "price", "mid", "last_price", "close"])

        print("\n" + "-" * 50)
        print("--- PRE-SIGNAL DIAGNOSTICS ---")
        print(f"  EMA fast: {ema_fast}")
        print(f"  EMA slow: {ema_slow}")
        print(f"  EMA trend: {ema_trend}")
        print(f"  RSI: {rsi}")
        print(f"  Price: {price}")
        # Also print core features used below (if present)
        for k in ["OBI", "TFI", "ABSORB", "MICRO_BIAS", "OFI", "TREND_ALIGN"]:
            if k in features or k.lower() in {kk.lower() for kk in features.keys()}:
                v = _get_any(features, [k])
                print(f"  {k}: {v}")
        # Dump any other factors that might affect score
        extra_keys = sorted([k for k in features.keys() if k.upper() not in {"OBI","TFI","ABSORB","MICRO_BIAS","OFI","TREND_ALIGN","EMA_FAST","EMA_SLOW","EMA_TREND","RSI","PRICE"}])
        if extra_keys:
            print("  Other features:")
            for k in extra_keys:
                try:
                    print(f"    - {k}: {features.get(k)}")
                except Exception:
                    pass
        print("-" * 50 + "\n")
    except Exception as _sig_dbg_e:
        try:
            print(f"Signal diagnostics error: {_sig_dbg_e}")
        except Exception:
            pass

    if weights is None:
        weights = {
            'OBI': 0.30,
            'TFI': 0.25,
            'ABSORB': 0.15,
            'MICRO_BIAS': 0.15,
            'OFI': 0.10,
            'TREND_ALIGN': 0.05,
        }
    score = 0.0
    total_w = 0.0
    for k, w in weights.items():
        x = float(features.get(k, 0.0) or 0.0)
        p = rp.get(k, (-1.0, 0.0, 1.0))
        p05, _, p95 = p
        xs = robust_scale(x, p05, p95, clip=True)
        score += w * xs
        total_w += w
    if total_w <= 0:
        return 0.0
    # Optional squash for stability
    return float(np.tanh(score))
