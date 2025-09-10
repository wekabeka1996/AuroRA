from __future__ import annotations

import os
from typing import Any

from aurora.governance import Governance
from aurora.health import HealthGuard
from core.aurora.pretrade import (
    gate_expected_return,
    gate_latency,
    gate_slippage,
    gate_trap,
)
from core.scalper.calibrator import CalibInput, IsotonicCalibrator
from core.scalper.sprt import SPRT, SprtConfig
from core.scalper.trap import TrapWindow
from risk.manager import RiskManager


class PretradePipeline:
    """Pretrade decision pipeline. Pure-ish core that orchestrates guards.

    Dependencies are injected to keep FastAPI glue outside.
    """

    def __init__(
        self,
        *,
        emitter: Any | None,
        trap_window: TrapWindow | None,
        health_guard: HealthGuard | None,
        risk_manager: RiskManager | None,
        governance: Governance | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        self.emitter = emitter
        self.tw = trap_window
        self.hg = health_guard
        self.rman = risk_manager
        self.gov = governance
        self.cfg = cfg or {}

    def decide(
        self,
        *,
        account: dict[str, Any],
        order: dict[str, Any],
        market: dict[str, Any],
        fees_bps: float,
    ) -> tuple[bool, str, dict[str, Any], float]:
        """Return (allow, reason, obs, risk_scale)."""
        emitter = self.emitter
        tw = self.tw
        hg = self.hg
        rman = self.rman
        cfg_all = self.cfg or {}

        mode = (account or {}).get('mode', os.getenv('AURORA_MODE', 'testnet'))
        reasons: list[str] = []
        allow = True
        reason = 'ok'

        latency_ms = float(market.get('latency_ms', 0.0) or 0.0)
        slip_bps_est = float(market.get('slip_bps_est', 0.0) or 0.0)
        a_bps = float(market.get('a_bps', 0.0) or 0.0)
        b_bps = float(market.get('b_bps', 0.0) or 0.0)
        score = float(market.get('score', 0.0) or 0.0)
        regime = str(market.get('mode_regime', 'normal'))
        spread_bps = float(market.get('spread_bps', 0.0) or 0.0)
        base_notional = float((order or {}).get('base_notional', (order or {}).get('notional', 0.0)) or 0.0)

        # latency cutoff immediate
        try:
            # Prefer YAML (env overrides уже применены в cfg), затем поддержим legacy env alias
            guards_cfg_l = (cfg_all.get('guards') or cfg_all.get('gates') or {})
            l_from_cfg = guards_cfg_l.get('latency_ms_limit')
            l_from_env_legacy = os.getenv('AURORA_LMAX_MS')
            if l_from_cfg is not None:
                lmax_ms = float(l_from_cfg)
            elif l_from_env_legacy is not None and str(l_from_env_legacy).strip():
                lmax_ms = float(l_from_env_legacy)
            else:
                lmax_ms = 30.0
        except Exception:
            lmax_ms = 30.0
        if allow and not gate_latency(latency_ms=latency_ms, lmax_ms=lmax_ms, reasons=reasons):
            allow, reason = False, 'latency_guard'
            if emitter:
                try:
                    emitter.emit(
                        type="HEALTH.LATENCY_HIGH",
                        severity="warning",
                        code="HEALTH.LATENCY_HIGH",
                        payload={"latency_ms": latency_ms, "lmax_ms": float(lmax_ms)},
                    )
                except Exception:
                    pass

        # p95 guard
        if hg is not None:
            ok, p95 = hg.record(latency_ms)
            if not ok and emitter:
                try:
                    emitter.emit(
                        type="HEALTH.LATENCY_P95_HIGH",
                        severity="warning",
                        code="HEALTH.LATENCY_P95_HIGH",
                        payload={"p95_ms": p95, "threshold": hg.threshold_ms},
                    )
                except Exception:
                    pass
            ok2, reason_h = hg.enforce()
            if allow and not ok2:
                allow = False
                reason = f"latency_{reason_h}"
                reasons.append(reason)
                if emitter:
                    try:
                        emitter.emit(
                            type="AURORA.ESCALATION",
                            severity="warning",
                            code="AURORA.ESCALATION",
                            payload={"state": hg.snapshot()},
                        )
                    except Exception:
                        pass

        risk_obs = None
        risk_scale = 1.0

        # TRAP
        trap_obs = None
        trap_cancel_deltas = market.get('trap_cancel_deltas')
        trap_add_deltas = market.get('trap_add_deltas')
        trap_trades_cnt = market.get('trap_trades_cnt')
        if allow and trap_cancel_deltas is not None and trap_add_deltas is not None and trap_trades_cnt is not None:
            try:
                # Prefer cfg.trap, then env, then defaults
                trap_cfg = (cfg_all.get('trap') or {})
                z_from_cfg = trap_cfg.get('z_threshold')
                cp_from_cfg = trap_cfg.get('cancel_pctl')
                z_env = os.getenv('AURORA_TRAP_Z_THRESHOLD')
                cp_env = os.getenv('AURORA_TRAP_CANCEL_PCTL')
                if z_from_cfg is not None:
                    z_threshold = float(z_from_cfg)
                elif z_env is not None:
                    z_threshold = float(z_env)
                else:
                    z_threshold = 1.64
                if cp_from_cfg is not None:
                    cancel_pctl = int(cp_from_cfg)
                elif cp_env is not None:
                    cancel_pctl = int(cp_env)
                else:
                    cancel_pctl = 90
            except Exception:
                z_threshold, cancel_pctl = 1.64, 90

            obi_sign = market.get('obi_sign')
            tfi_sign = market.get('tfi_sign')

            cancel_d = [float(x) for x in trap_cancel_deltas]
            add_d = [float(x) for x in trap_add_deltas]
            trades_cnt = int(trap_trades_cnt)

            if tw is None:
                # defaults similar to service
                try:
                    trap_cfg_local = (cfg_all.get('trap', {}) or {})
                    window_s_local = float(trap_cfg_local.get('window_s', 2.0))
                    levels_local = int(trap_cfg_local.get('levels', 5))
                except Exception:
                    window_s_local, levels_local = 2.0, 5
                tw = TrapWindow(window_s=window_s_local, levels=levels_local)
                self.tw = tw

            cfg_all_local = cfg_all
            guards_cfg = (cfg_all_local.get('guards') or cfg_all_local.get('gates') or {})
            default_trap_on = bool(guards_cfg.get('trap_guard_enabled', True))
            if os.getenv('PYTEST_CURRENT_TEST'):
                default_trap_on = True
            trap_guard_env = os.getenv('TRAP_GUARD', 'on' if default_trap_on else 'off').lower()

            allow_trap, metrics = gate_trap(
                tw,
                cancel_deltas=cancel_d,
                add_deltas=add_d,
                trades_cnt=trades_cnt,
                z_threshold=z_threshold,
                cancel_pctl=cancel_pctl,
                obi_sign=int(obi_sign) if obi_sign is not None else None,
                tfi_sign=int(tfi_sign) if tfi_sign is not None else None,
                reasons=reasons,
            )

            # score
            try:
                from core.scalper.trap import trap_score_from_features
                cancel_sum = float(sum(max(x, 0.0) for x in cancel_d))
                add_sum = float(sum(max(x, 0.0) for x in add_d))
                denom = max(1e-6, cancel_sum + add_sum)
                cancel_ratio = cancel_sum / denom
                dt_s = getattr(tw, 'window_s', 2.0) or 2.0
                repl_rate = float(add_sum) / float(dt_s) if dt_s > 0 else 0.0
                repl_ms_proxy = 1000.0 if repl_rate <= 0 else max(0.0, 250.0 / repl_rate)
                trap_score = float(trap_score_from_features(cancel_ratio, repl_ms_proxy))
            except Exception:
                trap_score = None

            # Threshold for composite trap score: cfg.trap.score_threshold → env alias → default
            try:
                trap_cfg2 = (cfg_all.get('trap') or {})
                trap_threshold = trap_cfg2.get('score_threshold')
                if trap_threshold is None:
                    t_env = os.getenv('AURORA_TRAP_THRESHOLD')
                    trap_threshold = float(t_env) if t_env is not None else 0.8
                else:
                    trap_threshold = float(trap_threshold)
            except Exception:
                trap_threshold = 0.8
            if allow and trap_score is not None and trap_guard_env not in {'off', '0', 'false'}:
                if trap_score > trap_threshold:
                    allow = False
                    reason = 'trap_guard_score'
                    reasons.append(f"trap_guard_score:{trap_score:.2f}>{trap_threshold:.2f}")
                    if emitter:
                        try:
                            emitter.emit(
                                type="POLICY.TRAP_GUARD",
                                severity="warning",
                                code="POLICY.TRAP_GUARD",
                                payload={"trap_score": trap_score, "threshold": trap_threshold},
                            )
                        except Exception:
                            pass

            trap_obs = {
                'trap_z': metrics.trap_z,
                'cancel_rate': metrics.cancel_rate,
                'repl_rate': metrics.repl_rate,
                'n_trades': metrics.n_trades,
                'trap_score': trap_score,
            }

            if not allow_trap and trap_guard_env not in {'off', '0', 'false'}:
                allow, reason = False, 'trap_guard'
                if emitter:
                    try:
                        emitter.emit(
                            type="POLICY.TRAP_BLOCK",
                            severity="warning",
                            code="POLICY.TRAP_BLOCK",
                            payload={
                                "trap_z": metrics.trap_z,
                                "cancel_rate": metrics.cancel_rate,
                                "repl_rate": metrics.repl_rate,
                                "n_trades": metrics.n_trades,
                            },
                        )
                    except Exception:
                        pass

        # ER vs slip
        order_profile = (cfg_all.get('pretrade', {}) or {}).get('order_profile', 'er_before_slip')
        order_profile = os.getenv('PRETRADE_ORDER_PROFILE', order_profile)

        def _run_er():
            nonlocal allow, reason
            cal = IsotonicCalibrator()
            ci = CalibInput(score=score, a_bps=a_bps, b_bps=b_bps, fees_bps=fees_bps, slip_bps=slip_bps_est, regime=regime)
            out_local = cal.e_pi_bps(ci)
            try:
                # Prefer cfg.risk.pi_min_bps (env overrides уже применены), затем env alias, затем default
                pi_min_local = (cfg_all.get('risk') or {}).get('pi_min_bps')
                if pi_min_local is None:
                    env_pi = os.getenv('AURORA_PI_MIN_BPS')
                    pi_min_local = float(env_pi) if env_pi is not None else 2.0
                else:
                    pi_min_local = float(pi_min_local)
            except Exception:
                pi_min_local = 2.0
            er_ok = gate_expected_return(e_pi_bps=out_local.e_pi_bps, pi_min_bps=pi_min_local, reasons=reasons)
            if not er_ok and allow:
                allow, reason = False, 'expected_return_gate'

        def _run_slip():
            nonlocal allow, reason
            try:
                # Prefer cfg.slippage.eta_fraction_of_b → env alias → default
                eta_local = (cfg_all.get('slippage') or {}).get('eta_fraction_of_b')
                if eta_local is None:
                    env_eta = os.getenv('AURORA_SLIP_ETA')
                    eta_local = float(env_eta) if env_eta is not None else 0.3
                else:
                    eta_local = float(eta_local)
            except Exception:
                eta_local = 0.3
            if allow and not gate_slippage(slip_bps=slip_bps_est, b_bps=b_bps, eta_fraction_of_b=eta_local, reasons=reasons):
                allow, reason = False, 'slippage_guard'

        if str(order_profile).lower() == 'slip_before_er':
            _run_slip(); _run_er()
        else:
            _run_er(); _run_slip()

        # risk manager
        pnl_today_pct = market.get('pnl_today_pct')
        open_positions = market.get('open_positions')
        if allow and rman is not None:
            try:
                allow_risk, reason_r, scaled_notional, rctx = rman.decide(
                    base_notional=base_notional,
                    pnl_today_pct=float(pnl_today_pct) if pnl_today_pct is not None else None,
                    open_positions=int(open_positions) if open_positions is not None else None,
                )
                risk_obs = {'cfg': rman.snapshot(), 'ctx': rctx}
                risk_scale = float(rctx.get('size_scale', 1.0))
                if not allow_risk:
                    allow, reason = False, reason_r or 'risk_block'
                    reasons.append(reason)
            except Exception as e:
                reasons.append(f"risk_error:{e}")

        # sprt
        sprt_samples = market.get('sprt_samples')
        sprt_decision = None
        sprt_llr = None
        sprt_n = None
        if allow and sprt_samples is not None:
            sprt_enabled_env = os.getenv('AURORA_SPRT_ENABLED')
            if sprt_enabled_env is None or str(sprt_enabled_env).lower() in {"1", "true", "yes"}:
                try:
                    # Prefer cfg.sprt values (already with env overrides), then env aliases, then defaults
                    scfg_d = (cfg_all.get('sprt') or {})
                    # allow alpha/beta → A/B
                    alpha = scfg_d.get('alpha'); beta = scfg_d.get('beta')
                    sigma = scfg_d.get('sigma')
                    A = scfg_d.get('A'); B = scfg_d.get('B'); max_obs = scfg_d.get('max_obs')
                    # env aliases fallback
                    if sigma is None:
                        e = os.getenv('AURORA_SPRT_SIGMA')
                        sigma = float(e) if e is not None else 1.0
                    if A is None:
                        e = os.getenv('AURORA_SPRT_A')
                        A = float(e) if e is not None else 2.0
                    if B is None:
                        e = os.getenv('AURORA_SPRT_B')
                        B = float(e) if e is not None else -2.0
                    if max_obs is None:
                        e = os.getenv('AURORA_SPRT_MAX_OBS')
                        max_obs = int(e) if e is not None else 10
                    # alpha/beta override thresholds when present
                    if alpha is not None and beta is not None:
                        try:
                            from core.scalper.sprt import thresholds_from_alpha_beta
                            A2, B2 = thresholds_from_alpha_beta(float(alpha), float(beta))
                            A, B = A2, B2
                        except Exception:
                            pass
                    cfg_s = SprtConfig(mu0=0.0, mu1=score, sigma=sigma, A=A, B=B, max_obs=max_obs)
                    sprt = SPRT(cfg_s)
                    try:
                        timeout_ms = int(os.getenv('AURORA_SPRT_TIMEOUT_MS', '500'))
                    except Exception:
                        timeout_ms = 500
                    sprt_decision = sprt.run_with_timeout([float(x) for x in sprt_samples], time_limit_ms=timeout_ms)
                    sprt_llr = sprt.llr
                    sprt_n = sprt.n_obs
                    if sprt_decision == "REJECT":
                        allow, reason = False, 'sprt_reject'
                        reasons.append("sprt_reject")
                    elif sprt_decision == "ACCEPT":
                        reasons.append("sprt_accept")
                    else:
                        reasons.append("sprt_continue")
                except Exception:
                    reasons.append("sprt_error")

        # spread guard
        try:
            # Prefer cfg.guards/gates.spread_bps_limit (с применёнными env-override), затем legacy env aliases
            guards_cfg_s = (cfg_all.get('guards') or cfg_all.get('gates') or {})
            if 'spread_bps_limit' in guards_cfg_s:
                val = guards_cfg_s.get('spread_bps_limit')
                spread_limit_bps = float(val if val is not None else 100.0)
            else:
                env_spread_lim = os.getenv('AURORA_SPREAD_BPS_LIMIT') or os.getenv('AURORA_SPREAD_MAX_BPS')
                spread_limit_bps = float(env_spread_lim) if env_spread_lim else 100.0
        except Exception:
            spread_limit_bps = 100.0
        if spread_bps > float(spread_limit_bps):
            allow, reason = False, f'spread_bps_too_wide:{spread_bps:.1f}'

        # ICP observability (optional)
        icp_obs = None
        if os.getenv('AURORA_ICP_OBS', '0').lower() in {'1', 'true', 'yes'}:
            try:
                from certification.icp import DynamicICP
                icp = DynamicICP()
                alpha = float(icp.compute_alpha(z=market.get('z'), aci=float(market.get('aci') or 0.0)))
                icp_obs = {'alpha': alpha, 'is_transition': bool(icp._detect_transition(market.get('z')))}
            except Exception:
                icp_obs = {'alpha': None, 'is_transition': None}

        obs = {
            'gate_state': 'PASS' if allow else 'BLOCK',
            'spread_bps': spread_bps,
            'mode': mode,
            'latency_ms': latency_ms,
            'slip_bps_est': slip_bps_est,
            'a_bps': a_bps,
            'b_bps': b_bps,
            'score': score,
            'risk': risk_obs,
            'trap': trap_obs,
            'sprt': {
                'decision': sprt_decision,
                'llr': sprt_llr,
                'n_obs': sprt_n,
            },
            'reasons': reasons,
        }
        if icp_obs is not None:
            obs['icp'] = icp_obs
        # Final governance check (kill-switch, DQ, macro guards). No-op if not provided.
        if allow and self.gov is not None:
            try:
                # Compose minimal intent/risk state for governance
                intent = {
                    'account': account,
                    'order': order,
                    'market': market,
                }
                risk_state = {
                    'spread_bps': spread_bps,
                    'latency_ms': latency_ms,
                    'pnl_today_pct': market.get('pnl_today_pct'),
                    'open_positions': market.get('open_positions'),
                    'recent_stats': {'total': 0, 'rejects': 0},  # caller may override in future
                    'dq': market.get('dq') or {},
                }
                g = self.gov.approve(intent=intent, risk_state=risk_state)
                if not g.get('allow', True):
                    allow = False
                    # Prefer explicit code when available
                    g_code = g.get('code') or 'governance_block'
                    reason = str(g_code)
                    reasons.append(str(g_code))
                    # bubble up governance reasons if present
                    try:
                        for r in g.get('reasons') or []:
                            if r not in reasons:
                                reasons.append(r)
                    except Exception:
                        pass
            except Exception:
                # governance failure should not crash the gate; annotate reasons
                reasons.append('governance_error')
        # Update obs with (possibly) new reasons/allow flag
        obs['gate_state'] = 'PASS' if allow else 'BLOCK'
        obs['reasons'] = reasons

        return allow, reason, obs, risk_scale
