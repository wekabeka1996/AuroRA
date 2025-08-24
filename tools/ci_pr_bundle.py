#!/usr/bin/env python
"""CI PR Bundle Generator

Aggregates:
 - current thresholds YAML
 - ratchet thresholds YAML (proposed)
 - hard enable decision log JSONL
 - DCTS audit summary markdown
Produces a consolidated pr_summary.md with sections:
 1. Overview
 2. Ratchet Diff Table
 3. Hard-enable Decisions
 4. DCTS Audit Snapshot
 5. Rollback Playbook
Exit 0 normal; exit 3 on error.
"""
from __future__ import annotations
import argparse, json, sys, math
from pathlib import Path
from typing import Any, Dict, List
import yaml

SECTION_HEADERS = ["Overview", "Ratchet Diff", "Hard-enable Decisions", "DCTS Audit", "Rollback Playbook"]

def load_yaml(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def read_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line: continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def diff_thresholds(cur: Dict[str, Any], rat: Dict[str, Any]) -> List[Dict[str, Any]]:
    cd = cur.get('thresholds', {}) or {}
    rd = rat.get('thresholds', {}) or {}
    rows = []
    keys = sorted(set(cd.keys()) | set(rd.keys()))
    for k in keys:
        v0 = cd.get(k)
        v1 = rd.get(k)
        if isinstance(v0, (int,float)) and isinstance(v1,(int,float)):
            if v0 == 0:
                rel = math.inf if v1!=0 else 0.0
            else:
                rel = (v1 - v0)/abs(v0)
        else:
            rel = None
        rows.append({'key': k, 'current': v0, 'proposed': v1, 'abs_delta': (None if (not isinstance(v0,(int,float)) or not isinstance(v1,(int,float))) else v1 - v0), 'rel_delta': rel})
    return rows


def format_diff_table(rows: List[Dict[str, Any]]) -> str:
    header = "| Key | Current | Proposed | Δ | Δ% |\n|-----|---------|----------|----|----|"
    lines = [header]
    for r in rows:
        if r['abs_delta'] is None:
            delta = ''
            relp = ''
        else:
            delta = f"{r['abs_delta']:.4g}"
            relp = ("∞" if (r['rel_delta'] is not None and math.isinf(r['rel_delta'])) else (f"{r['rel_delta']*100:.2f}%" if r['rel_delta'] is not None else ''))
        lines.append(f"| {r['key']} | {r['current']} | {r['proposed']} | {delta} | {relp} |")
    return "\n".join(lines)


def summarize_hard(decisions: List[Dict[str, Any]]) -> str:
    if not decisions:
        return "No hard-enable decisions logged."
    header = "| Metric | Threshold Key | Enable | Changed | Reasons | n | warn_rate | delta_p95p10 |\n|--------|---------------|--------|---------|---------|---|-----------|-------------|"
    lines = [header]
    for d in decisions[-50:]:  # recent tail
        stats = d.get('stats', {})
        lines.append(f"| {d.get('metric')} | {d.get('threshold_key')} | {d.get('enable')} | {d.get('changed')} | {(';'.join(d.get('reasons', [])))[:120]} | {stats.get('n')} | {stats.get('warn_rate')} | {stats.get('delta_p95_p10')} |")
    return "\n".join(lines)


def build_markdown(args, current, ratchet, decisions, audit_md_text):
    diff_rows = diff_thresholds(current, ratchet)
    diff_table = format_diff_table(diff_rows)
    hard_table = summarize_hard(decisions)
    overview = f"This PR bundles CI threshold changes. Max relative delta: {max([abs(r['rel_delta']) for r in diff_rows if isinstance(r.get('rel_delta'), (int,float)) and not math.isinf(r['rel_delta'])] or [0]):.2%}.\n\nRatchet source: {args.ratchet}\nCurrent: {args.current}".strip()
    rollback = """### Rollback Steps
1. Revert to previous `configs/ci_thresholds.yaml` from Git history.
2. Set `ci_gating.hard_override: force_off` if emergency disabling hard gating is required.
3. Redeploy / restart service relying on thresholds.
4. Inspect recent HARD events; confirm cessation post-rollback.
""".strip()
    parts = [
        f"## Overview\n\n{overview}",
        f"## Ratchet Diff\n\n{diff_table}",
        f"## Hard-enable Decisions\n\n{hard_table}",
        f"## DCTS Audit\n\n{audit_md_text or 'No audit summary provided.'}",
        f"## Rollback Playbook\n\n{rollback}"
    ]
    return "\n\n".join(parts) + "\n"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--current', required=True)
    p.add_argument('--ratchet', required=True)
    p.add_argument('--hard-log', required=True)
    p.add_argument('--audit-md', required=False)
    p.add_argument('--out', required=True)
    return p.parse_args()


def main():
    args = parse_args()
    try:
        current = load_yaml(Path(args.current))
        ratchet = load_yaml(Path(args.ratchet))
        decisions = read_jsonl(Path(args.hard_log))
        audit_md_text = Path(args.audit_md).read_text(encoding='utf-8') if args.audit_md and Path(args.audit_md).exists() else ''
        md = build_markdown(args, current, ratchet, decisions, audit_md_text)
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(md, encoding='utf-8')
        # quick validation that all sections present
        missing = [h for h in SECTION_HEADERS if f"## {h}" not in md]
        if missing:
            print(f"[ERROR] Missing sections: {missing}", file=sys.stderr)
            return 3
        return 0
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 3

if __name__ == '__main__':
    sys.exit(main())
