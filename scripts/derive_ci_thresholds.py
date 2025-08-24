#!/usr/bin/env python
"""Derive suggested CI gating thresholds from historical replay summary_*.json files.

Usage:
    python scripts/derive_ci_thresholds.py \
        --summaries artifacts/replay_reports \
        --out configs/ci_thresholds.yaml \
        [--alpha-target 0.10] [--force] [--current configs/ci_thresholds.yaml] \
        [--dryrun] [--report artifacts/ci_thresholds/report.json] [--min-eligible-ratio 0.7]

Production formulas (AUR-CI-705 hardening):
    coverage_tolerance = clamp( p95(|coverage_empirical - (1-alpha_target)|), 0.02, 0.05 )
    ctr_min            = max(0.95, p10(ctr))                                 (if ctr present)
    dcts_min           = max(0.90, p10(dcts))                                (ratchet upward later)
    max_churn_per_1k   = clamp( 1.10 * p95(decision_churn_per_1k), 15, 40 )
    max_dro_penalty    = 1.10 * p95(dro_penalty)                             (warn-only initially)
    tau_drift_ema_max  = clamp(1.25 * p95(tau_drift_ema), 0.01, 0.05)        (if metric present)

Rules:
    - Metrics computed only if >=5 finite samples for that metric (robust quantiles).
    - NaN / missing values ignored per metric independently.
    - If insufficient samples -> key reported as null with status 'insufficient_samples'.

Enhancements:
    - --dryrun prevents overwriting --out; still emits diff report JSON.
    - --current allows diffing against an existing thresholds YAML.
    - Diff report enumerates status per key: added/removed/changed/unchanged/insufficient_samples.
    - Eligible ratio (share of keys with newly derived numeric thresholds) enforced via --min-eligible-ratio.
    - Report JSON (default artifacts/ci_thresholds/report.json) stores full metadata + diff summary.

Exit codes:
    0 success (eligible ratio OK)
    2 eligible ratio below threshold or dryrun (informational) *still prints report*
    3 unexpected error
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Tuple
import statistics as stats
import yaml

# ------------------ Core percentile helpers ------------------

def percentile(values: List[float], p: float) -> float:
    vals = [v for v in values if math.isfinite(v)]
    if not vals:
        return float('nan')
    vals.sort()
    k = (len(vals)-1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(vals[int(k)])
    return float(vals[f] + (k - f) * (vals[c] - vals[f]))

# ------------------ Data collection ------------------

def collect_summaries(path: Path) -> List[Dict[str, Any]]:
    """Collect summary_*.json records.

    Flexible semantics:
      * If 'path' is an existing directory -> scan for summary_*.json inside.
      * If 'path' is an existing file -> treat it as single summary file (must match pattern name-wise).
      * If directory does not exist but CWD contains summary_*.json and user passed a non-existent path, fall back to CWD with a warning.
    """
    out: List[Dict[str, Any]] = []
    if path.exists() and path.is_dir():
        targets = sorted(path.glob('summary_*.json'))
    elif path.exists() and path.is_file():
        targets = [path]
    else:
        # Fallback: look in current directory if there are summary files
        cwd = Path.cwd()
        fallback = sorted(cwd.glob('summary_*.json'))
        if fallback:
            print(f"[INFO] Provided summaries path '{path}' not found. Falling back to current directory: {cwd}", file=sys.stderr)
            targets = fallback
        else:
            raise FileNotFoundError(f"Summaries path not found and no summary_*.json in CWD: {path}")
    for fp in targets:
        try:
            with fp.open('r', encoding='utf-8') as f:
                data = json.load(f)
            out.append(data)
        except Exception as e:
            print(f"[WARN] Failed to load {fp}: {e}", file=sys.stderr)
    if not out:
        raise RuntimeError(f"No summary_*.json files found (looked under {path})")
    return out

# ------------------ Metric extraction ------------------

def extract_metric(s: Dict[str, Any], key_path: str) -> float:
    cur: Any = s
    for part in key_path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return float('nan')
        cur = cur[part]
    try:
        return float(cur)
    except Exception:
        return float('nan')

# ------------------ Threshold computation ------------------

def _finite(values: List[float]) -> List[float]:
    return [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]

def _maybe_quantile(values: List[float], p: float, min_count: int) -> Tuple[float, int]:
    fin = _finite(values)
    if len(fin) < min_count:
        return float('nan'), len(fin)
    return percentile(fin, p), len(fin)

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

EXPECTED_KEYS = [
    'coverage_tolerance', 'ctr_min', 'dcts_min', 'max_churn_per_1k', 'max_dro_penalty', 'tau_drift_ema_max'
]


def compute_thresholds(summaries: List[Dict[str, Any]], alpha_target: float) -> Dict[str, Any]:
    # Collect raw lists per metric
    coverages = [extract_metric(s, 'coverage_empirical') for s in summaries]
    # Prefer robust DCTS (tvf2.dcts_robust.value or alias tvf2.dcts_robust_value) if present with sufficient samples (>=5 finite)
    robust_candidates = []
    for s in summaries:
        rv = float('nan')
        # structured form
        cur = s.get('tvf2') if isinstance(s, dict) else None
        if isinstance(cur, dict):
            rob = cur.get('dcts_robust')
            if isinstance(rob, dict) and 'value' in rob:
                try:
                    rv = float(rob['value'])
                except Exception:
                    rv = float('nan')
            if math.isnan(rv) and 'dcts_robust_value' in cur:
                try:
                    rv = float(cur['dcts_robust_value'])
                except Exception:
                    rv = float('nan')
        robust_candidates.append(rv)
    robust_finite = [v for v in robust_candidates if math.isfinite(v)]
    use_robust = len(robust_finite) >= 5
    dcts_values = robust_candidates if use_robust else [extract_metric(s, 'tvf2.dcts') for s in summaries]
    dcts_source = 'robust' if use_robust else 'base'
    # Emit trace for chosen DCTS source
    try:  # side-effect logging (non-fatal)
        if use_robust:
            print(f"[THRESH] dcts_source=robust (N={len(robust_finite)})")
        else:
            print(f"[THRESH] dcts_source=base (robust_N={len(robust_finite)} < 5)")
    except Exception:
        pass
    ctr_values = [extract_metric(s, 'tvf_ctr.ctr') for s in summaries]  # optional nested structure
    churns = [extract_metric(s, 'decision_churn_per_1k') for s in summaries]
    dro_penalties = [extract_metric(s, 'acceptance.dro_penalty') for s in summaries]
    tau_drift = [extract_metric(s, 'r1.tau_drift_ema') for s in summaries]  # example path if present

    target_cov = 1.0 - alpha_target
    coverage_abs_err = [abs(c - target_cov) for c in coverages if math.isfinite(c)]

    thresholds: Dict[str, Any] = {}
    meta_percentiles: Dict[str, Any] = {}
    meta_counts: Dict[str, int] = {}
    min_samples = 5

    # coverage_tolerance
    p95_cov, n_cov = _maybe_quantile(coverage_abs_err, 0.95, min_samples)
    meta_percentiles['coverage_abs_err_p95'] = p95_cov
    meta_counts['coverage_samples'] = n_cov
    if not math.isnan(p95_cov):
        thresholds['coverage_tolerance'] = round(clamp(p95_cov, 0.02, 0.05), 5)

    # dcts_min
    p10_dcts, n_dcts = _maybe_quantile(dcts_values, 0.10, min_samples)
    meta_percentiles['dcts_p10'] = p10_dcts
    meta_percentiles['dcts_source'] = dcts_source
    meta_counts['dcts_samples'] = n_dcts
    if not math.isnan(p10_dcts):
        thresholds['dcts_min'] = round(max(0.90, p10_dcts), 4)

    # ctr_min
    p10_ctr, n_ctr = _maybe_quantile(ctr_values, 0.10, min_samples)
    meta_percentiles['ctr_p10'] = p10_ctr
    meta_counts['ctr_samples'] = n_ctr
    if not math.isnan(p10_ctr):
        thresholds['ctr_min'] = round(max(0.95, p10_ctr), 4)

    # max_churn_per_1k
    p95_churn, n_churn = _maybe_quantile(churns, 0.95, min_samples)
    meta_percentiles['churn_p95'] = p95_churn
    meta_counts['churn_samples'] = n_churn
    if not math.isnan(p95_churn):
        thresholds['max_churn_per_1k'] = round(clamp(1.10 * p95_churn, 15.0, 40.0), 4)

    # max_dro_penalty (warn-only initially, but we still derive)
    p95_dro, n_dro = _maybe_quantile(dro_penalties, 0.95, min_samples)
    meta_percentiles['dro_penalty_p95'] = p95_dro
    meta_counts['dro_penalty_samples'] = n_dro
    if not math.isnan(p95_dro):
        thresholds['max_dro_penalty'] = round(1.10 * p95_dro, 6)

    # tau_drift_ema_max
    p95_tau, n_tau = _maybe_quantile(tau_drift, 0.95, min_samples)
    meta_percentiles['tau_drift_ema_p95'] = p95_tau
    meta_counts['tau_drift_ema_samples'] = n_tau
    if not math.isnan(p95_tau):
        thresholds['tau_drift_ema_max'] = round(clamp(1.25 * p95_tau, 0.01, 0.05), 5)

    meta = {
        'generated': datetime.utcnow().isoformat() + 'Z',
        'alpha_target': alpha_target,
        'samples_total': len(summaries),
        'percentiles_source': meta_percentiles,
        'sample_counts': meta_counts,
        'min_samples_required_per_metric': min_samples,
    }
    # Ensure all expected keys present (None if missing due to insufficient samples)
    completed = {k: thresholds.get(k) for k in EXPECTED_KEYS}
    eligible_keys = [k for k, v in completed.items() if isinstance(v, (int, float)) and not math.isnan(v)]
    meta['eligible_keys'] = eligible_keys
    meta['eligible_ratio'] = (len(eligible_keys) / len(EXPECTED_KEYS)) if EXPECTED_KEYS else 1.0
    return {'thresholds': completed, 'meta': meta}

# ------------------ YAML emission ------------------

def write_yaml(data: Dict[str, Any], out_path: Path, force: bool):
    if out_path.exists() and not force:
        raise FileExistsError(f"Output file exists (use --force to overwrite): {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False)


def load_current(path: Path) -> Dict[str, Any]:  # pragma: no cover - simple IO
    if not path.exists():
        return {}
    try:
        with path.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def build_diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    old_th = (old or {}).get('thresholds', {}) if isinstance(old, dict) else {}
    new_th = (new or {}).get('thresholds', {}) if isinstance(new, dict) else {}
    all_keys = sorted(set(old_th.keys()) | set(new_th.keys()) | set(EXPECTED_KEYS))
    diff_rows = []
    changed = added = removed = insufficient = unchanged = 0
    for k in all_keys:
        ov = old_th.get(k)
        nv = new_th.get(k)
        status: str
        pct_change = None
        if nv is None:
            status = 'insufficient_samples'
            insufficient += 1
        elif ov is None and nv is not None:
            status = 'added'
            added += 1
        elif ov is not None and nv is None:
            status = 'removed'
            removed += 1
        else:
            # both not None
            if isinstance(ov, (int, float)) and isinstance(nv, (int, float)) and not any(math.isnan(x) for x in (ov, nv)):
                if ov == 0:
                    pct_change = None
                else:
                    pct_change = (nv - ov) / abs(ov)
                if nv != ov:
                    status = 'changed'
                    changed += 1
                else:
                    status = 'unchanged'
                    unchanged += 1
            else:
                status = 'changed' if nv != ov else 'unchanged'
                if status == 'changed':
                    changed += 1
                else:
                    unchanged += 1
        diff_rows.append({
            'key': k,
            'old': ov,
            'new': nv,
            'pct_change': None if pct_change is None else round(pct_change, 6),
            'status': status,
        })
    summary = {
        'counts': {
            'added': added,
            'removed': removed,
            'changed': changed,
            'unchanged': unchanged,
            'insufficient_samples': insufficient,
        },
        'total_keys': len(all_keys),
    }
    return {'rows': diff_rows, 'summary': summary}


def write_report(report_path: Path, payload: Dict[str, Any]):  # pragma: no cover - IO
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open('w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)

# ------------------ CLI ------------------

def parse_args(argv: List[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Derive CI gating thresholds from replay summaries.')
    ap.add_argument('--summaries', required=True, help='Directory containing summary_*.json files.')
    ap.add_argument('--out', required=True, help='Output YAML file (suggested thresholds).')
    ap.add_argument('--alpha-target', type=float, default=0.10, help='Alpha target used for coverage delta (default 0.10).')
    ap.add_argument('--force', action='store_true', help='Overwrite existing output file.')
    ap.add_argument('--current', type=str, default=None, help='Existing thresholds YAML to diff against (optional).')
    ap.add_argument('--dryrun', action='store_true', help='Do not overwrite --out; just compute and report.')
    ap.add_argument('--report', type=str, default='artifacts/ci_thresholds/report.json', help='Path to write JSON diff report.')
    ap.add_argument('--min-eligible-ratio', type=float, default=0.7, help='Minimal share of keys with derived numeric values to treat as success.')
    ap.add_argument('--emit-hard-candidates', action='store_true', help='Augment meta with hard_candidates list & reason map based on stability heuristics.')
    ap.add_argument('--hard-min-samples', type=int, default=20, help='Minimum per-metric finite samples to consider for hard candidate.')
    ap.add_argument('--hard-max-coverage-delta-p95', type=float, default=0.07, help='Max p95 absolute coverage error allowed for hard coverage_tolerance candidacy.')
    ap.add_argument('--hard-max-churn-p95', type=float, default=25.0, help='Max churn p95 for churn threshold to be hard candidate.')
    ap.add_argument('--hard-max-tau-drift-p95', type=float, default=0.04, help='Max tau_drift_ema p95 for drift threshold candidacy.')
    ap.add_argument('--hard-max-dcts-var-ratio', type=float, default=0.85, help='Upper bound on robust/base variance ratio (if available) for dcts_min hard candidacy.')
    # DCTS audit integration
    ap.add_argument('--dcts-audit-json', type=str, default=None, help='Path to DCTS audit JSON (tools/dcts_audit.py output).')
    ap.add_argument('--audit-min-summaries', type=int, default=10, help='Minimum robust sample count from audit to treat as fresh.')
    ap.add_argument('--audit-max-age-days', type=int, default=7, help='Maximum age (days) of audit JSON for freshness.')
    ap.add_argument('--enable-hard', type=str, default=None, help='Comma separated list of logical metric identifiers to hard-enable (e.g. tvf2.dcts,ci.churn). Only applied if metric is in hard_candidates unless forced via override option at runtime.')
    return ap.parse_args(argv)

def main(argv: List[str]) -> int:
    try:
        args = parse_args(argv)
        summaries_dir = Path(args.summaries)
        out_file = Path(args.out)
        summaries = collect_summaries(summaries_dir)
        new_data = compute_thresholds(summaries, alpha_target=args.alpha_target)
        # Load current if provided
        old_data = load_current(Path(args.current)) if args.current else load_current(out_file)
        diff = build_diff(old_data, new_data)

        # Hard candidate heuristics (purely metadata, does not mutate thresholds):
        hard_candidates: List[str] = []
        hard_reasons: Dict[str, str] = {}
        if args.emit_hard_candidates:
            meta = new_data.get('meta', {})
            pct_src = meta.get('percentiles_source', {})
            counts = meta.get('sample_counts', {})
            # Optionally enrich with DCTS audit statistics (variance ratio robust/base)
            var_ratio_rb = None
            if args.dcts_audit_json:
                audit_path = Path(args.dcts_audit_json)
                fresh_ok = False
                if audit_path.exists():
                    try:
                        with audit_path.open('r', encoding='utf-8') as f:
                            audit_obj = json.load(f)
                        # Determine freshness
                        mtime = datetime.utcfromtimestamp(audit_path.stat().st_mtime)
                        age_days = (datetime.utcnow() - mtime).days
                        # robust sample count
                        audit_counts = audit_obj.get('counts', {}) if isinstance(audit_obj, dict) else {}
                        robust_n = audit_counts.get('robust') or 0
                        if robust_n >= args.audit_min_summaries and age_days <= args.audit_max_age_days:
                            var_ratio_rb = audit_obj.get('var_ratio')
                            fresh_ok = True
                            try:
                                print(f"[THRESH] dcts_source=robust (N={robust_n}), var_ratio={var_ratio_rb}")
                            except Exception:
                                pass
                        else:
                            print(f"[DERIVE] dcts_audit stale/insufficient (robust_n={robust_n} age_days={age_days})", file=sys.stderr)
                    except Exception as e:
                        print(f"[DERIVE] failed_read_dcts_audit path={audit_path} err={e}", file=sys.stderr)
                else:
                    print(f"[DERIVE] dcts_audit missing path={audit_path}", file=sys.stderr)
            if var_ratio_rb is not None:
                # store in meta regardless of whether it triggers candidacy
                new_data['meta']['var_ratio_rb'] = var_ratio_rb
            # coverage_tolerance: need enough coverage samples & p95 abs error below configured ceiling
            cov_p95 = pct_src.get('coverage_abs_err_p95')
            cov_n = counts.get('coverage_samples', 0)
            if isinstance(cov_p95, (int,float)) and isinstance(cov_n, int) and cov_n >= args.hard_min_samples and cov_p95 <= args.hard_max_coverage_delta_p95:
                hard_candidates.append('coverage_tolerance')
                hard_reasons['coverage_tolerance'] = f"p95_abs_err={cov_p95:.5f}<=max({args.hard_max_coverage_delta_p95}) n={cov_n}"
            # dcts_min: require robust source chosen & variance ratio low (need external audit file optional)
            dcts_source = pct_src.get('dcts_source')
            dcts_n = counts.get('dcts_samples', 0)
            if dcts_source == 'robust' and dcts_n >= args.hard_min_samples:
                # If audit var_ratio available use it; else fall back to sample count only.
                if var_ratio_rb is not None:
                    if isinstance(var_ratio_rb, (int,float)) and var_ratio_rb <= args.hard_max_dcts_var_ratio:
                        hard_candidates.append('dcts_min')
                        hard_reasons['dcts_min'] = f"var_ratio_rb<={args.hard_max_dcts_var_ratio} ({var_ratio_rb}) n={dcts_n}"
                else:
                    hard_candidates.append('dcts_min')
                    hard_reasons['dcts_min'] = f"robust_source=N{dcts_n}>=min_samples({args.hard_min_samples})"
            # ctr_min: sufficient samples & derived ctr_min high (>=0.97 gives confidence)
            ctr_n = counts.get('ctr_samples', 0)
            ctr_threshold = new_data.get('thresholds', {}).get('ctr_min')
            if isinstance(ctr_threshold,(int,float)) and ctr_n >= args.hard_min_samples and ctr_threshold >= 0.97:
                hard_candidates.append('ctr_min')
                hard_reasons['ctr_min'] = f"ctr_min={ctr_threshold}>=0.97 n={ctr_n}"
            # max_churn_per_1k: require churn p95 low vs hard_max_churn_p95
            churn_p95 = pct_src.get('churn_p95')
            churn_n = counts.get('churn_samples', 0)
            if isinstance(churn_p95,(int,float)) and churn_n >= args.hard_min_samples and churn_p95 <= args.hard_max_churn_p95:
                hard_candidates.append('max_churn_per_1k')
                hard_reasons['max_churn_per_1k'] = f"p95={churn_p95}<=max({args.hard_max_churn_p95}) n={churn_n}"
            # tau_drift_ema_max: ensure p95 small enough
            tau_p95 = pct_src.get('tau_drift_ema_p95')
            tau_n = counts.get('tau_drift_ema_samples', 0)
            if isinstance(tau_p95,(int,float)) and tau_n >= args.hard_min_samples and tau_p95 <= args.hard_max_tau_drift_p95:
                hard_candidates.append('tau_drift_ema_max')
                hard_reasons['tau_drift_ema_max'] = f"p95={tau_p95}<=max({args.hard_max_tau_drift_p95}) n={tau_n}"
            # max_dro_penalty intentionally excluded from hard candidacy (risk tuning, leave soft)
            new_data['meta']['hard_candidates'] = hard_candidates
            new_data['meta']['hard_candidate_reasons'] = hard_reasons
        report_payload = {
            'generated': datetime.utcnow().isoformat() + 'Z',
            'alpha_target': args.alpha_target,
            'summaries_dir': str(summaries_dir),
            'out_file': str(out_file),
            'dryrun': bool(args.dryrun),
            'eligible_ratio': new_data['meta'].get('eligible_ratio'),
            'min_eligible_ratio': args.min_eligible_ratio,
            'new': new_data,
            'old': old_data.get('thresholds') if old_data else None,
            'diff': diff,
        }
        write_report(Path(args.report), report_payload)
        print(f"[derive-ci-thresholds] report -> {args.report}")
        # Optional hard-enable promotion (adds hard_enabled / hard_reason under threshold namespaces)
        if args.enable_hard:
            targets = {t.strip() for t in args.enable_hard.split(',') if t.strip()}
            # Map logical names to threshold keys present in our flat 'thresholds'
            logical_map = {
                'ci.churn': 'max_churn_per_1k',
                'tvf2.dcts': 'dcts_min',
                'ci.coverage_tolerance': 'coverage_tolerance',
                'risk.dro_penalty': 'max_dro_penalty',
                'tau.drift': 'tau_drift_ema_max',
            }
            hc = set(new_data.get('meta', {}).get('hard_candidates', []))
            promoted: list[str] = []
            for logical, flat_key in logical_map.items():
                if logical in targets and flat_key in hc:
                    # Attach metadata marking hard
                    # We'll augment a 'hard_meta' structure parallel to thresholds
                    hm = new_data.setdefault('hard_meta', {})
                    hm.setdefault(flat_key, {})['hard_enabled'] = True
                    hm[flat_key]['hard_reason'] = f"stable_criteria_met@{datetime.utcnow().date().isoformat()}"
                    promoted.append(logical)
            if promoted:
                print(f"[derive-ci-thresholds] hard-enabled metrics: {','.join(promoted)}")
        # ---- Build per-metric meta block (non-breaking extra structure) ----
        try:
            metric_meta: Dict[str, Any] = {}
            # Map flat threshold keys to logical namespaces for readability
            logical_names = {
                'dcts_min': 'tvf2.dcts',
                'max_churn_per_1k': 'ci.churn',
                'coverage_tolerance': 'ci.coverage_tolerance',
                'tau_drift_ema_max': 'tau.drift',
            }
            hard_candidates_list = new_data.get('meta', {}).get('hard_candidates', []) or []
            hard_reason_map = new_data.get('meta', {}).get('hard_candidate_reasons', {}) or {}
            var_ratio_rb = new_data.get('meta', {}).get('var_ratio_rb')
            for flat_key, value in new_data.get('thresholds', {}).items():
                logical_lookup = logical_names.get(flat_key)
                logical = logical_lookup if isinstance(logical_lookup, str) else flat_key  # guarantee str
                meta_entry: Dict[str, Any] = {}
                if flat_key == 'dcts_min' and var_ratio_rb is not None:
                    meta_entry['var_ratio_rb'] = var_ratio_rb
                if flat_key in hard_reason_map:
                    meta_entry['hard_candidate'] = True
                    # store reasons as list (future extensibility)
                    meta_entry['hard_candidate_reasons'] = [hard_reason_map[flat_key]]
                elif flat_key in hard_candidates_list:
                    # candidate but no granular reason (should not happen, fallback)
                    meta_entry['hard_candidate'] = True
                # If we previously promoted to hard_meta -> copy status
                hard_meta_block = new_data.get('hard_meta', {}).get(flat_key)
                if hard_meta_block and hard_meta_block.get('hard_enabled'):
                    meta_entry['hard_enabled'] = True
                    meta_entry['hard_reason'] = hard_meta_block.get('hard_reason')
                if meta_entry:  # only add if non-empty
                    metric_meta[logical] = meta_entry
            if metric_meta:
                new_data['metric_meta'] = metric_meta
        except Exception:
            pass
        if not args.dryrun:
            if out_file.exists() and not args.force:
                print(f"[derive-ci-thresholds] ERROR: {out_file} exists (use --force)", file=sys.stderr)
                return 3
            write_yaml(new_data, out_file, force=True if args.force else False)
            print(f"[derive-ci-thresholds] wrote: {out_file}")
        else:
            # Optionally emit dryrun yaml next to out_file
            dry_path = out_file.parent / (out_file.name + '.dryrun.yaml')
            try:
                write_yaml(new_data, dry_path, force=True)
                print(f"[derive-ci-thresholds] dryrun yaml -> {dry_path}")
            except Exception:
                pass
        # eligibility gate
        elig = new_data['meta'].get('eligible_ratio', 0.0)
        if elig < args.min_eligible_ratio:
            print(f"[derive-ci-thresholds] WARN: eligible_ratio={elig:.3f} < {args.min_eligible_ratio} (exit 2)")
            return 2
        # Dryrun exit code 2 to signal non-finalization (optional policy)
        if args.dryrun:
            return 2
        return 0
    except SystemExit:
        raise
    except Exception as e:  # pragma: no cover - defensive
        print(f"[derive-ci-thresholds] ERROR: {e}", file=sys.stderr)
        return 3

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
