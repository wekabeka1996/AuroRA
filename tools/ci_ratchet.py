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

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import sys
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Current thresholds YAML not found: {path}")
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_report(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def parse_args(argv):
    ap = argparse.ArgumentParser(description='Ratcheting tool for CI thresholds.')
    ap.add_argument('--current', required=True, help='Current ci_thresholds.yaml file.')
    # Accept both --proposal and legacy/test alias --proposed for compatibility
    ap.add_argument('--proposal', required=False, help='Proposal report JSON from derive script.')
    ap.add_argument('--proposed', required=False, help='Alias for --proposal (compat)', dest='proposal')
    ap.add_argument('--report', required=False, help='Optional JSON report path to write summary')
    ap.add_argument('--out', required=True, help='Output YAML (ratcheted).')
    ap.add_argument('--max-step', type=float, default=0.05, help='Maximum relative change per metric (fraction).')
    ap.add_argument('--dryrun', action='store_true', help='Dryrun mode (still writes --out for inspection).')
    ap.add_argument('--exitcode-dryrun', type=int, choices=[0, 2], default=2,
                   help='Exit code for dryrun mode: 0 (legacy compat) or 2 (default convention).')
    return ap.parse_args(argv)


def ratchet(current: dict[str, Any], proposal_report: dict[str, Any], max_step: float) -> dict[str, Any]:
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


def write_yaml(path: Path, data: dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False)


def main(argv):
    args = parse_args(argv)
    current = load_yaml(Path(args.current))
    if not args.proposal:
        raise SystemExit(2)
    proposal = None
    # proposal file may be JSON or YAML; try JSON then YAML
    ppath = Path(args.proposal)
    if not ppath.exists():
        raise FileNotFoundError(f"Proposal file not found: {ppath}")
    try:
        proposal = load_report(ppath)
    except Exception:
        import yaml as _yaml
        with ppath.open('r', encoding='utf-8') as f:
            proposal = _yaml.safe_load(f) or {}

    # Normalize inputs: if user provided plain thresholds dict, wrap under expected keys
    def _flatten(d, parent_key='', sep='.'):
        items = {}
        for k, v in (d or {}).items():
            new_key = parent_key + sep + k if parent_key else k
            if isinstance(v, dict):
                items.update(_flatten(v, new_key, sep=sep))
            else:
                items[new_key] = v
        return items

    def _unflatten(d, sep='.'):
        out = {}
        for k, v in (d or {}).items():
            parts = k.split(sep)
            cur = out
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur[parts[-1]] = v
        return out

    # Determine thresholds dicts
    cur_thresholds = current.get('thresholds') if isinstance(current, dict) and 'thresholds' in current else current
    prop_thresholds = None
    if isinstance(proposal, dict) and 'new' in proposal and isinstance(proposal['new'], dict) and 'thresholds' in proposal['new']:
        prop_thresholds = proposal['new']['thresholds']
    else:
        prop_thresholds = proposal

    flat_cur = _flatten(cur_thresholds)
    flat_prop = _flatten(prop_thresholds)

    norm_current = {'thresholds': flat_cur}
    norm_proposal = {'new': {'thresholds': flat_prop}}
    new_data = ratchet(norm_current, norm_proposal, args.max_step)
    # new_data['thresholds'] is flat mapping; unflatten for output YAML
    # Write thresholds as flat top-level keys for compatibility with callers/tests
    flat_out = new_data.get('thresholds', {})
    out_doc = dict(flat_out)
    # include meta if present
    if new_data.get('meta'):
        out_doc['meta'] = new_data.get('meta')
    write_yaml(Path(args.out), out_doc)
    # optional report
    if args.report:
        changes = new_data.get('meta', {}).get('ratchet', {}).get('changes', {})
        clamped = [k for k, v in (changes or {}).items() if v.get('clamped')]
        report = {'clamped_total': len(clamped), 'clamped': clamped}
        with open(args.report, 'w', encoding='utf-8') as rf:
            json.dump(report, rf)
    print(f"[ci-ratchet] wrote {args.out}")
    if args.dryrun:
        print(f'[ci-ratchet] dryrun mode (exit={args.exitcode_dryrun})')
        return args.exitcode_dryrun
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
