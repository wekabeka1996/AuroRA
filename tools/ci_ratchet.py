#!/usr/bin/env python
"""Apply controlled ratcheting from a proposed thresholds report to current ci_thresholds.yaml.

Policy (Hard-Enable Rollout):
    * Only modify keys present in BOTH current.thresholds and proposal.new.thresholds.
    * Added keys (present only in proposal) are adopted directly (treated as change, not clamped).
    * Null / NaN proposal values => skip (insufficient_samples).
    * Relative move limited: |new-old| / |old| <= max_step; excess is clamped.
    * Record per-key decision under ratchet_meta.decisions and aggregated short form under ratchet_meta.changes.
    * Preserve: meta, hard_meta, metric_meta.
    * Exit code: 0 normal, 2 when --dryrun (allows CI to treat as informational).

CLI:
    python tools/ci_ratchet.py --current configs/ci_thresholds.yaml \
            --proposal artifacts/ci_thresholds/report.json \
            --out configs/ci_thresholds.ratchet.yaml --max-step 0.05 --dryrun
"""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict
import yaml


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Current thresholds YAML not found: {path}")
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_report(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def parse_args(argv):
    ap = argparse.ArgumentParser(description='Ratcheting tool for CI thresholds.')
    ap.add_argument('--current', required=True, help='Current ci_thresholds.yaml file.')
    ap.add_argument('--proposal', required=True, help='Proposal report JSON from derive script.')
    ap.add_argument('--out', required=True, help='Output YAML (ratcheted).')
    ap.add_argument('--max-step', type=float, default=0.05, help='Maximum relative change per metric (fraction).')
    ap.add_argument('--dryrun', action='store_true', help='Dryrun mode (still writes --out for inspection).')
    ap.add_argument('--exitcode-dryrun', type=int, choices=[0, 2], default=2, 
                   help='Exit code for dryrun mode: 0 (legacy compat) or 2 (default convention).')
    return ap.parse_args(argv)


def ratchet(current: Dict[str, Any], proposal_report: Dict[str, Any], max_step: float) -> Dict[str, Any]:
    prop = proposal_report.get('new', {}) if isinstance(proposal_report, dict) else {}
    prop_thresholds = prop.get('thresholds', {}) if isinstance(prop, dict) else {}
    cur_thresholds = current.get('thresholds', {}) if isinstance(current, dict) else {}
    result_thresholds = {k: v for k, v in cur_thresholds.items()}  # start with existing
    decisions = {}
    changes = {}
    for key, proposed in prop_thresholds.items():
        if proposed is None or (isinstance(proposed, float) and (math.isnan(proposed))):
            decisions[key] = {'action': 'skip_insufficient'}
            continue
        cur_val = cur_thresholds.get(key)
        if cur_val is None:
            result_thresholds[key] = proposed
            decisions[key] = {'action': 'adopt_new', 'clamped': False, 'old': None, 'proposed': proposed, 'final': proposed}
            changes[key] = {'old': None, 'proposed': proposed, 'applied': proposed, 'clamped': False, 'added': True}
            continue
        if not isinstance(cur_val, (int,float)) or not isinstance(proposed, (int,float)):
            # non numeric -> adopt proposed directly
            result_thresholds[key] = proposed
            decisions[key] = {'action': 'adopt_non_numeric', 'clamped': False, 'old': cur_val, 'proposed': proposed, 'final': proposed}
            continue
        if cur_val == 0:
            # avoid div0: treat as direct adopt
            result_thresholds[key] = proposed
            decisions[key] = {'action': 'adopt_zero_base', 'clamped': False, 'old': cur_val, 'proposed': proposed, 'final': proposed}
            continue
        delta = (proposed - cur_val) / abs(cur_val)
        if abs(delta) <= max_step:
            result_thresholds[key] = proposed
            decisions[key] = {'action': 'adopt_within_step', 'clamped': False, 'old': cur_val, 'proposed': proposed, 'final': proposed, 'delta': round(delta,6)}
            changes[key] = {'old': cur_val, 'proposed': proposed, 'applied': proposed, 'clamped': False}
        else:
            # clamp
            final = cur_val * (1 + max_step * (1 if delta > 0 else -1))
            # maintain formatting precision similar to input
            final_rounded = round(final, 6)
            result_thresholds[key] = final_rounded
            decisions[key] = {'action': 'clamped', 'clamped': True, 'old': cur_val, 'proposed': proposed, 'final': final_rounded, 'delta': round(delta,6)}
            changes[key] = {'old': cur_val, 'proposed': proposed, 'applied': final_rounded, 'clamped': True}
    # Preserve unknown keys present in current but not in proposal (explicit carry forward)
    for key in cur_thresholds.keys():
        if key not in prop_thresholds:
            decisions.setdefault(key, {'action': 'carry_forward'})
    out_meta = current.get('meta', {}).copy()
    ratchet_meta = {
        'ratcheted': datetime.utcnow().isoformat() + 'Z',
        'max_step': max_step,
        'decisions': decisions,
        'proposal_source': {
            'alpha_target': proposal_report.get('alpha_target'),
            'eligible_ratio': proposal_report.get('eligible_ratio')
        },
        'changes': changes
    }
    out_meta['ratchet'] = ratchet_meta
    out_doc = {'thresholds': result_thresholds, 'meta': out_meta}
    # Preserve auxiliary structures if present
    for extra in ('hard_meta','metric_meta','ratchet_meta'):
        if extra in current and extra not in out_doc:
            out_doc[extra] = current[extra]
    return out_doc


def write_yaml(path: Path, data: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False)


def main(argv):
    args = parse_args(argv)
    current = load_yaml(Path(args.current))
    proposal = load_report(Path(args.proposal))
    new_data = ratchet(current, proposal, args.max_step)
    write_yaml(Path(args.out), new_data)
    print(f"[ci-ratchet] wrote {args.out}")
    if args.dryrun:
        print(f'[ci-ratchet] dryrun mode (exit={args.exitcode_dryrun})')
        return args.exitcode_dryrun
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
