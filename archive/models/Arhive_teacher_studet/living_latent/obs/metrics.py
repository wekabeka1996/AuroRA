from __future__ import annotations
from typing import Optional, Dict
import numpy as np
from prometheus_client import (
    CollectorRegistry, Counter, Gauge, Histogram, start_http_server
)
import threading

class Metrics:
    def __init__(self, profile: str, buckets: dict, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry(auto_describe=True)
        self.profile = profile

        # --- Counters ---
        self.decisions = Counter(
            "aurora_acceptance_decision_total", "Acceptance decisions",
            labelnames=("decision", "profile"), registry=self.registry)
        self.violations = Counter(
            "aurora_acceptance_violation_total", "Guard violations",
            labelnames=("type", "profile"), registry=self.registry)
        self.state_transitions = Counter(
            "aurora_acceptance_state_transitions_total", "FSM transitions",
            labelnames=("from_state", "to_state", "profile"), registry=self.registry)
        self.icp_miss = Counter(
            "aurora_icp_miss_total", "ICP misses (y out of interval)", labelnames=("profile",), registry=self.registry)
        self.state_saves = Counter(
            "aurora_state_saves_total", "State snapshot saves", labelnames=("profile",), registry=self.registry)
        self.state_restores = Counter(
            "aurora_state_restores_total", "State snapshot restores", labelnames=("profile",), registry=self.registry)

        # --- Gauges ---
        self.icp_alpha = Gauge("aurora_icp_alpha", "Current ICP alpha", labelnames=("profile",), registry=self.registry)
        self.icp_alpha_target = Gauge("aurora_icp_alpha_target", "Target ICP alpha", labelnames=("profile",), registry=self.registry)
        self.icp_coverage_ema = Gauge("aurora_icp_coverage_ema", "Coverage EMA", labelnames=("profile",), registry=self.registry)
        # Extended Adaptive ICP live metrics (R2 Block B)
        self.icp_alpha_eff = Gauge(
            "aurora_icp_alpha_eff", "Effective alpha after dynamic adjustment", labelnames=("profile",), registry=self.registry
        )
        self.icp_aci_ema = Gauge(
            "aurora_icp_aci_ema", "Adaptive Conformal Instability (ACI) EMA signal", labelnames=("profile",), registry=self.registry
        )
        self.icp_qhat = Gauge(
            "aurora_icp_qhat", "Current quantile estimate (q-hat)", labelnames=("profile",), registry=self.registry
        )
        self.kappa_plus = Gauge("aurora_acceptance_kappa_plus", "kappa+ gauge", labelnames=("profile",), registry=self.registry)
        # Gauge renamed to avoid collision with histogram of same semantic base name
        self.rel_width = Gauge("aurora_acceptance_rel_width_current", "Relative interval width (instant)", labelnames=("profile",), registry=self.registry)
        self.state_flag = Gauge("aurora_acceptance_state", "FSM state flag (one-hot)",
                                labelnames=("state","profile"), registry=self.registry)
        self.last_state_save_ts = Gauge("aurora_state_last_save_timestamp", "Unix timestamp of last successful state save", labelnames=("profile",), registry=self.registry)
        # Execution gating metrics (Batch-010)
        self.execution_risk_scale = Gauge(
            "aurora_execution_risk_scale", "Current recommended risk scale (notional/base_notional)",
            labelnames=("profile",), registry=self.registry
        )
        self.execution_blocks = Counter(
            "aurora_execution_block_total", "Execution blocks (recommended notional==0)",
            labelnames=("profile","reason"), registry=self.registry
        )
        # Decision churn (AUR-GATE-601)
        self.decision_churn_per_1k = Gauge(
            "aurora_decision_churn_per_1k", "Decision churn per 1000 decisions (hysteresis-adjusted)",
            labelnames=("profile",), registry=self.registry
        )
        self.execution_block_rate = Gauge(
            "aurora_exec_block_rate", "Rolling execution block rate (share)",
            labelnames=("profile",), registry=self.registry
        )
        # Dwell efficiency (successful transitions / attempted transitions)
        self.dwell_efficiency = Gauge(
            "aurora_dwell_efficiency", "Hysteresis dwell efficiency (transitions/attempts)",
            labelnames=("profile",), registry=self.registry
        )
        # DRO risk adjustment (AUR-DRO-703 Prometheus export)
        self.dro_risk_factor = Gauge(
            "aurora_risk_dro_factor", "Average DRO risk scaling factor (summary-level)",
            labelnames=("profile",), registry=self.registry
        )
        self.dro_risk_scale_adj = Gauge(
            "aurora_risk_dro_adj", "Average risk scale adjusted by DRO factor (summary-level)",
            labelnames=("profile",), registry=self.registry
        )

        # Tail risk gauges (RSK-203)
        self.tail_xi = Gauge(
            "aurora_tail_xi", "Tail index (Hill) estimate", labelnames=("profile","regime"), registry=self.registry
        )
        self.tail_theta_e = Gauge(
            "aurora_tail_theta_e", "Extremal index (runs) estimate", labelnames=("profile","regime"), registry=self.registry
        )
        self.tail_lambda_u = Gauge(
            "aurora_tail_lambda_u", "Upper tail dependence coefficient", labelnames=("profile","regime"), registry=self.registry
        )
        # CTR gauge (TVF 2.0)
        self.tvf_ctr = Gauge(
            "aurora_tvf_ctr", "Coverage Transfer Ratio", labelnames=("profile",), registry=self.registry
        )
        # DCTS gauge (TVF 2.0)
        self.tvf_dcts = Gauge(
            "aurora_tvf2_dcts", "Distributional Conformal Transfer Score", labelnames=("profile",), registry=self.registry
        )
        self.tvf_dcts_robust = Gauge(
            "aurora_tvf2_dcts_robust", "Robust (multigrid) DCTS value", labelnames=("profile",), registry=self.registry
        )
        self.tvf_dcts_grid = Gauge(
            "aurora_tvf2_dcts_grid", "Per-grid DCTS values", labelnames=("profile","grid"), registry=self.registry
        )
        # Extended DCTS exports (PROM-DCTS-EXPORT)
        self.tvf_dcts_robust_value = Gauge(
            "aurora_tvf2_dcts_robust_value", "Robust DCTS aggregate value (export layer)", labelnames=("profile",), registry=self.registry
        )
        self.tvf_dcts_min_value = Gauge(
            "aurora_tvf2_dcts_min_value", "Minimum grid DCTS value (export layer)", labelnames=("profile",), registry=self.registry
        )
        # CI gating (soft) metrics
        self.ci_gating_state = Gauge(
            "aurora_ci_gating_state", "CI soft gating state code", labelnames=("profile","metric"), registry=self.registry
        )
        self.ci_gating_value = Gauge(
            "aurora_ci_gating_value", "Latest observed metric value for soft gating", labelnames=("profile","metric"), registry=self.registry
        )
        self.ci_gating_threshold = Gauge(
            "aurora_ci_gating_threshold", "Threshold used for ci gating", labelnames=("profile","metric"), registry=self.registry
        )
        self.ci_gating_violations = Counter(
            "aurora_ci_gating_violation_total", "Soft gating violations (value out of accepted relation)", labelnames=("profile","metric"), registry=self.registry
        )
        # Coverage monitoring (COVERAGE-MONITORING)
        self.ci_coverage_abs_err = Gauge(
            "aurora_ci_coverage_abs_err", "Absolute coverage error vs target", labelnames=("profile",), registry=self.registry
        )
        self.ci_coverage_abs_err_ema = Gauge(
            "aurora_ci_coverage_abs_err_ema", "EMA of absolute coverage error", labelnames=("profile",), registry=self.registry
        )

        # --- Histograms ---
        self.surprisal_h = Histogram(
            "aurora_acceptance_surprisal_v2", "Surprisal v2 distribution",
            labelnames=("profile",), registry=self.registry,
            buckets=tuple(buckets.get("surprisal_buckets", [0.1,0.3,0.7,1.2,2.0,3.0,5.0])))
        self.latency_h = Histogram(
            "aurora_acceptance_latency_ms", "Latency ms distribution",
            labelnames=("profile",), registry=self.registry,
            buckets=tuple(buckets.get("latency_buckets_ms", [10,25,50,75,100,150,250,400,600])))
        self.width_h = Histogram(
            "aurora_acceptance_rel_width", "Relative interval width distribution",
            labelnames=("profile",), registry=self.registry,
            buckets=tuple(buckets.get("width_buckets", [0.001,0.002,0.004,0.008,0.016,0.032])))
        self.kappa_h = Histogram(
            "aurora_acceptance_kappa", "Kappa distribution",
            labelnames=("profile",), registry=self.registry,
            buckets=tuple(buckets.get("kappa_buckets", [0.2,0.4,0.6,0.7,0.8,0.9,0.95,0.99])))

        self._server_started = False
        self._lock = threading.Lock()

    def start_http(self, port: int, mode: str = 'standalone'):
        """Start embedded Prometheus HTTP exporter unless mode == 'api'.

        Parameters
        ----------
        port : int
            Port to bind.
        mode : str
            'standalone' launches exporter; 'api' skips (FastAPI serves /metrics).
        """
        if mode == 'api':
            return
        with self._lock:
            if not self._server_started:
                start_http_server(port, registry=self.registry)
                self._server_started = True

    def set_icp_stats(self, alpha: float, alpha_target: float, coverage_ema: float):
        self.icp_alpha.labels(self.profile).set(alpha)
        self.icp_alpha_target.labels(self.profile).set(alpha_target)
        self.icp_coverage_ema.labels(self.profile).set(coverage_ema)
    def set_icp_live_extras(self, alpha_eff: float | None = None, qhat: float | None = None):
        """Optional extra Adaptive ICP stats.

        Parameters
        ----------
        alpha_eff : float | None
            Effective alpha actually used after transition inflations.
        qhat : float | None
            Estimated quantile multiplier (scale before * sigma_eff).
        """
        try:
            if alpha_eff is not None:
                self.icp_alpha_eff.labels(self.profile).set(alpha_eff)
            if qhat is not None and np.isfinite(qhat):
                self.icp_qhat.labels(self.profile).set(qhat)
        except Exception:
            pass

    def set_icp_aci(self, aci_ema: float | None):
        try:
            if aci_ema is not None and np.isfinite(aci_ema):
                self.icp_aci_ema.labels(self.profile).set(float(aci_ema))
        except Exception:
            pass

    def observe_surprisal(self, val: float):
        self.surprisal_h.labels(self.profile).observe(val)

    def observe_latency(self, ms: float):
        self.latency_h.labels(self.profile).observe(ms)

    def observe_width_kappa(self, rel_width: float, kappa: float, kappa_plus: float):
        self.width_h.labels(self.profile).observe(rel_width)
        self.kappa_h.labels(self.profile).observe(kappa)
        self.kappa_plus.labels(self.profile).set(kappa_plus)
        self.rel_width.labels(self.profile).set(rel_width)

    def count_decision(self, decision: str):
        self.decisions.labels(decision, self.profile).inc()

    def count_violation(self, vtype: str):
        self.violations.labels(vtype, self.profile).inc()

    def fsm_transition(self, from_state: str, to_state: str):
        self.state_transitions.labels(from_state, to_state, self.profile).inc()
        for s in ("PASS","DERISK","BLOCK"):
            self.state_flag.labels(s, self.profile).set(1.0 if s == to_state else 0.0)

    # --- Persistence hooks ---
    def count_state_save(self):
        self.state_saves.labels(self.profile).inc()
        import time as _t
        self.last_state_save_ts.labels(self.profile).set(_t.time())

    def count_state_restore(self):
        self.state_restores.labels(self.profile).inc()

    # --- Tail metrics hooks (RSK-203) ---
    def set_tail_metrics(self, regime: str, xi: float, theta_e: float, lambda_u: float):
        if not np.isnan(xi):
            self.tail_xi.labels(self.profile, regime).set(float(xi))
        if not np.isnan(theta_e):
            self.tail_theta_e.labels(self.profile, regime).set(float(theta_e))
        if not np.isnan(lambda_u):
            self.tail_lambda_u.labels(self.profile, regime).set(float(lambda_u))

    # --- Execution gating hooks ---
    def set_execution_risk_scale(self, scale: float):
        try:
            self.execution_risk_scale.labels(self.profile).set(scale)
        except Exception:
            pass

    def count_execution_block(self, reason: str):
        try:
            self.execution_blocks.labels(self.profile, reason).inc()
        except Exception:
            pass

    # --- Hysteresis / churn hooks ---
    def set_decision_churn(self, churn_per_1k: float):
        try:
            self.decision_churn_per_1k.labels(self.profile).set(churn_per_1k)
        except Exception:
            pass

    def set_exec_block_rate(self, rate: float):
        try:
            self.execution_block_rate.labels(self.profile).set(rate)
        except Exception:
            pass

    def set_dwell_efficiency(self, eff: float):
        try:
            self.dwell_efficiency.labels(self.profile).set(eff)
        except Exception:
            pass

    # --- DRO risk adjustment setters ---
    def set_dro_risk_adjustment(self, base: float | None = None, factor: float | None = None, adj: float | None = None):
        """Export DRO adjustment metrics.

        Parameters
        ----------
        base : float | None
            Base average risk scale (pre-DRO) for context; not exported directly here (already via other gauges if any).
        factor : float | None
            DRO scaling factor applied to base average risk scale.
        adj : float | None
            Adjusted average risk scale (base * factor).
        """
        try:
            import numpy as _np
            if factor is not None and _np.isfinite(factor):
                self.dro_risk_factor.labels(self.profile).set(float(factor))
            if adj is not None and _np.isfinite(adj):
                self.dro_risk_scale_adj.labels(self.profile).set(float(adj))
        except Exception:
            pass

    # --- TVF2 hooks ---
    def set_tvf_ctr(self, ctr: float | None):
        try:
            if ctr is not None and np.isfinite(ctr):
                self.tvf_ctr.labels(self.profile).set(ctr)
        except Exception:
            pass

    def set_tvf_dcts(self, dcts: float | None):
        try:
            if dcts is not None and np.isfinite(dcts):
                self.tvf_dcts.labels(self.profile).set(dcts)
        except Exception:
            pass

    def set_tvf_dcts_robust(self, robust: float | None):
        try:
            if robust is not None and np.isfinite(robust):
                self.tvf_dcts_robust.labels(self.profile).set(robust)
        except Exception:
            pass

    def set_tvf_dcts_grids(self, grid_map: dict[str, float] | None):
        if not isinstance(grid_map, dict):
            return
        for g, v in grid_map.items():
            try:
                if v is not None and np.isfinite(v):
                    self.tvf_dcts_grid.labels(self.profile, str(g)).set(float(v))
            except Exception:
                continue

    # --- Extended DCTS export layer (PROM-DCTS-EXPORT) ---
    def export_tvf_dcts_layer(self, base: float | None, robust: float | None, dmin: float | None, grids: dict | None = None, export_grids: bool = False):
        try:
            if base is not None and np.isfinite(base):
                # reuse existing gauge
                self.tvf_dcts.labels(self.profile).set(base)
            if robust is not None and np.isfinite(robust):
                self.tvf_dcts_robust_value.labels(self.profile).set(robust)
            if dmin is not None and np.isfinite(dmin):
                self.tvf_dcts_min_value.labels(self.profile).set(dmin)
            if export_grids and isinstance(grids, dict):
                for g,v in grids.items():
                    try:
                        if v is not None and np.isfinite(v):
                            self.tvf_dcts_grid.labels(self.profile, str(g)).set(float(v))
                    except Exception:
                        pass
        except Exception:
            pass

    # --- CI soft gating hooks ---
    def set_ci_gating_state(self, metric: str, state: str):
        try:
            # map textual state to int code
            mapping = {"observe":0,"warn":1,"watch":2,"stable":3,"cooldown":4,"unknown":9}
            code = mapping.get(state, 9)
            self.ci_gating_state.labels(self.profile, metric).set(code)
        except Exception:
            pass

    def set_ci_gating_value(self, metric: str, value: float):
        try:
            if np.isfinite(value):
                self.ci_gating_value.labels(self.profile, metric).set(value)
        except Exception:
            pass

    def set_ci_gating_threshold(self, metric: str, threshold: float):
        try:
            if np.isfinite(threshold):
                self.ci_gating_threshold.labels(self.profile, metric).set(threshold)
        except Exception:
            pass

    def inc_ci_gating_violation(self, metric: str):
        try:
            self.ci_gating_violations.labels(self.profile, metric).inc()
        except Exception:
            pass

    # --- Coverage monitoring setters ---
    def set_coverage_abs_err(self, val: float | None):
        try:
            if val is not None and np.isfinite(val):
                self.ci_coverage_abs_err.labels(self.profile).set(float(val))
        except Exception:
            pass

    def set_coverage_abs_err_ema(self, val: float | None):
        try:
            if val is not None and np.isfinite(val):
                self.ci_coverage_abs_err_ema.labels(self.profile).set(float(val))
        except Exception:
            pass

__all__ = ["Metrics"]
