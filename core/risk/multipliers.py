from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict


class LambdaOrchestrator:
    def __init__(self, config: Dict[str, Any] | None = None):
        self.cfg = (config or {}).get('kelly', {}).get('multipliers', {})

    @staticmethod
    def _piecewise(value: Decimal, breaks: list[float], lambdas: list[float]) -> float:
        v = float(value)
        if len(lambdas) == 0:
            return 1.0
        if len(breaks) + 1 != len(lambdas):
            # fallback safe
            return lambdas[-1]
        if len(breaks) == 0:
            return lambdas[0]
        if v <= breaks[0]:
            return lambdas[0]
        if len(breaks) == 1:
            return lambdas[1]
        if v <= breaks[1]:
            return lambdas[1]
        return lambdas[2]

    def compute(self, intent: Dict[str, Any], risk_ctx: Dict[str, Any], micro_ctx: Dict[str, Any]) -> Dict[str, float]:
        # λ_cal via ECE
        cal_cfg = self.cfg.get('cal', {})
        ece_warn = float(cal_cfg.get('ece_warn', 0.04))
        ece_bad = float(cal_cfg.get('ece_bad', 0.08))
        ece = float(micro_ctx.get('ece', 0.0))
        if ece <= ece_warn:
            lam_cal = 1.0
        elif ece <= ece_bad:
            lam_cal = 0.8
        else:
            lam_cal = 0.6

        # λ_reg by regime
        reg_cfg = self.cfg.get('reg', {})
        regime = str(micro_ctx.get('regime', 'trend')).lower()
        lam_reg = {
            'trend': float(reg_cfg.get('trend', 1.0)),
            'grind': float(reg_cfg.get('grind', 0.8)),
            'chaos': float(reg_cfg.get('chaos', 0.6)),
        }.get(regime, 1.0)

        # λ_liq by half-spread bps
        liq_cfg = self.cfg.get('liq', {})
        hs_bps = Decimal(str(micro_ctx.get('half_spread_bps', 0)))
        lam_liq = self._piecewise(hs_bps, list(map(float, liq_cfg.get('spread_bps_breaks', [5, 10]))), list(map(float, liq_cfg.get('lambdas', [1.0, 0.8, 0.6]))))

        # λ_dd by portfolio DD%
        dd_cfg = self.cfg.get('dd', {})
        dd_warn = float(dd_cfg.get('dd_warn', 0.05))
        dd_bad = float(dd_cfg.get('dd_bad', 0.10))
        dd = float(risk_ctx.get('drawdown_frac', 0.0))
        if dd <= dd_warn:
            lam_dd = float(dd_cfg.get('lambdas', [1.0, 0.7, 0.4])[0])
        elif dd <= dd_bad:
            lam_dd = float(dd_cfg.get('lambdas', [1.0, 0.7, 0.4])[1])
        else:
            lam_dd = float(dd_cfg.get('lambdas', [1.0, 0.7, 0.4])[2])

        # λ_lat by p95 latency
        lat_cfg = self.cfg.get('lat', {})
        lat_p95 = Decimal(str(micro_ctx.get('latency_p95_ms', 0)))
        lam_lat = self._piecewise(lat_p95, list(map(float, lat_cfg.get('p95_ms_breaks', [200, 500]))), list(map(float, lat_cfg.get('lambdas', [1.0, 0.8, 0.6]))))

        return {'cal': lam_cal, 'reg': lam_reg, 'liq': lam_liq, 'dd': lam_dd, 'lat': lam_lat}
