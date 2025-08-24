"""Deterministic feature engineering utilities.

Features implemented:
- ATR (Average True Range, normalized)
- RSI-lite (using simple EMA approximation)
- VWAP (rolling intraday; expects cumulative volume+price*volume if streaming)
- Realized volatility (rolling window of log returns)
- Momentum (n-period return)
- MACD (12-26 EMA diff + signal line)
- Bollinger Band Width ( (upper-lower)/middle )

All feature functions are pure (functional) given a pandas DataFrame to
ensure determinism for a given input slice. No random state.

Contract:
Input DataFrame must contain columns: ['open','high','low','close','volume'].
Index should be monotonic increasing (timestamp).

Output: DataFrame with added feature columns (no rows dropped). Initial periods
with insufficient history are forward-filled after computation to maintain
vector length.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Sequence, Dict

# Default windows
ATR_PERIOD = 14
RSI_PERIOD = 14
RV_WINDOW = 30
MOM_WINDOW = 20
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
BB_WINDOW = 20
BB_K = 2.0

REQUIRED_COLS = ["open","high","low","close","volume"]


def _check_cols(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    if not df.index.is_monotonic_increasing:
        raise ValueError("Index must be monotonic increasing")


def atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)
    tr = (high - low).abs()
    tr = pd.concat([
        tr,
        (high - close).abs(),
        (low - close).abs()
    ], axis=1).max(axis=1)
    atr_raw = tr.ewm(alpha=1/period, adjust=False, min_periods=1).mean()
    # Normalize by price to keep scale roughly stable across assets
    return (atr_raw / df["close"]).rename("atr_norm")


def rsi_lite(df: pd.DataFrame, period: int = RSI_PERIOD) -> pd.Series:
    delta = df["close"].diff().fillna(0.0)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    gain_ema = pd.Series(gain, index=df.index).ewm(alpha=1/period, adjust=False, min_periods=1).mean()
    loss_ema = pd.Series(loss, index=df.index).ewm(alpha=1/period, adjust=False, min_periods=1).mean()
    rs = gain_ema / (loss_ema + 1e-12)
    rsi = 100 - (100 / (1 + rs))
    return rsi.rename("rsi")


def vwap(df: pd.DataFrame) -> pd.Series:
    # Intraday VWAP proxy; if multi-day, reset daily using date component
    price = df["close"]
    vol = df["volume"].replace(0, np.nan)
    day = df.index.date
    pv = (price * vol).groupby(day).cumsum()
    v_cum = vol.groupby(day).cumsum()
    vwap = pv / v_cum
    vwap = vwap.fillna(method="ffill")
    return vwap.rename("vwap")


def realized_vol(df: pd.DataFrame, window: int = RV_WINDOW) -> pd.Series:
    log_ret = np.log(df["close"]).diff().fillna(0.0)
    rv = (log_ret**2).rolling(window, min_periods=1).sum() ** 0.5
    return rv.rename("realized_vol")


def momentum(df: pd.DataFrame, window: int = MOM_WINDOW) -> pd.Series:
    mom = df["close"].pct_change(window).fillna(0.0)
    return mom.rename(f"mom_{window}")


def macd(df: pd.DataFrame, fast: int = MACD_FAST, slow: int = MACD_SLOW, signal: int = MACD_SIGNAL) -> pd.DataFrame:
    price = df["close"]
    ema_fast = price.ewm(span=fast, adjust=False, min_periods=1).mean()
    ema_slow = price.ewm(span=slow, adjust=False, min_periods=1).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=1).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({
        "macd_line": macd_line,
        "macd_signal": signal_line,
        "macd_hist": hist
    })


def bollinger_width(df: pd.DataFrame, window: int = BB_WINDOW, k: float = BB_K) -> pd.Series:
    mid = df["close"].rolling(window, min_periods=1).mean()
    std = df["close"].rolling(window, min_periods=1).std(ddof=0).fillna(0.0)
    upper = mid + k * std
    lower = mid - k * std
    width = (upper - lower) / (mid + 1e-12)
    return width.rename("bb_width")


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame with deterministic engineered features.
    Leaves original OHLCV columns, appends feature columns.
    NaN introduced by warm-up windows are forward filled then back filled (edge).
    """
    _check_cols(df)
    feats = pd.DataFrame(index=df.index)
    feats["atr_norm"] = atr(df)
    feats["rsi"] = rsi_lite(df)
    feats["vwap"] = vwap(df)
    feats["realized_vol"] = realized_vol(df)
    feats[momentum(df).name] = momentum(df)
    macd_df = macd(df)
    for c in macd_df.columns:
        feats[c] = macd_df[c]
    feats["bb_width"] = bollinger_width(df)

    # Handle warm-up NaNs deterministically
    feats = feats.fillna(method="ffill").fillna(method="bfill")

    return pd.concat([df, feats], axis=1)


def feature_vector(df: pd.DataFrame, feature_order: Sequence[str] | None = None) -> np.ndarray:
    """Return numpy feature matrix (n, F) with a stable column order.
    If feature_order not supplied it is inferred (excluding raw ohlcv) and returned as attribute.
    """
    full = build_features(df)
    base_exclude = set(REQUIRED_COLS)
    candidates = [c for c in full.columns if c not in base_exclude]
    if feature_order is None:
        feature_order = sorted(candidates)
    arr = full[feature_order].to_numpy(dtype=np.float32)
    return arr

__all__ = [
    "build_features","feature_vector","atr","rsi_lite","vwap","realized_vol","momentum","macd","bollinger_width"
]
