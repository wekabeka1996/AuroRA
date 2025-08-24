from __future__ import annotations
import numpy as np
from typing import Dict, Any

def to_compact_stats(arr) -> Dict[str, Any]:
    a = np.asarray(arr).reshape(-1)
    if a.size == 0:
        return {"n": 0, "mean": 0.0, "std": 0.0, "q05": 0.0, "q50": 0.0, "q95": 0.0}
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "std": float(a.std()),
        "q05": float(np.quantile(a, 0.05)),
        "q50": float(np.quantile(a, 0.50)),
        "q95": float(np.quantile(a, 0.95)),
    }

__all__ = ["to_compact_stats"]
