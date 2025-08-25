from __future__ import annotations
"""CI summary helpers (AUR-CI-701).

Provides threshold gate evaluation for replay-generated summary JSON.
"""
from typing import Tuple, List, Dict, Any
import json
from pathlib import Path
import numpy as np  # type: ignore

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

__all__ = ["check_ci_thresholds", "load_threshold_config", "apply_ci_gate", "augment_with_tvf2"]

try:
    from living_latent.core.certification.tvf2 import compute_dcts, delta_invariants, quantile_grid  # type: ignore
except Exception:  # pragma: no cover
    compute_dcts = delta_invariants = quantile_grid = None  # type: ignore


def load_threshold_config(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CI thresholds config not found: {p}")
    text = p.read_text(encoding='utf-8')
    if p.suffix.lower() in ('.yml', '.yaml'):
        if yaml is None:
            import json as _json
            # very small subset: assume valid yaml also valid json-like? fallback naive
            return _json.loads(json.dumps({l.split(':',1)[0].strip(): l.split(':',1)[1].strip() for l in text.splitlines() if ':' in l and not l.strip().startswith('#')}))
        return yaml.safe_load(text)
    return json.loads(text)


def _get(d: Dict[str, Any], path: str, default=None):
    cur: Any = d
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def check_ci_thresholds(summary: Dict[str, Any], cfg: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Evaluate summary against CI thresholds.

    Returns
    -------
    decision : str
        "pass" or "fail".
    violations : list[str]
        Keys describing violated constraints (order of detection).
    """
    violations: List[str] = []
    fail_fast = bool(cfg.get('fail_fast', True))
    # Derived targets
    alpha_target = summary.get('alpha_target') or cfg.get('alpha_target') or 0.1
    cov_emp = summary.get('coverage_empirical')
    cov_ema = summary.get('coverage_ema_final')
    cov_tol = cfg.get('coverage_tolerance', 0.03)
    cov_ema_tol = cfg.get('coverage_ema_tolerance', 0.03)
    # Conditions
    target_cov = 1 - float(alpha_target)
    if cov_emp is not None:
        if cov_emp < target_cov - cov_tol:
            violations.append('coverage_empirical')
            if fail_fast: return 'fail', violations
    if cov_ema is not None and isinstance(cov_ema, (int, float)):
        if abs(cov_ema - target_cov) > cov_ema_tol:
            violations.append('coverage_ema_final')
            if fail_fast: return 'fail', violations
    # TVF CTR
    ctr_min = cfg.get('ctr_min')
    tvf_ctr = _get(summary, 'tvf_ctr.ctr') or _get(summary, 'tvf2.ctr') or summary.get('ctr')
    if ctr_min is not None:
        try:
            if tvf_ctr is None or tvf_ctr < float(ctr_min):
                violations.append('tvf_ctr')
                if fail_fast: return 'fail', violations
        except Exception:
            violations.append('tvf_ctr')
            if fail_fast: return 'fail', violations
    # DCTS (placeholder key tvf2.dcts)
    dcts_min = cfg.get('dcts_min')
    tvf_dcts = _get(summary, 'tvf2.dcts')
    if dcts_min is not None:
        try:
            if tvf_dcts is None or tvf_dcts < float(dcts_min):
                violations.append('tvf_dcts')
                if fail_fast: return 'fail', violations
        except Exception:
            violations.append('tvf_dcts')
            if fail_fast: return 'fail', violations
    # Churn per 1k
    churn_thr = cfg.get('max_churn_per_1k')
    churn_val = summary.get('decision_churn_per_1k')
    if churn_thr is not None and churn_val is not None:
        if churn_val > float(churn_thr):
            violations.append('decision_churn_per_1k')
            if fail_fast: return 'fail', violations
    # Exec block rate
    block_thr = cfg.get('max_exec_block_rate')
    block_rate = summary.get('exec_block_rate')
    if block_thr is not None and block_rate is not None:
        if block_rate > float(block_thr):
            violations.append('exec_block_rate')
            if fail_fast: return 'fail', violations
    # Tau drift ema
    tau_thr = cfg.get('tau_drift_ema_max')
    tau_val = summary.get('tau_drift_ema') or summary.get('tau_drift_ema_final')
    if tau_thr is not None and tau_val is not None:
        try:
            if tau_val > float(tau_thr):
                violations.append('tau_drift_ema')
                if fail_fast: return 'fail', violations
        except Exception:
            violations.append('tau_drift_ema')
            if fail_fast: return 'fail', violations
    # DRO penalty ceiling (PIPE-902)
    dro_max = cfg.get('max_dro_penalty')
    dro_pen = _get(summary, 'acceptance.dro_penalty') or summary.get('dro_penalty')
    if dro_max is not None:
        try:
            if dro_pen is None or float(dro_pen) > float(dro_max):
                violations.append('dro_penalty')
                if fail_fast: return 'fail', violations
        except Exception:
            violations.append('dro_penalty')
            if fail_fast: return 'fail', violations
    decision = 'fail' if violations else 'pass'
    # Compute soft warnings (non-blocking)
    warnings = compute_warnings(summary, cfg)
    # Reflect into summary (mutate caller dict)
    summary.setdefault('ci', {})
    summary['ci']['decision'] = decision
    summary['ci']['violations'] = violations
    summary['ci']['warnings'] = warnings
    return decision, violations


def apply_ci_gate(summary_path: str | Path, cfg_path: str | Path) -> int:
    summary_p = Path(summary_path)
    if not summary_p.exists():
        print(f"[CI] Summary file not found: {summary_p}")
        return 2
    summary = json.loads(summary_p.read_text(encoding='utf-8'))
    cfg = load_threshold_config(cfg_path)
    decision, violations = check_ci_thresholds(summary, cfg)
    print(json.dumps({'ci_decision': decision, 'violations': violations}, indent=2))
    # Optionally write back enriched summary
    try:
        summary_p.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    except Exception:
        pass
    return 0 if decision == 'pass' else 2


# --- TVF2 augmentation (AUR-TVF-801) ---
def augment_with_tvf2(summary: Dict[str, Any], source_summary: Dict[str, Any] | None = None) -> None:
    """Populate summary['tvf2'] with {'ctr','dcts','delta'} if possible.

    Parameters
    ----------
    summary : target domain summary (mutated in place)
    source_summary : optional source domain summary providing qhat grid & tail snapshot
    """
    if compute_dcts is None:
        return
    tvf2: Dict[str, Any] = {}
    # CTR passthrough (keep previous if already there)
    ctr = summary.get('ctr') or (summary.get('tvf_ctr', {}) or {}).get('ctr')
    if ctr is not None:
        tvf2['ctr'] = ctr
    # DCTS (requires target residuals and source q-grid; will silently skip if compact-only)
    try:
        qhat_S = None
        if source_summary is not None:
            qhat_S = source_summary.get('icp_qhat_grid')
        if qhat_S is None:
            # attempt build from residuals_S if provided
            res_S = source_summary.get('residuals') if source_summary else None
            if res_S is not None and quantile_grid is not None:
                qhat_S = quantile_grid(np.asarray(res_S))
        res_T = summary.get('residuals')
        if res_T is not None and qhat_S and compute_dcts is not None:
            tvf2['dcts'] = compute_dcts(np.asarray(res_T), qhat_S)
    except Exception:
        pass
    # Δ-invariants
    try:
        tail_src = source_summary.get('tail_snapshot') if source_summary else None
        tail_tgt = summary.get('tail_snapshot')
        if tail_src and tail_tgt and delta_invariants is not None:
            tvf2['delta'] = delta_invariants(tail_src, tail_tgt)
        else:
            tvf2['delta'] = None
    except Exception:
        tvf2['delta'] = None
    if tvf2:
        summary['tvf2'] = tvf2


if __name__ == '__main__':  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description='Apply CI gate to summary JSON')
    ap.add_argument('--summary', required=True)
    ap.add_argument('--thresholds', default='configs/ci_thresholds.yaml')
    args = ap.parse_args()
    exit(apply_ci_gate(args.summary, args.thresholds))


# --- Soft warning helpers (AUR-CI-702) ---
def _append_warning(warnings: List[str], name: str):
    if name not in warnings:
        warnings.append(name)


def _get_ci_threshold_key(name: str):
    mapping = {
        "coverage_empirical": ("coverage_lower_band", "lower"),  # coverage_lower_band may be derived dynamically
        "ctr": ("ctr_min", "lower"),
        "dcts": ("dcts_min", "lower"),
        "decision_churn_per_1k": ("max_churn_per_1k", "upper"),
    "max_dro_penalty": ("max_dro_penalty", "upper"),  # synthetic warning key -> acceptance.dro_penalty
    }
    return mapping.get(name, (None, None))


def compute_warnings(summary: Dict[str, Any], cfg: Dict[str, Any]) -> List[str]:
    wcfg = (cfg.get("warnings") or {})
    if not wcfg:
        return []
    warn_fraction = float(wcfg.get("warn_fraction", 0.8))
    warnings: List[str] = []

    # Lower-bound metrics (value should be >= threshold)
    for name in (wcfg.get("lower_bound_metrics") or []):
        thr_key, kind = _get_ci_threshold_key(name)
        if thr_key is None:
            continue
        thr = cfg.get(thr_key)
        val = summary.get(name)
        if thr is None or val is None:
            # Special handling for coverage: dynamic target = 1 - alpha_target - coverage_tolerance
            if name == 'coverage_empirical':
                alpha_target = summary.get('alpha_target') or cfg.get('alpha_target') or 0.1
                cov_tol = cfg.get('coverage_tolerance', 0.03)
                target_cov = 1 - float(alpha_target) - float(cov_tol)
                thr = target_cov
                val = summary.get('coverage_empirical')
                if val is None:
                    continue
            else:
                continue
        try:
            thr_f = float(thr)
            val_f = float(val)
        except Exception:
            continue
        # Already a violation? skip marking as warning (handled elsewhere)
        if name == 'coverage_empirical':
            # violation logic uses target_cov - tol; we keep warning band just above that
            pass
        if val_f < thr_f and val_f >= warn_fraction * thr_f:
            _append_warning(warnings, name)

    # Upper-bound metrics (value should be <= threshold)
    for name in (wcfg.get("upper_bound_metrics") or []):
        thr_key, kind = _get_ci_threshold_key(name)
        if thr_key is None:
            continue
        thr = cfg.get(thr_key)
        if name == 'max_dro_penalty':  # map to acceptance.dro_penalty
            val = _get(summary, 'acceptance.dro_penalty')
        else:
            val = summary.get(name)
        if thr is None or val is None:
            continue
        try:
            thr_f = float(thr)
            val_f = float(val)
        except Exception:
            continue
        if val_f <= thr_f and val_f > warn_fraction * thr_f:
            _append_warning(warnings, name)
    return warnings
