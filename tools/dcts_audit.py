#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys


def load_json(path: Path) -> dict | None:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def extract_records(obj: dict) -> list[dict]:
    recs = []
    if not isinstance(obj, dict):
        return recs
    tvf2 = obj.get('tvf2') if isinstance(obj.get('tvf2'), dict) else None
    if not tvf2:
        return recs
    base = tvf2.get('dcts')
    robust_block = tvf2.get('dcts_robust') if isinstance(tvf2.get('dcts_robust'), dict) else None
    robust_val = None
    if robust_block and 'value' in robust_block:
        robust_val = robust_block['value']
    grids_map = tvf2.get('dcts_grids') if isinstance(tvf2.get('dcts_grids'), dict) else None
    min_block = tvf2.get('dcts_min') if isinstance(tvf2.get('dcts_min'), dict) else None
    min_val = min_block.get('value') if isinstance(min_block, dict) else None
    if base is None and robust_val is None:
        return recs
    recs.append({
        'dcts': base,
        'dcts_robust': robust_val,
        'dcts_min': min_val,
        'dcts_grids': grids_map
    })
    return recs


def summarize(pairs: list[dict]) -> dict:
    # filter valid numeric
    base_vals = [p['dcts'] for p in pairs if isinstance(p.get('dcts'), (int,float)) and math.isfinite(p['dcts'])]
    robust_vals = [p['dcts_robust'] for p in pairs if isinstance(p.get('dcts_robust'), (int,float)) and math.isfinite(p['dcts_robust'])]
    min_vals = [p['dcts_min'] for p in pairs if isinstance(p.get('dcts_min'), (int,float)) and math.isfinite(p['dcts_min'])]
    n = max(len(base_vals), len(robust_vals))
    grids_collect: dict[str, list[float]] = {}
    for p in pairs:
        gm = p.get('dcts_grids')
        if isinstance(gm, dict):
            for g,v in gm.items():
                if isinstance(v, (int,float)) and math.isfinite(v):
                    grids_collect.setdefault(str(g), []).append(float(v))
    def _stats(xs: list[float]) -> dict:
        if not xs:
            return {'n':0,'mean':None,'std':None}
        if len(xs)==1:
            return {'n':1,'mean':xs[0],'std':0.0}
        return {'n':len(xs), 'mean': statistics.fmean(xs), 'std': statistics.pstdev(xs)}
    base_stats = _stats(base_vals)
    robust_stats = _stats(robust_vals)
    min_stats = _stats(min_vals)
    var_ratio = None
    if base_stats['n']>1 and robust_stats['n']>1 and base_stats['std'] not in (None,0):
        base_var = base_stats['std']**2
        robust_var = robust_stats['std']**2
        if base_var>0:
            var_ratio = robust_var / base_var
    # fraction robust close to min
    eps = 1e-6
    close_count = 0; denom = 0
    for p in pairs:
        rv = p.get('dcts_robust'); mv = p.get('dcts_min')
        if isinstance(rv,(int,float)) and isinstance(mv,(int,float)) and math.isfinite(rv) and math.isfinite(mv):
            denom += 1
            if rv <= mv + eps:
                close_count += 1
    close_frac = (close_count/denom) if denom else None
    grids_stats = {g: _stats(vs) for g,vs in grids_collect.items()}
    return {
        'counts': {'base': base_stats['n'], 'robust': robust_stats['n']},
        'base': base_stats,
        'robust': robust_stats,
        'min': min_stats,
        'grid_stats': grids_stats,
        'var_ratio': var_ratio,
        'robust_is_min_fraction': close_frac
    }


def write_md(summary: dict, path: Path):
    lines = []
    lines.append('# DCTS Audit Summary')
    counts = summary.get('counts', {})
    lines.append(f"N base={counts.get('base')} robust={counts.get('robust')}")
    base = summary.get('base', {})
    robust = summary.get('robust', {})
    var_ratio = summary.get('var_ratio')
    lines.append('')
    lines.append('| Metric | mean | std |')
    lines.append('|--------|------|-----|')
    lines.append(f"| dcts | {base.get('mean')} | {base.get('std')} |")
    lines.append(f"| dcts_robust | {robust.get('mean')} | {robust.get('std')} |")
    lines.append('')
    lines.append(f"var_ratio = {var_ratio}")
    lines.append(f"robust_is_min_fraction = {summary.get('robust_is_min_fraction')}")
    grids = summary.get('grid_stats', {})
    if grids:
        lines.append('\n## Grids')
        lines.append('| Grid | N | mean | std |')
        lines.append('|------|---|------|-----|')
        for g, st in sorted(grids.items()):
            lines.append(f"| {g} | {st.get('n')} | {st.get('mean')} | {st.get('std')} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines), encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description='Audit runtime summaries for DCTS vs robust DCTS stats.')
    ap.add_argument('--summaries', nargs='+', required=True, help='Glob(s) or explicit files to parse')
    ap.add_argument('--out-json', required=True)
    ap.add_argument('--out-md', required=True)
    args = ap.parse_args()
    files: list[Path] = []
    for patt in args.summaries:
        if any(ch in patt for ch in '*?['):
            import glob as _g
            for m in _g.glob(patt):
                p = Path(m)
                if p.is_file():
                    files.append(p)
        else:
            p = Path(patt)
            if p.is_file():
                files.append(p)
    pairs: list[dict] = []
    for f in files:
        obj = load_json(f)
        if not obj:
            continue
        recs = extract_records(obj)
        if not recs:
            continue
        pairs.extend(recs)
    summary = summarize(pairs)
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    write_md(summary, Path(args.out_md))
    n = summary.get('counts', {}).get('robust') or 0
    if n < 10:
        print(f"[WARN] Only {n} robust samples (<10) -- statistics may be unstable", file=sys.stderr)
    print(json.dumps({'report': str(out_json), 'md': str(args.out_md), 'n': n, 'var_ratio': summary.get('var_ratio') }))

if __name__ == '__main__':
    main()
