import numpy as np

def rolling_std(arr, window):
    if len(arr) < max(2, window):
        return 0.0
    a = np.array(arr[-window:], dtype=float)
    return float(np.std(a))

def synthetic_l5_stream(n=3000, seed=42):
    """Yield synthetic L5 order book + trades: (mid, spread, bids, asks, trades)."""
    rng = np.random.default_rng(seed)
    mid = 30000.0
    for i in range(n):
        mid += rng.normal(0, 1.5) + (-0.02 * (mid - 30000))
        spread = max(0.5, abs(rng.normal(1.0, 0.2)))
        bids = [(mid - spread/2 - j*0.5, max(1.0, rng.gamma(2.0, 3.0))) for j in range(5)]
        asks = [(mid + spread/2 + j*0.5, max(1.0, rng.gamma(2.0, 3.0))) for j in range(5)]
        pos_bias = rng.normal(0, 0.3)
        trades = [{"side": "buy" if rng.normal(0,1)+pos_bias>0 else "sell", "qty": float(max(0.01, rng.gamma(2.0, 0.2)))} for _ in range(rng.integers(3, 15))]
        yield float(mid), float(spread), bids, asks, trades
