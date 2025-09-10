from __future__ import annotations

"""
Universe — Symbol ranking with hysteresis and robust normalization
=================================================================

Scores and ranks instruments for tradeability using liquidity, spread,
fillability and regime features. Applies EMA smoothing and hysteresis add/drop
thresholds to reduce churn in the active universe.

Score model (default)
---------------------
For symbol i let metrics be:
  • L_i  : liquidity proxy (e.g., notional depth or turnover)
  • S_i  : spread in bps (smaller is better)
  • P_i  : estimated P(fill) in [0,1]
  • R_i  : regime flag {0,1} (1=tradeable: e.g., trend/grind acceptable)

We compute robust min–max transforms using batch-wise 10th/90th percentiles:
    zL_i = clip((L_i - q10(L))/(q90(L)-q10(L)), 0, 1)
    zS_i = 1 - clip((S_i - q10(S))/(q90(S)-q10(S)), 0, 1)   # smaller spread better
and score
    score_i = wL*zL_i + wS*zS_i + wP*P_i + wR*R_i.

Membership is stabilized by a per-symbol hysteresis:
    add if score >= T_add; drop if score <= T_drop; dwell >= min_dwell.

All parameters are configurable via SSOT or ctor args.
"""

from dataclasses import dataclass

from core.config.loader import ConfigError, get_config
from repo.core.universe.hysteresis import EmaSmoother, Hysteresis


def _f(x: float | None, default: float = 0.0) -> float:
    """Coerce Optional[float] to float with default."""
    return default if x is None else float(x)


def _i(x: int | None, default: int = 0) -> int:
    """Coerce Optional[int] to int with default."""
    return default if x is None else int(x)


@dataclass
class SymbolMetrics:
    liquidity: float
    spread_bps: float
    p_fill: float
    regime_flag: float  # 0..1


@dataclass
class Ranked:
    symbol: str
    score: float
    active: bool


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    q = 0.0 if q < 0.0 else 1.0 if q > 1.0 else q
    xs2 = sorted(xs)
    pos = q * (len(xs2) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs2) - 1)
    frac = pos - lo
    return xs2[lo] * (1 - frac) + xs2[hi] * frac


class UniverseRanker:
    def __init__(
        self,
        *,
        wL: float | None = None,
        wS: float | None = None,
        wP: float | None = None,
        wR: float | None = None,
        add_thresh: float | None = None,
        drop_thresh: float | None = None,
        min_dwell: int | None = None,
        ema_alpha: float = 0.2,
    ) -> None:
        # defaults from SSOT
        if None in (wL, wS, wP, wR, add_thresh, drop_thresh, min_dwell):
            try:
                cfg = get_config()
                wL = float(cfg.get("universe.ranking.wL", 0.35)) if wL is None else wL
                wS = float(cfg.get("universe.ranking.wS", 0.25)) if wS is None else wS
                wP = float(cfg.get("universe.ranking.wP", 0.25)) if wP is None else wP
                wR = float(cfg.get("universe.ranking.wR", 0.15)) if wR is None else wR
                add_thresh = float(cfg.get("universe.ranking.add_thresh", 0.60)) if add_thresh is None else add_thresh
                drop_thresh = float(cfg.get("universe.ranking.drop_thresh", 0.40)) if drop_thresh is None else drop_thresh
                min_dwell = int(cfg.get("universe.ranking.min_dwell", 200)) if min_dwell is None else min_dwell
            except (ConfigError, Exception):
                wL = 0.35 if wL is None else wL
                wS = 0.25 if wS is None else wS
                wP = 0.25 if wP is None else wP
                wR = 0.15 if wR is None else wR
                add_thresh = 0.60 if add_thresh is None else add_thresh
                drop_thresh = 0.40 if drop_thresh is None else drop_thresh
                min_dwell = 200 if min_dwell is None else min_dwell
        # weights normalized for interpretability
        wL = _f(wL)
        wS = _f(wS)
        wP = _f(wP)
        wR = _f(wR)
        add_thresh = _f(add_thresh)
        drop_thresh = _f(drop_thresh)
        min_dwell = _i(min_dwell)

        tot = wL + wS + wP + wR
        self.wL = wL / tot
        self.wS = wS / tot
        self.wP = wP / tot
        self.wR = wR / tot
        self.addT = add_thresh
        self.dropT = drop_thresh
        self.min_dwell = min_dwell
        self.ema_alpha = float(ema_alpha)

        self._metrics: dict[str, SymbolMetrics] = {}
        self._hyst: dict[str, Hysteresis] = {}
        self._ema: dict[str, EmaSmoother] = {}
        self._score_raw: dict[str, float] = {}
        self._score_smooth: dict[str, float] = {}

    # ---------- update API ----------

    def update_metrics(self, symbol: str, *, liquidity: float | None, spread_bps: float | None, p_fill: float | None, regime_flag: float | None) -> None:
        # Coerce Optional values to ensure type safety
        L = _f(liquidity)
        S = _f(spread_bps)
        P = _f(p_fill)
        R = _f(regime_flag)

        self._metrics[symbol] = SymbolMetrics(L, S, max(0.0, min(1.0, P)), max(0.0, min(1.0, R)))

    # ---------- scoring ----------

    def _robust_scale(self, vals: list[float], invert: bool = False):
        # scale to [0,1] using p10..p90 range; outside clipped
        if not vals:
            return lambda v: 0.0
        q10 = _quantile(vals, 0.10)
        q90 = _quantile(vals, 0.90)
        rng = max(1e-12, q90 - q10)
        def tr(v: float) -> float:
            z = (v - q10) / rng
            z = 0.0 if z < 0.0 else 1.0 if z > 1.0 else z
            return (1.0 - z) if invert else z
        return tr

    def _compute_scores(self) -> dict[str, float]:
        if not self._metrics:
            return {}
        Ls = [m.liquidity for m in self._metrics.values()]
        Ss = [m.spread_bps for m in self._metrics.values()]
        trL = self._robust_scale(Ls, invert=False)
        trS = self._robust_scale(Ss, invert=True)
        out: dict[str, float] = {}
        for sym, m in self._metrics.items():
            zL = trL(m.liquidity)
            zS = trS(m.spread_bps)
            s = self.wL * zL + self.wS * zS + self.wP * m.p_fill + self.wR * m.regime_flag
            out[sym] = s
        return out

    # ---------- rank + hysteresis ----------

    def rank(self, *, top_k: int | None = None) -> list[Ranked]:
        raw = self._compute_scores()
        # smooth
        for sym, sc in raw.items():
            ema = self._ema.get(sym)
            if ema is None:
                ema = EmaSmoother(alpha=self.ema_alpha, init=sc)
                self._ema[sym] = ema
            self._score_smooth[sym] = ema.update(sc)
            self._score_raw[sym] = sc
        # hysteresis
        out: list[Ranked] = []
        for sym, sc in self._score_smooth.items():
            h = self._hyst.get(sym)
            if h is None:
                h = Hysteresis(add_thresh=self.addT, drop_thresh=self.dropT, min_dwell=self.min_dwell)
                self._hyst[sym] = h
            st = h.update(sc)
            out.append(Ranked(symbol=sym, score=sc, active=st.active))
        out.sort(key=lambda r: r.score, reverse=True)
        if top_k is not None:
            out = out[: int(top_k)]
        return out

    # ---------- debug/inspection ----------

    def scores(self) -> dict[str, float]:
        return dict(self._score_smooth)

    def raw_scores(self) -> dict[str, float]:
        return dict(self._score_raw)

__all__ = ["UniverseRanker", "SymbolMetrics", "Ranked"]
