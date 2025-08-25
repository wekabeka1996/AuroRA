from __future__ import annotations
import argparse
import json
import glob
from pathlib import Path
import random
import numpy as np

from living_latent.core.metrics_io import derive_calib_metrics, compute_objective_v_b008_v1
from living_latent.core.risk.tail_snapshot import snapshot_tail_metrics
from certification.tvf import compute_ctr
from living_latent.core.risk.dro_es import DROConfig, dro_es_optimize, get_scenarios
from living_latent.core.utils.io import to_compact_stats
from living_latent.core.replay.summarize import augment_with_tvf2
try:  # TVF2 utilities (optional)
    from living_latent.core.certification.tvf2 import quantile_grid
except Exception:  # pragma: no cover
    quantile_grid = None  # type: ignore

from living_latent.core.icp_dynamic import AdaptiveICP
from living_latent.core.acceptance import Acceptance, AcceptanceCfg, Event
from living_latent.core.acceptance_hysteresis import HysteresisGate, HysteresisCfg
from living_latent.obs.metrics import Metrics
from living_latent.execution.gating import RiskGate, GatingCfg, DecisionHysteresis, DwellConfig, risk_scale_from_dro

# Minimal YAML fallback if ruamel not present (we expect config existing)
try:  # pragma: no cover - import guard
    from ruamel.yaml import YAML  # type: ignore
except Exception:  # pragma: no cover
    YAML = None  # type: ignore


def load_profile(master_path: Path, profile: str) -> dict:
    if not master_path.exists():
        raise FileNotFoundError(f"master.yaml not found at {master_path}")
    if YAML is None:  # fallback to pyyaml
        import yaml as pyyaml  # type: ignore
        with open(master_path, 'r', encoding='utf-8') as f:
            data = pyyaml.safe_load(f)
    else:
        yaml = YAML(typ='safe')
        data = yaml.load(master_path.read_text(encoding='utf-8'))
    return data['profiles'][profile]


def parse_args():
    ap = argparse.ArgumentParser(description="Replay shadow logs with Adaptive ICP + Acceptance (and optional calibration)")
    ap.add_argument('--logs_dir', type=str, required=True)
    ap.add_argument('--profile', type=str, default='default')
    ap.add_argument('--config', type=str, default='living_latent/cfg/master.yaml')
    ap.add_argument('--seed', type=int, default=1337)
    ap.add_argument('--summary_out', type=str, default='run_r0_summary.json')
    # Calibration flags
    ap.add_argument('--calibrate', action='store_true', help='Enable grid calibration mode')
    ap.add_argument('--grid', type=str, default=None, help='Grid specification string k=v1,v2; or path to YAML/JSON file')
    ap.add_argument('--calib-out-dir', type=str, default='calib', help='Directory for calibration artifacts')
    ap.add_argument('--top-k', type=int, default=5)
    ap.add_argument('--objective-weights', type=str, default=None, help='Override objective weights string')
    ap.add_argument('--hard-constraints', type=str, default=None, help='Override hard constraints list string')
    # Snapshot persistence
    ap.add_argument('--load-snapshot', type=str, default=None, help='Path to snapshot JSON to load before replay')
    ap.add_argument('--save-snapshot', type=str, default=None, help='Path to snapshot JSON to save after replay')
    return ap.parse_args()


def _parse_weights(spec: str) -> dict:
    out = {}
    if not spec:
        return out
    for part in spec.split(','):
        if not part or '=' not in part:
            continue
        k, v = part.split('=', 1)
        try:
            out[k.strip()] = float(v)
        except Exception:  # pragma: no cover - defensive
            pass
    return out


def _load_grid(spec: str) -> dict:
    from pathlib import Path as _Path
    if not spec:
        return {}
    p = _Path(spec)
    if p.exists() and p.suffix.lower() in ('.yml', '.yaml', '.json'):
        if p.suffix.lower() in ('.yml', '.yaml'):
            if YAML is None:
                import yaml as pyyaml  # type: ignore
                with open(p, 'r', encoding='utf-8') as f:
                    return pyyaml.safe_load(f)
            yaml = YAML(typ='safe')
            return yaml.load(p.read_text(encoding='utf-8'))
        import json as _json
        return _json.loads(p.read_text(encoding='utf-8'))
    grid = {}
    for seg in spec.split(';'):
        seg = seg.strip()
        if not seg or '=' not in seg:
            continue
        k, vs = seg.split('=', 1)
        values = [v.strip() for v in vs.split(',') if v.strip()]
        def _coerce(x: str):
            try:
                if x.lower() in ('true', 'false'):
                    return x.lower() == 'true'
            except Exception:
                pass
            try:
                if any(c in x for c in ('.', 'e', 'E')):
                    return float(x)
                return int(x)
            except Exception:
                return x
        grid[k.strip()] = [_coerce(v) for v in values]
    return grid


def _iter_grid(grid: dict):
    if not grid:
        yield {}
        return
    from itertools import product
    keys = list(grid.keys())
    vals_list = [grid[k] for k in keys]
    for combo in product(*vals_list):
        yield {k: v for k, v in zip(keys, combo)}


def _apply_params(base_profile: dict, params: dict) -> dict:
    import copy
    prof = copy.deepcopy(base_profile)
    for full_k, val in params.items():
        path = full_k.split('.')
        cursor = prof
        try:
            for p in path[:-1]:
                cursor = cursor[p]
            cursor[path[-1]] = val
        except Exception:  # pragma: no cover - ignore invalid path
            pass
    return prof


def _parse_constraints(spec: str) -> list[str]:
    return [s.strip() for s in spec.split(',') if s.strip()]


def _evaluate_hard_constraints(constraints: list[str], metrics: dict, prof_cfg: dict) -> bool:
    coverage = metrics.get('coverage_empirical')
    surprisal = metrics.get('surprisal_p95')
    latency = metrics.get('latency_p95_ms')
    guard = prof_cfg.get('acceptance', {}).get('surprisal_p95_guard')
    slo = prof_cfg.get('acceptance', {}).get('latency_p95_max_ms')
    coverage_bound = prof_cfg.get('acceptance', {}).get('coverage_lower_bound')
    for c in constraints:
        if c.startswith('coverage>=') and coverage is not None and coverage_bound is not None:
            if coverage < coverage_bound:
                return True
        elif c.startswith('surprisal<=guard*1.05') and guard and surprisal:
            if surprisal > 1.05 * guard:
                return True
        elif c.startswith('latency<=slo*1.1') and slo and latency:
            if latency > 1.1 * slo:
                return True
    return False


def _compute_score(weights: dict, metrics: dict, prof_cfg: dict) -> float:
    w_pass = weights.get('w_pass', 1.0)
    w_derisk = weights.get('w_derisk', 0.5)
    w_block = weights.get('w_block', 2.0)
    w_viol = weights.get('w_viol', 3.0)
    w_lat = weights.get('w_lat', 1.0)
    w_sur = weights.get('w_sur', 1.0)
    w_flap = weights.get('w_flap', 0.5)
    pass_share = metrics.get('decisions_share.PASS', 0.0)
    derisk_share = metrics.get('decisions_share.DERISK', 0.0)
    block_share = metrics.get('decisions_share.BLOCK', 0.0)
    n = max(1, metrics.get('n', 1))
    viol_total = metrics.get('violations_total', 0)
    viol_rate = viol_total / n
    latency_p95 = metrics.get('latency_p95_ms', float('nan'))
    surprisal_p95 = metrics.get('surprisal_p95', float('nan'))
    flap_rate_k = metrics.get('flap_rate_k', 0.0)
    guard = prof_cfg.get('acceptance', {}).get('surprisal_p95_guard', float('nan'))
    slo = prof_cfg.get('acceptance', {}).get('latency_p95_max_ms', float('nan'))
    import math as _m
    lat_pen = max(0.0, (latency_p95 / slo - 1.0)) if slo and not _m.isnan(latency_p95) else 0.0
    sur_pen = max(0.0, (surprisal_p95 / guard - 1.0)) if guard and not _m.isnan(surprisal_p95) else 0.0
    score = (w_pass * pass_share
             - w_derisk * derisk_share
             - w_block * block_share
             - w_viol * viol_rate
             - w_lat * lat_pen
             - w_sur * sur_pen
             - w_flap * (flap_rate_k / 10.0))
    return score


def surrogate_y(mu: float, interval: tuple[float, float], rng: random.Random) -> float:
    lo, hi = interval
    mid = 0.5 * (lo + hi)
    width = hi - lo
    return rng.gauss(mid, max(1e-9, width / 4.0))


def _run_single(paths: list[str], base_profile: dict, args, tweaks: dict | None = None):
    prof_cfg = _apply_params(base_profile, tweaks or {})
    icp_cfg = prof_cfg['icp']
    acceptance_profile = prof_cfg['acceptance']
    kappa_profile = prof_cfg.get('kappa', {})
    metrics_cfg = prof_cfg.get('metrics', {})
    exec_cfg = prof_cfg.get('execution', {}).get('gating', {})
    # DRO risk adjustment config (AUR-DRO-703)
    dro_risk_cfg = prof_cfg.get('risk', {}).get('dro_risk', {}) or {}
    dro_risk_enabled = bool(dro_risk_cfg.get('enabled', False))
    dro_lambda = float(dro_risk_cfg.get('lambda', dro_risk_cfg.get('lam', 1.0)))  # sensitivity multiplier on penalty
    dro_k = float(dro_risk_cfg.get('k', 10.0))  # curvature in mapping
    dro_floor = float(dro_risk_cfg.get('floor', dro_risk_cfg.get('cap', 0.5)))  # minimum scale floor
    base_notional = float(prof_cfg.get('execution', {}).get('base_notional', exec_cfg.get('base_notional', 1.0)))
    rng = random.Random(args.seed)
    np.random.seed(args.seed)
    icp = AdaptiveICP(
        alpha_target=icp_cfg.get('alpha_target', 0.1),
        eta=icp_cfg.get('eta', 0.01),
        window=icp_cfg.get('window', 1000),
        quantile_mode=icp_cfg.get('quantile_fallback', 'p2'),
        alpha_min=icp_cfg.get('alpha_min'),
        alpha_max=icp_cfg.get('alpha_max'),
        aci_beta=icp_cfg.get('aci_beta'),
        aci_up_thresh=icp_cfg.get('aci_up_thresh'),
        alpha_k_up=icp_cfg.get('alpha_k_up'),
        cooldown_steps=icp_cfg.get('cooldown_steps'),
        decay_tau=icp_cfg.get('decay_tau'),
    )
    # --- Alpha fail-safe mode (ACI proxy correlation degrade) ---
    alpha_cfg = prof_cfg.get('alpha', {}) or {}
    proxy_cfg = alpha_cfg.get('proxy_eval', {}) or {}
    alpha_mode = alpha_cfg.get('mode', 'adaptive')
    static_alpha_value = float(alpha_cfg.get('static_value', icp_cfg.get('alpha_target', 0.1)))
    proxy_state_file = proxy_cfg.get('state_file')
    degrade_runs = int(proxy_cfg.get('degrade_runs', 3))
    recover_runs = int(proxy_cfg.get('recover_runs', 5))
    corr_min_synth = float(proxy_cfg.get('corr_min_synth', 0.60))
    corr_min_real_p25 = float(proxy_cfg.get('corr_min_real_p25', 0.30))
    proxy_state = {'mode': alpha_mode, 'fail_streak': 0, 'ok_streak': 0}
    import json as _json, numpy as _np
    if proxy_state_file:
        try:
            ps_path = Path(proxy_state_file)
            if ps_path.exists():
                loaded = _json.loads(ps_path.read_text(encoding='utf-8'))
                proxy_state.update({k: loaded.get(k, v) for k,v in proxy_state.items()})
        except Exception:
            pass
    metrics = None
    if metrics_cfg.get('enabled', False):
        buckets = dict(
            latency_buckets_ms=metrics_cfg.get('latency_buckets_ms', []),
            surprisal_buckets=metrics_cfg.get('surprisal_buckets', []),
            width_buckets=metrics_cfg.get('width_buckets', []),
            kappa_buckets=metrics_cfg.get('kappa_buckets', []),
        )
        metrics = Metrics(profile=args.profile, buckets=buckets)
    hys_cfg_raw = acceptance_profile.get('hysteresis', {})
    dwell_raw = acceptance_profile.get('dwell', {})
    gate = HysteresisGate(HysteresisCfg.from_dict(hys_cfg_raw, dwell_raw))
    acc_cfg = AcceptanceCfg(
        tau_pass=kappa_profile.get('tau_pass', 0.75),
        tau_derisk=kappa_profile.get('tau_derisk', 0.5),
        coverage_lower_bound=acceptance_profile.get('coverage_lower_bound', 0.90),
        surprisal_p95_guard=acceptance_profile.get('surprisal_p95_guard', 2.5),
        latency_p95_max_ms=acceptance_profile.get('latency_p95_max_ms', 120.0),
        max_interval_rel_width=acceptance_profile.get('max_interval_rel_width', 0.06),
        persistence_n=acceptance_profile.get('persistence_n', 20),
        penalties=acceptance_profile.get('penalties', {'latency_to_kappa_bonus': -0.05, 'coverage_deficit_bonus': -0.10}),
    )
    acceptance = Acceptance(acc_cfg, hysteresis_gate=gate, metrics=metrics, profile_label=args.profile)
    # Execution Risk Gate
    risk_gate = RiskGate(GatingCfg(
        scale_map=exec_cfg.get('scale_map', {"PASS": 1.0, "DERISK": 0.5, "BLOCK": 0.0}),
        hard_block_on_guard=exec_cfg.get('hard_block_on_guard', True),
        min_notional=float(exec_cfg.get('min_notional', 0.0)),
        max_notional=float(exec_cfg.get('max_notional', 1e12)),
    ))
    # Optional pre-load snapshot
    if tweaks is None and args.load_snapshot:
        try:  # pragma: no cover
            from living_latent.state.snapshot import load_snapshot, load_icp_state, load_acceptance_state
            icp_payload, acc_payload = load_snapshot(args.load_snapshot)
            load_icp_state(icp, icp_payload)
            load_acceptance_state(acceptance, acc_payload)
            if metrics:
                metrics.count_state_restore()
            print(f"[INFO] Loaded snapshot: {args.load_snapshot}")
        except FileNotFoundError:
            print(f"[WARN] Snapshot path not found: {args.load_snapshot}")
        except Exception as e:
            print(f"[WARN] Snapshot load failed: {e}")

    n = 0
    coverage_hits = 0
    decisions_count = {"PASS": 0, "DERISK": 0, "BLOCK": 0}
    coverage_below_streaks = 0
    kappa_plus_values = []
    dwell_cfg = dwell_raw
    dcfg = DwellConfig(
        min_dwell_pass=int(dwell_cfg.get('min_dwell_pass', 10)) if isinstance(dwell_cfg, dict) else 10,
        min_dwell_derisk=int(dwell_cfg.get('min_dwell_derisk', 10)) if isinstance(dwell_cfg, dict) else 10,
        min_dwell_block=int(dwell_cfg.get('min_dwell_block', 1)) if isinstance(dwell_cfg, dict) else 1,
    )
    decision_hys = DecisionHysteresis(dcfg)
    sum_risk_scale = 0.0
    sum_risk_scale_dro_adj_stream = 0.0  # optional streaming adjustment if dro penalty available per-event
    exec_blocks_total = 0
    exec_block_reason_counts: dict[str, int] = {}
    trigger_warn_emitted = False
    trigger_cfg = base_profile.get('r1', {}).get('text_trigger', {})
    trigger_offset = float(trigger_cfg.get('offset_s', 0))
    trigger_grace = float(trigger_cfg.get('grace_s', 0))
    trigger_deadline = None
    for p in paths:
        with open(p, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                mu = rec.get('mu'); sigma = rec.get('sigma', 0.0)
                lo = rec.get('lo'); hi = rec.get('hi')
                if mu is None or lo is None or hi is None:
                    continue
                latency_ms = rec.get('latency_ms') or rec.get('latency')
                y = rec.get('y')
                if y is None:
                    y = surrogate_y(mu, (lo, hi), rng)
                event = Event(ts=rec.get('ts', n), mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=latency_ms, y=y)
                icp.update(y, mu, sigma)
                acceptance.update(event)
                decision_raw, info = acceptance.decide(event)
                decision = decision_hys.update(decision_raw)
                decisions_count[decision] += 1
                # Guards
                try:
                    def _num(x, default):
                        try:
                            return float(x)
                        except Exception:
                            return default
                    p95_s = _num(info.get('p95_surprisal'), 0.0)
                    cov_ema_v = _num(info.get('coverage_ema'), 1.0)
                    lat_p95 = _num(info.get('latency_p95'), 0.0)
                    rel_w = _num(info.get('rel_width'), 0.0)
                    guards = {
                        'surprisal': bool(info.get('guard_surprisal', p95_s > float(acc_cfg.surprisal_p95_guard)) ),
                        'coverage': bool(info.get('guard_coverage', cov_ema_v < float(acc_cfg.coverage_lower_bound)) ),
                        'latency': bool(info.get('guard_latency', lat_p95 > float(acc_cfg.latency_p95_max_ms)) ),
                        'width': bool(info.get('guard_width', rel_w > float(acc_cfg.max_interval_rel_width)) ),
                    }
                except Exception:
                    guards = {'surprisal': False, 'coverage': False, 'latency': False, 'width': False}
                notional = risk_gate.scale(decision, guards, base_notional=base_notional)

                # (coverage monitoring handled post-summary)

                risk_scale = 0.0 if base_notional <= 0 else (notional / base_notional)
                # Streaming DRO-aware risk scaling placeholder (future enhancement).
                # If record already contains a dro_penalty field (e.g., produced upstream), apply immediate adjustment.
                if dro_risk_enabled and dro_lambda != 0.0:
                    try:
                        rec_pen = rec.get('dro_penalty')
                        if isinstance(rec_pen, (int, float)) and rec_pen >= 0:
                            adj_factor_stream = risk_scale_from_dro(rec_pen * dro_lambda, k=dro_k, cap=dro_floor)
                            sum_risk_scale_dro_adj_stream += risk_scale * adj_factor_stream
                        else:
                            # fall back accumulate neutral
                            sum_risk_scale_dro_adj_stream += risk_scale
                    except Exception:
                        sum_risk_scale_dro_adj_stream += risk_scale
                else:
                    sum_risk_scale_dro_adj_stream += risk_scale
                sum_risk_scale += risk_scale
                if notional == 0.0:
                    exec_blocks_total += 1
                    reason = (
                        'guard_surprisal' if guards['surprisal'] else
                        'guard_coverage' if guards['coverage'] else
                        'guard_latency' if guards['latency'] else
                        'guard_width' if guards['width'] else
                        'decision'
                    )
                    exec_block_reason_counts[reason] = exec_block_reason_counts.get(reason, 0) + 1
                    if metrics is not None:
                        try: metrics.count_execution_block(reason)
                        except Exception: pass
                if metrics is not None:
                    try:
                        metrics.set_execution_risk_scale(risk_scale)
                        metrics.set_decision_churn(decision_hys.churn_per_1k())
                        metrics.set_dwell_efficiency(decision_hys.dwell_efficiency())
                    except Exception:
                        pass
                kp = info.get('kappa_plus') if isinstance(info, dict) else None
                if kp is not None:
                    kappa_plus_values.append(float(kp))
                try:
                    st = icp.stats()
                    alpha = getattr(st, 'alpha', getattr(icp, 'alpha', None))
                    alpha_target = icp_cfg.get('alpha_target', 0.1)
                    cov_ema_raw = getattr(st, 'coverage_ema', acceptance.stats().get('coverage_ema'))
                    cov_ema = float(cov_ema_raw) if cov_ema_raw is not None else float('nan')
                    qhat = getattr(st, 'q_estimate', float('nan'))
                    eff_alpha = None
                    aci_signal = None
                    try:
                        eff_alpha = icp.effective_alpha()
                        aci_signal = icp.aci_ema()
                    except Exception:
                        pass
                    if metrics is not None and alpha is not None:
                        acceptance.set_icp_stats(alpha=float(alpha), alpha_target=float(alpha_target), coverage_ema=cov_ema)
                        try:
                            metrics.set_icp_live_extras(alpha_eff=float(eff_alpha) if eff_alpha is not None else float(alpha), qhat=float(qhat) if qhat is not None else None)
                            metrics.set_icp_aci(aci_signal)
                        except Exception:
                            pass
                except Exception:
                    pass
                if lo <= y <= hi:
                    coverage_hits += 1
                n += 1
                if acceptance.state.coverage_below_streak and acceptance.state.coverage_below_streak % acceptance.state.cfg.persistence_n == 0:
                    coverage_below_streaks += 1
                if trigger_deadline is None:
                    try:
                        ts0 = float(event.ts)
                        trigger_deadline = ts0 + trigger_offset + trigger_grace
                    except Exception:
                        trigger_deadline = None
                if (not trigger_warn_emitted) and trigger_deadline is not None and event.ts >= trigger_deadline:
                    print(json.dumps({'warn': 'text_trigger_missing', 'ts': event.ts, 'deadline': trigger_deadline}))
                    trigger_warn_emitted = True

    empirical_cov = coverage_hits / n if n else float('nan')
    stats = acceptance.stats()
    alpha_final = getattr(icp, 'alpha', float('nan'))
    total = max(1, sum(decisions_count.values()))
    decisions_share = {k: v / total for k, v in decisions_count.items()}
    import numpy as _np
    if kappa_plus_values:
        arr = _np.array(kappa_plus_values)
        avg_kp = float(arr.mean())
        median_kp = float(_np.quantile(arr, 0.5))
        p10_kp = float(_np.quantile(arr, 0.10))
        p90_kp = float(_np.quantile(arr, 0.90))
    else:
        avg_kp = median_kp = p10_kp = p90_kp = float('nan')
    metrics_out = {
        'n': n,
        'profile': args.profile,
        'coverage_empirical': empirical_cov,
        'surprisal_p95': stats.get('surprisal_p95'),
        'latency_p95_ms': stats.get('latency_p95'),
        'decisions_share.PASS': decisions_share.get('PASS', 0.0),
        'decisions_share.DERISK': decisions_share.get('DERISK', 0.0),
        'decisions_share.BLOCK': decisions_share.get('BLOCK', 0.0),
        'violations_total': coverage_below_streaks,
        'viol_coverage': coverage_below_streaks,
        'viol_surprisal': 0,
        'viol_latency': 0,
        'viol_width': 0,
        'avg_kappa_plus': avg_kp,
        'median_kappa_plus': median_kp,
        'p10_kappa_plus': p10_kp,
        'p90_kappa_plus': p90_kp,
        'transitions_total': decision_hys.transitions,
        'flap_rate_k': decision_hys.churn_per_1k(),
        'decision_churn_per_1k': decision_hys.churn_per_1k(),
        'dwell_efficiency': decision_hys.dwell_efficiency(),
        'alpha_final': alpha_final,
        'icp_qhat': getattr(icp.stats(), 'q_estimate', float('nan')),
        'coverage_ema_final': acceptance.stats().get('coverage_ema'),
        'alpha_target': icp_cfg.get('alpha_target', 0.1),
        'avg_risk_scale': (sum_risk_scale / n) if n else float('nan'),
        'exec_block_rate': (exec_blocks_total / n) if n else 0.0,
    }
    for r, c in exec_block_reason_counts.items():
        metrics_out[f'exec_block_rate.{r}'] = c / n if n else 0.0
    for k, v in (tweaks or {}).items():
        metrics_out[k] = v
    if tweaks is None and args.save_snapshot:
        try:  # pragma: no cover
            from living_latent.state.snapshot import save_snapshot, make_icp_state, make_acceptance_state
            save_snapshot(args.save_snapshot, make_icp_state(icp), make_acceptance_state(acceptance))
            if metrics: metrics.count_state_save()
            print(f"[INFO] Saved snapshot: {args.save_snapshot}")
        except Exception as e:
            print(f"[WARN] Snapshot save failed: {e}")
    return metrics_out, prof_cfg, metrics


def main():
    args = parse_args()
    base_profile_cfg = load_profile(Path(args.config), args.profile)
    # Global DRO risk adjustment config for summary-level post-hoc scaling
    dro_risk_cfg = base_profile_cfg.get('risk', {}).get('dro_risk', {}) or {}
    dro_risk_enabled = bool(dro_risk_cfg.get('enabled', False))
    dro_lambda = float(dro_risk_cfg.get('lambda', dro_risk_cfg.get('lam', 1.0)))
    dro_k = float(dro_risk_cfg.get('k', 10.0))
    dro_floor = float(dro_risk_cfg.get('floor', dro_risk_cfg.get('cap', 0.5)))
    calib_defaults = base_profile_cfg.get('calibration', {})
    paths = sorted(glob.glob(str(Path(args.logs_dir) / 'pred_*.jsonl')))
    if not paths:
        paths = sorted(glob.glob(str(Path(args.logs_dir) / '*.jsonl')))
    if not paths:
        raise SystemExit('No shadow log files found.')
    if not args.calibrate:
        metrics_out, prof_cfg, metrics_ref = _run_single(paths, base_profile_cfg, args, tweaks=None)
        # Prepare alpha fail-safe configuration (ACI proxy correlation monitoring)
        alpha_cfg = (prof_cfg.get('alpha') or {}) if isinstance(prof_cfg, dict) else {}
        proxy_cfg = (alpha_cfg.get('proxy_eval') or {}) if isinstance(alpha_cfg, dict) else {}
        alpha_mode = alpha_cfg.get('mode', 'adaptive')
        static_alpha_value = float(alpha_cfg.get('static_value', alpha_cfg.get('alpha_target', 0.1)))
        proxy_state_file = proxy_cfg.get('state_file')
        degrade_runs = int(proxy_cfg.get('degrade_runs', 3))
        recover_runs = int(proxy_cfg.get('recover_runs', 5))
        corr_min_synth = float(proxy_cfg.get('corr_min_synth', 0.60))
        corr_min_real_p25 = float(proxy_cfg.get('corr_min_real_p25', 0.30))
        proxy_state = {'mode': alpha_mode, 'fail_streak': 0, 'ok_streak': 0}
        import json as _json, numpy as _np  # local aliases for fail-safe logic
        if proxy_state_file:
            try:
                _ps_path = Path(proxy_state_file)
                if _ps_path.exists():
                    _loaded = _json.loads(_ps_path.read_text(encoding='utf-8'))
                    proxy_state.update({k: _loaded.get(k, v) for k, v in proxy_state.items()})
            except Exception:
                pass
        decisions_share = {
            'PASS': metrics_out.get('decisions_share.PASS', 0.0),
            'DERISK': metrics_out.get('decisions_share.DERISK', 0.0),
            'BLOCK': metrics_out.get('decisions_share.BLOCK', 0.0),
        }
        summary = {
            'n': metrics_out['n'],
            'coverage_empirical': round(metrics_out.get('coverage_empirical', float('nan')), 6),
            'surprisal_p95': round(metrics_out.get('surprisal_p95', float('nan')), 6),
            'latency_p95_ms': round(metrics_out.get('latency_p95_ms', float('nan')), 6),
            'decisions_share': decisions_share,
            'alpha_final': round(metrics_out.get('alpha_final', float('nan')), 6),
            'alpha_target': round(metrics_out.get('alpha_target', float('nan')), 6),
            'icp_qhat': round(metrics_out.get('icp_qhat', float('nan')), 6),
            'coverage_ema_final': round(metrics_out.get('coverage_ema_final', float('nan')), 6),
            'violations': {'coverage_below_bound_streaks': metrics_out.get('violations_total', 0)},
            'avg_risk_scale': round(metrics_out.get('avg_risk_scale', float('nan')), 6),
            'exec_block_rate': round(metrics_out.get('exec_block_rate', float('nan')), 6),
            'exec_block_rate_by_reason': {k.split('.', 1)[1]: round(v, 6) for k, v in metrics_out.items() if k.startswith('exec_block_rate.')},
            'decision_churn_per_1k': round(metrics_out.get('decision_churn_per_1k', float('nan')), 6),
            'dwell_efficiency': round(metrics_out.get('dwell_efficiency', float('nan')), 6),
        }
        # Synthetic CTR & tail snapshot placeholders
        try:
            # --- Coverage monitoring (COVERAGE-MONITORING) ---
            try:
                ci_cov_cfg = base_profile_cfg.get('ci_gating', {}).get('coverage', {}) or {}
                beta = float(ci_cov_cfg.get('ema_beta', 0.2))
                cov_emp = summary.get('coverage_empirical')
                alpha_t = summary.get('alpha_target')
                if isinstance(cov_emp, (int, float)) and isinstance(alpha_t, (int, float)):
                    target_cov = 1.0 - alpha_t
                    if np.isfinite(cov_emp) and np.isfinite(target_cov):
                        abs_err = abs(cov_emp - target_cov)
                        prev_ema = None
                        # Optional persistence
                        state_path = ci_cov_cfg.get('ema_state_file')
                        if state_path:
                            try:
                                sp = Path(state_path)
                                if sp.exists():
                                    prev_ema = float(json.loads(sp.read_text(encoding='utf-8')).get('coverage_abs_err_ema'))
                            except Exception:
                                prev_ema = None
                        if prev_ema is None or not np.isfinite(prev_ema):
                            ema = abs_err
                        else:
                            ema = beta * abs_err + (1 - beta) * prev_ema
                        summary['coverage_abs_err'] = round(abs_err, 6)
                        summary['coverage_abs_err_ema'] = round(ema, 6)
                        if metrics_ref is not None:
                            try:
                                metrics_ref.set_coverage_abs_err(abs_err)
                                metrics_ref.set_coverage_abs_err_ema(ema)
                            except Exception:
                                pass
                        if state_path:
                            try:
                                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                                Path(state_path).write_text(json.dumps({'coverage_abs_err_ema': ema}), encoding='utf-8')
                            except Exception:
                                pass
            except Exception:
                pass
            residuals_src = []
            residuals_tgt = []
            count_limit = 5000
            processed = 0
            with open(paths[0], 'r', encoding='utf-8') as f0:
                for line in f0:
                    if processed >= count_limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    mu = rec.get('mu'); lo = rec.get('lo'); hi = rec.get('hi'); y = rec.get('y')
                    if mu is None or lo is None or hi is None:
                        continue
                    if y is None:
                        y = surrogate_y(mu, (lo, hi), random.Random(0))
                    r = y - mu
                    residuals_src.append(r); residuals_tgt.append(r)
                    processed += 1
            if len(residuals_src) >= 100 and len(residuals_tgt) >= 100:
                ctr_res = compute_ctr(residuals_src, residuals_tgt, alpha=0.1)
                summary['tvf_ctr'] = ctr_res.as_dict()
                # Gauge for CTR
                try:
                    if metrics_ref is not None:
                        metrics_ref.set_tvf_ctr(summary['tvf_ctr'].get('ctr'))
                except Exception:
                    pass
                # Persist residuals & quantile grid for TVF2 augmentation downstream
                # Truncate residuals to avoid huge summaries
                summary['residuals'] = residuals_tgt[:1000]
                if quantile_grid is not None:
                    try:
                        summary['icp_qhat_grid'] = quantile_grid(np.asarray(residuals_src), alphas=(0.05, 0.1, 0.2, 0.3))
                    except Exception:  # pragma: no cover
                        pass
        except Exception as e:
            summary['tvf_ctr_error'] = str(e)
        try:
            kappa_vals = [v for v in (metrics_out.get('avg_kappa_plus'), metrics_out.get('median_kappa_plus'),
                                      metrics_out.get('p10_kappa_plus'), metrics_out.get('p90_kappa_plus'))
                          if isinstance(v, (int, float)) and not np.isnan(v)]
            if len(kappa_vals) >= 4:
                snap = snapshot_tail_metrics(np.asarray(kappa_vals), regime=args.profile)
                summary['tail_snapshot'] = snap
        except Exception as e:  # pragma: no cover
            summary['tail_snapshot_error'] = str(e)
        # Auto-TVF2 augmentation (AUR-TVF-802)
        try:
            augment_with_tvf2(summary, source_summary=summary)
        except Exception as _e:  # pragma: no cover
            summary.setdefault('tvf2_error', str(_e))
        if 'tvf2' not in summary:
            summary['tvf2'] = None
        # Export DCTS gauge if available (legacy basic export kept for backward compat)
        try:
            if metrics_ref is not None:
                tvf2_block = summary.get('tvf2')
                if isinstance(tvf2_block, dict):
                    metrics_ref.set_tvf_dcts(tvf2_block.get('dcts'))
                    metrics_ref.set_tvf_dcts_robust(
                        (tvf2_block.get('dcts_robust') or {}).get('value') if isinstance(tvf2_block.get('dcts_robust'), dict) else None
                    )
                    metrics_ref.set_tvf_dcts_grids(tvf2_block.get('dcts_grids'))
        except Exception:  # pragma: no cover
            pass
        # Robust DCTS (AUR-DCTS-901 REAL multigrid)
        try:
            from living_latent.core.tvf2.dcts_multigrid import DCTSGridConfig, compute_dcts_multigrid
            tvf2_cfg = base_profile_cfg.get('tvf2', {}).get('dcts', {}) or {}
            grids = tvf2_cfg.get('grids', [0.5, 1.0, 2.0])
            aggregator = str(tvf2_cfg.get('aggregator', 'median_min'))
            base_window = int(tvf2_cfg.get('base_window', 20))
            tvf2_block = summary.get('tvf2') or {}
            # Need raw residuals and qhat_S to recompute across grids => rely on stored data in summary if present
            res_T = summary.get('residuals_T') or summary.get('residuals_target')
            qhat_S = (summary.get('tvf2') or {}).get('qhat_S')  # if earlier code persisted it
            # Fallback: if no raw artifacts, skip (keep previous dcts only)
            if isinstance(res_T, list) and isinstance(qhat_S, dict):
                import numpy as _np
                res_arr = _np.asarray(res_T, dtype=float)
                cfg_obj = DCTSGridConfig(grids=list(grids), base_window=base_window, aggregator=aggregator)
                mg = compute_dcts_multigrid(res_arr, qhat_S, cfg_obj)
                existing_tvf2 = summary.get('tvf2')
                if not isinstance(existing_tvf2, dict):
                    existing_tvf2 = {}
                    summary['tvf2'] = existing_tvf2
                grids_map = mg.get('grids') if isinstance(mg, dict) else None
                robust_block = mg.get('robust') if isinstance(mg, dict) else None
                min_block = mg.get('min') if isinstance(mg, dict) else None
                if isinstance(grids_map, dict):
                    existing_tvf2['dcts_grids'] = grids_map
                if isinstance(robust_block, dict):
                    existing_tvf2['dcts_robust'] = robust_block
                    if 'value' in robust_block:
                        existing_tvf2['dcts_robust_value'] = robust_block['value']
                if isinstance(min_block, dict):
                    existing_tvf2['dcts_min'] = min_block
                # Add meta trace (LOG-AGG-META)
                try:
                    meta = {
                        'aggregator': aggregator,
                        'grids': list(grids),
                        'source': 'robust' if 'dcts_robust' in existing_tvf2 else 'fallback'
                    }
                    existing_tvf2['dcts_meta'] = meta
                except Exception:
                    pass
                # Extended meta export (to be added in later task if not present)
                try:
                    obs_prom = base_profile_cfg.get('observability', {}).get('prometheus', {})
                    dcts_export_cfg = obs_prom.get('tvf2_dcts_export', {}) if isinstance(obs_prom, dict) else {}
                    if metrics_ref is not None and dcts_export_cfg.get('enabled'):
                        metrics_ref.export_tvf_dcts_layer(
                            base=existing_tvf2.get('dcts'),
                            robust=existing_tvf2.get('dcts_robust_value'),
                            dmin=(existing_tvf2.get('dcts_min') or {}).get('value') if isinstance(existing_tvf2.get('dcts_min'), dict) else None,
                            grids=existing_tvf2.get('dcts_grids'),
                            export_grids=bool(dcts_export_cfg.get('export_grids'))
                        )
                except Exception:
                    pass
            else:  # degrade gracefully
                summary.setdefault('tvf2_robust_error', 'missing_residuals_or_qhat_source')
        except Exception as _dcts_err:  # pragma: no cover
            summary.setdefault('tvf2_robust_error', str(_dcts_err))
        # DCTS divergence early alert (ALERT-DCTS-DIVERGENCE)
        try:
            div_cfg_block = base_profile_cfg.get('ci_gating', {}).get('dcts_divergence', {}) or {}
            if div_cfg_block.get('enabled'):
                from living_latent.core.ci.dcts_divergence import DCTSDivergenceConfig, DCTSDivergenceMonitor
                persistence_file = div_cfg_block.get('persistence_file')
                cfg_obj = DCTSDivergenceConfig(
                    enabled=True,
                    abs_delta_max=float(div_cfg_block.get('abs_delta_max', 0.08)),
                    rel_delta_max=float(div_cfg_block.get('rel_delta_max', 0.15)),
                    window_runs=int(div_cfg_block.get('window_runs', 5)),
                    min_breaches=int(div_cfg_block.get('min_breaches', 3)),
                    persistence_file=Path(persistence_file) if persistence_file else None
                )
                monitor = DCTSDivergenceMonitor(cfg_obj)
                tvf2_raw = summary.get('tvf2')
                tvf2_block = tvf2_raw if isinstance(tvf2_raw, dict) else {}
                base_val = tvf2_block.get('dcts') if tvf2_block else None
                robust_val = tvf2_block.get('dcts_robust_value') if tvf2_block else None
                obs_res = monitor.observe(base_val, robust_val)
                if obs_res:
                    summary.setdefault('alerts', {})['dcts_divergence'] = obs_res
                    if monitor.should_alert():
                        # Emit pseudo-event structure
                        ev = {
                            'type': 'DIV-DCTS',
                            'message': 'Robust DCTS diverges from base beyond configured bounds',
                            'delta': obs_res.get('delta'),
                            'rel_delta': obs_res.get('rel_delta'),
                            'thresholds': {
                                'abs_delta_max': cfg_obj.abs_delta_max,
                                'rel_delta_max': cfg_obj.rel_delta_max
                            }
                        }
                        summary.setdefault('ci_gating_events', []).append(ev)
                        if metrics_ref is not None:
                            try:
                                metrics_ref.inc_ci_gating_violation('dcts_divergence')
                            except Exception:
                                pass
        except Exception as _div_err:  # pragma: no cover
            summary.setdefault('dcts_divergence_error', str(_div_err))
        # --- DRO penalty integration (AUR-PIPE-902) ---
        try:
            history = np.asarray(summary.get('residuals') or [], dtype=float)
            tail_snap = summary.get('tail_snapshot') or {}
            sources = {
                'history': history,
                'teacher_extremes': np.array([], dtype=float),
                'xi_hat': tail_snap.get('xi', 0.0),
                'scale_tail': float(np.std(history[-2048:])) if history.size > 0 else 0.02,
            }
            scen = get_scenarios(n=1024, regime=summary.get('regime', 'unknown'), sources=sources, p_ext=0.10, seed=42)
            losses = -scen
            dro_cfg = DROConfig(alpha=0.10, eps_mode='fixed', eps=0.02)
            alpha_dro = dro_cfg.alpha
            k_es = max(1, int(np.ceil((1.0 - alpha_dro) * losses.size)))
            es_alpha = float(np.mean(np.sort(losses)[-k_es:]))
            tail_snapshot = dict(tail_snap)
            tail_snapshot.setdefault('es_alpha', es_alpha)
            dro_res = dro_es_optimize(scen, dro_cfg, tail_snapshot=tail_snapshot)
            summary.setdefault('acceptance', {})
            summary['acceptance'].update({
                'dro_penalty': dro_res['objective'],
                'dro_cvar': dro_res['cvar'],
                'dro_eps': dro_res['eps'],
                'dro_tail_proxy': dro_res['tail_proxy'],
                'dro_status': dro_res['status'],
            })
            if metrics_ref is not None:
                try:
                    from living_latent.core.utils.metrics import set_dro_objective, set_dro_runtime_ms, set_dro_penalty
                    set_dro_objective(dro_res['objective'])
                    set_dro_runtime_ms(dro_res['runtime_ms'])
                    set_dro_penalty(dro_res['objective'])
                except Exception:
                    pass
            if dro_risk_enabled and dro_lambda != 0.0:
                try:
                    dro_pen = float(dro_res['objective'])
                    factor = risk_scale_from_dro(dro_pen * dro_lambda, k=dro_k, cap=dro_floor)
                    summary['avg_risk_scale_dro_factor'] = factor
                    base_avg = summary.get('avg_risk_scale')
                    if isinstance(base_avg, (int, float)):
                        summary['avg_risk_scale_dro_adj'] = round(base_avg * factor, 6)
                        # Export DRO adjustment gauges
                        if metrics_ref is not None:
                            try:
                                metrics_ref.set_dro_risk_adjustment(base=base_avg, factor=factor, adj=base_avg * factor)
                            except Exception:
                                pass
                    else:
                        summary['avg_risk_scale_dro_adj'] = None
                except Exception as _e:
                    summary.setdefault('dro_adjust_error', str(_e))
        except Exception as e:  # pragma: no cover
            summary.setdefault('dro_error', str(e))
        # Residuals compaction (OBS-614)
        try:
            res_arr = summary.get('residuals')
            if isinstance(res_arr, list) and len(res_arr) > 1000:
                summary['residuals_compact'] = to_compact_stats(np.asarray(res_arr, dtype=float))
                summary['residuals_saved'] = 'compact'
                summary.pop('residuals', None)
        except Exception:  # pragma: no cover
            pass
        with open(args.summary_out, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
        print(json.dumps(summary, indent=2))
        # Evaluate alpha fail-safe triggers based on previously persisted ACI proxy eval report if present
        try:
            if proxy_state_file:
                report_path = Path('artifacts/aci_eval/report.json')
                degraded = False
                ok = False
                if report_path.exists():
                    rep = _json.loads(report_path.read_text(encoding='utf-8'))
                    synth_corrs_raw = [r.get('corr') for r in (rep.get('synthetic') or []) if isinstance(r, dict)]
                    synth_corrs = [float(c) for c in synth_corrs_raw if isinstance(c, (int, float))]
                    median_corr_synth = float(_np.median(_np.array(synth_corrs, dtype=float))) if synth_corrs else float('nan')
                    real_block = rep.get('real') or {}
                    p25_corr_real = real_block.get('p25') if isinstance(real_block, dict) else None
                    degraded = ((isinstance(median_corr_synth,(int,float)) and _np.isfinite(median_corr_synth) and median_corr_synth < corr_min_synth) or
                                (isinstance(p25_corr_real,(int,float)) and p25_corr_real < corr_min_real_p25))
                    ok = ((isinstance(median_corr_synth,(int,float)) and _np.isfinite(median_corr_synth) and median_corr_synth >= corr_min_synth) and
                          (isinstance(p25_corr_real,(int,float)) and p25_corr_real >= corr_min_real_p25))
                if degraded:
                    proxy_state['fail_streak'] = proxy_state.get('fail_streak',0) + 1
                    proxy_state['ok_streak'] = 0
                elif ok:
                    proxy_state['ok_streak'] = proxy_state.get('ok_streak',0) + 1
                    proxy_state['fail_streak'] = 0
                mode_before = proxy_state.get('mode', alpha_mode)
                mode_after = mode_before
                if mode_before == 'adaptive' and proxy_state['fail_streak'] >= degrade_runs:
                    mode_after = 'static'
                elif mode_before == 'static' and proxy_state['ok_streak'] >= recover_runs:
                    mode_after = 'adaptive'
                proxy_state['mode'] = mode_after
                summary.setdefault('alpha_mode', mode_after)
                if mode_after == 'static':
                    summary['alpha_static_value'] = static_alpha_value
                try:
                    Path(proxy_state_file).parent.mkdir(parents=True, exist_ok=True)
                    Path(proxy_state_file).write_text(_json.dumps(proxy_state), encoding='utf-8')
                except Exception:
                    pass
                if mode_before != mode_after:
                    tag = 'DEGRADE' if mode_after == 'static' else 'RECOVER'
                    print(f"[ALPHA-{tag}] mode {mode_before}->{mode_after} fail_streak={proxy_state['fail_streak']} ok_streak={proxy_state['ok_streak']}")
                with open(args.summary_out, 'w', encoding='utf-8') as f2:
                    json.dump(summary, f2, indent=2)
        except Exception as _afe:  # pragma: no cover
            summary.setdefault('alpha_fail_safe_error', str(_afe))
        # --- CI Soft Gating (post-summary) ---
        try:
            ci_cfg = base_profile_cfg.get('ci_gating', {}) or {}
            if ci_cfg.get('enabled'):
                from living_latent.core.ci.gating import CIGatingStateMachine, MetricSpec
                # Load thresholds YAML if present
                import os
                thr_path = os.environ.get('CI_THRESHOLDS_PATH', 'configs/ci_thresholds.yaml')
                thresholds = {}
                if Path(thr_path).exists():
                    try:
                        if thr_path.endswith(('.yml','.yaml')):
                            if YAML is None:
                                import yaml as pyyaml  # type: ignore
                                thresholds = pyyaml.safe_load(Path(thr_path).read_text(encoding='utf-8')) or {}
                            else:
                                _yaml = YAML(typ='safe')
                                thresholds = _yaml.load(Path(thr_path).read_text(encoding='utf-8')) or {}
                        else:
                            import json as _json
                            thresholds = _json.loads(Path(thr_path).read_text(encoding='utf-8')) or {}
                    except Exception:
                        thresholds = {}
                specs = []
                # Hard override logic
                hard_override = ci_cfg.get('hard_override', 'auto')
                hard_meta = thresholds.get('hard_meta', {}) if isinstance(thresholds, dict) else {}
                promote_all = (hard_override == 'force_on')
                suppress_all = (hard_override == 'force_off')
                for m in ci_cfg.get('metrics', []):
                    try:
                        hc_flag = bool(m.get('hard_candidate', False))
                        # If thresholds contain hard_meta entry for the flat key referenced by threshold_key leaf -> treat as enabled hard
                        # Extract flat key (last segment after '.')
                        flat_key = m.get('threshold_key','').split('.')[-1]
                        hard_enabled_meta = hard_meta.get(flat_key, {}).get('hard_enabled') if isinstance(hard_meta, dict) else False
                        if promote_all and hc_flag:
                            hard_enabled_meta = True
                        if suppress_all:
                            hard_enabled_meta = False
                        specs.append(MetricSpec(
                            name=m['name'], source_key=m['source_key'], threshold_key=m['threshold_key'],
                            relation=m.get('relation','<='), hard_candidate=bool(hc_flag and hard_enabled_meta)
                        ))
                    except Exception:
                        pass
                persistence_file = ci_cfg.get('persistence_file')
                persistence_path = Path(persistence_file) if persistence_file else None
                sm = CIGatingStateMachine(ci_cfg, specs, persistence_path=persistence_path, metrics_exporter=metrics_ref)
                run_id = f"run_{__import__('datetime').datetime.utcnow().strftime('%Y%m%dT%H%M%S')}"
                events = sm.evaluate_batch(run_id, summary, thresholds)
                if ci_cfg.get('hard_enabled') and sm.any_hard_failure(events):
                    summary['ci_hard_failed'] = True
                summary['ci_gating_events'] = [e.__dict__ for e in events]
                # rewrite summary including gating events
                with open(args.summary_out, 'w', encoding='utf-8') as f2:
                    json.dump(summary, f2, indent=2)
                if summary.get('ci_hard_failed'):
                    # Emit explicit log line
                    print('[CI-GATING][HARD] Hard gating failure detected -> exiting with code 3')
                    # Exit after flushing
                    raise SystemExit(3)
        except Exception as _g_err:  # pragma: no cover
            summary['ci_gating_error'] = str(_g_err)
            try:
                with open(args.summary_out, 'w', encoding='utf-8') as f3:
                    json.dump(summary, f3, indent=2)
            except Exception:
                pass
        return

    # Calibration mode
    grid_spec = _load_grid(args.grid or '')
    if args.objective_weights:
        weights = _parse_weights(args.objective_weights)
    else:
        weights = calib_defaults.get('objective_weights', {})
    if args.hard_constraints:
        constraints = _parse_constraints(args.hard_constraints)
    else:
        constraints = calib_defaults.get('hard_constraints', [])
    from pathlib import Path as _P
    out_dir = _P(args.calib_out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, tweaks in enumerate(_iter_grid(grid_spec)):
        print(json.dumps({'combo_id': idx, 'params': tweaks, 'seed': args.seed}))
        try:
            metrics_out, prof_cfg, _ = _run_single(paths, base_profile_cfg, args, tweaks=tweaks)
            violated = _evaluate_hard_constraints(constraints, metrics_out, prof_cfg)
            score = -1e9 if violated else _compute_score(weights, metrics_out, prof_cfg)
            calib_record = {
                'decisions_share.PASS': metrics_out.get('decisions_share.PASS'),
                'decisions_share.DERISK': metrics_out.get('decisions_share.DERISK'),
                'decisions_share.BLOCK': metrics_out.get('decisions_share.BLOCK'),
                'surprisal_p95': metrics_out.get('surprisal_p95'),
                'latency_p95_ms': metrics_out.get('latency_p95_ms'),
                'violations_total': metrics_out.get('violations_total'),
            }
            norm = derive_calib_metrics(calib_record)
            objective_v_b008_v1 = compute_objective_v_b008_v1(norm)
            for k, v in norm.items():
                metrics_out[f'norm_{k}'] = v
            metrics_out['objective_v_b008_v1'] = objective_v_b008_v1
            print(json.dumps({'combo_id': idx, 'objective_v_b008_v1': objective_v_b008_v1, **{f'n_{k}': v for k, v in norm.items()}}))
            metrics_out['score'] = score
            rows.append(metrics_out)
        except Exception as e:  # pragma: no cover
            err_row = {'score': float('-inf'), 'error': str(e), **{k: v for k, v in tweaks.items()}}
            rows.append(err_row)
    import csv
    if rows:
        all_keys = set()
        for r in rows: all_keys.update(r.keys())
        fieldnames = sorted(all_keys)
        with open(out_dir / 'calib_results.csv', 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader(); [w.writerow(r) for r in rows]
        topk = sorted(rows, key=lambda x: x.get('score', float('-inf')), reverse=True)[:args.top_k]
        top_payload = {
            'timestamp': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
            'base_profile': args.profile,
            'objective': 'score_v1',
            'weights': weights,
            'hard_constraints': constraints,
            'items': [
                {
                    'params': {k: r.get(k) for k in grid_spec},
                    'metrics': {mk: r.get(mk) for mk in [
                        'coverage_empirical', 'surprisal_p95', 'latency_p95_ms',
                        'decisions_share.PASS', 'decisions_share.DERISK', 'decisions_share.BLOCK', 'score'
                    ]},
                    'score': r.get('score')
                } for r in topk
            ]
        }
        with open(out_dir / 'calib_topk.json', 'w', encoding='utf-8') as f:
            json.dump(top_payload, f, indent=2)
        print(f"Calibration complete: {len(rows)} combos -> {out_dir/'calib_results.csv'}")


if __name__ == '__main__':  # pragma: no cover
    main()
