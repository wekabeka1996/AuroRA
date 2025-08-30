from __future__ import annotations

"""
Signal — Linear Score with Optional Cross-Asset Term and Calibration
===================================================================

Formula
-------
S(t) = w^T x(t) + b + gamma * beta_{i|SOL} * r_SOL(t - tau*)

- w: weights over feature vector x (features already preprocessed/scaled, dimensionless)
- b: intercept (bias, dimensionless)
- gamma: cross-asset coupling coefficient (dimensionless)
- beta_{i|SOL}: lead-lag beta (dimensionless, estimated in leadlag_hy.py)
- r_SOL(t - tau*): lagged return of SOL at tau* (fractional return, e.g., 0.02 for 2%, anti-look-ahead respected by upstream)

Probability mapping
-------------------
p_raw = sigmoid(S); optional calibration step p = Calibrator(p_raw)
Calibrator is an injected dependency (Platt/Isotonic/Venn-Abers/ICP wrapper).

Design
------
- No external deps; robust to missing features (treated as 0.0)
- Numerically stable sigmoid (clip S to [-40, 40])
- Deterministic component breakdown for XAI DecisionLog
- Reads optional defaults from SSOT-config (signal.score.gamma, signal.score.use_cross_asset)

Usage
-----
    model = ScoreModel(weights={"obi": 0.8, "microprice": 0.5}, intercept=-0.1)
    out = model.score_event(
        features={"obi": 0.12, "microprice": -0.03},
        cross_beta=0.25,
        cross_return=-0.004,
        calibrator=None,
    )
    # out = {"score": ..., "p_raw": ..., "p": ..., "components": {...}}

"""

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol, runtime_checkable, Union
import math

from core.config.loader import get_config, ConfigError


@runtime_checkable
class CalibratorProto(Protocol):
    def calibrate_prob(self, p: float) -> float: ...

@runtime_checkable
class ModelProto(Protocol):
    def predict_proba(self, p: float) -> float: ...

@runtime_checkable
class TransformerProto(Protocol):
    def transform(self, p: float) -> float: ...


def _sigmoid(z: float) -> float:
    # numerically stable sigmoid
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    else:
        ez = math.exp(z)
        return ez / (1.0 + ez)


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class ScoreOutput:
    score: float
    p_raw: float
    p: float
    components: Dict[str, float]

    def as_dict(self) -> Dict[str, float]:
        d: Dict[str, float] = {
            "score": self.score,
            "p_raw": self.p_raw,
            "p": self.p,
        }
        for k, v in self.components.items():
            d[f"comp_{k}"] = v
        return d


class ScoreModel:
    def __init__(
        self,
        *,
        weights: Mapping[str, float],
        intercept: float = 0.0,
        gamma: Optional[float] = None,
        use_cross_asset: Optional[bool] = None,
    ) -> None:
        self._w = {str(k): float(v) for k, v in weights.items()}
        self._b = float(intercept)

        # Defaults from config if not supplied
        g = gamma
        uca = use_cross_asset
        if g is None or uca is None:
            try:
                cfg = get_config()
                if g is None:
                    g = float(cfg.get("signal.score.gamma", 0.0))
                if uca is None:
                    uca = bool(cfg.get("signal.score.use_cross_asset", True))
            except (ConfigError, Exception):
                # fall back on safe defaults
                if g is None:
                    g = 0.0
                if uca is None:
                    uca = True
        self._gamma = float(g)
        self._use_cross = bool(uca)

    # --------- public API ---------

    def score_event(
        self,
        *,
        features: Mapping[str, Any],
        cross_beta: Optional[float] = None,
        cross_return: Optional[float] = None,
        calibrator: Optional[Union[CalibratorProto, ModelProto, TransformerProto]] = None,
    ) -> ScoreOutput:
        """
        Compute linear score and probability, with optional cross-asset coupling and calibration.

        Parameters
        ----------
        features : mapping from feature name to numeric value (missing treated as 0.0)
        cross_beta : beta_{i|SOL} estimated by lead-lag model (optional)
        cross_return : lagged return of SOL at tau* (optional)
        calibrator : object with one of methods {calibrate_prob(p), predict_proba(p)}; optional
        """
        lin = 0.0
        for k, w in self._w.items():
            xk = features.get(k, 0.0)
            try:
                x = float(xk)
            except Exception:
                x = 0.0
            lin += w * x

        cross = 0.0
        if self._use_cross and self._gamma != 0.0 and cross_beta is not None and cross_return is not None:
            try:
                cross = self._gamma * float(cross_beta) * float(cross_return)
            except Exception:
                cross = 0.0

        s = lin + self._b + cross
        p_raw = _sigmoid(_clip(s, -40.0, 40.0))

        p = p_raw
        if calibrator is not None:
            # flexible adapter
            if hasattr(calibrator, "calibrate_prob"):
                p = float(calibrator.calibrate_prob(p_raw))
            elif hasattr(calibrator, "predict_proba"):
                p = float(calibrator.predict_proba(p_raw))
            elif hasattr(calibrator, "transform"):
                p = float(calibrator.transform(p_raw))
            else:
                # unknown calibrator interface — leave raw prob
                p = p_raw
            # clamp to [0,1]
            p = 0.0 if p < 0.0 else 1.0 if p > 1.0 else p

        comps = {
            "lin": lin,
            "intercept": self._b,
            "cross": cross,
            "gamma": self._gamma,
        }
        return ScoreOutput(score=s, p_raw=p_raw, p=p, components=comps)

    def score_only(self, features: Mapping[str, Any], *, cross_beta: Optional[float] = None, cross_return: Optional[float] = None) -> float:
        return self.score_event(features=features, cross_beta=cross_beta, cross_return=cross_return).score

    def predict_proba(self, features: Mapping[str, Any], *, cross_beta: Optional[float] = None, cross_return: Optional[float] = None, calibrator: Optional[Union[CalibratorProto, ModelProto, TransformerProto]] = None) -> float:
        return self.score_event(features=features, cross_beta=cross_beta, cross_return=cross_return, calibrator=calibrator).p

    # --------- utilities ---------

    def weights(self) -> Mapping[str, float]:
        return dict(self._w)

    def intercept(self) -> float:
        return self._b

    def gamma(self) -> float:
        return self._gamma

    def use_cross_asset(self) -> bool:
        return self._use_cross
