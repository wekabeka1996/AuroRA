#!/usr/bin/env python
"""Batch runner to generate multiple replay summary_*.json files for CI threshold derivation.

TASK_ID: REPLAY-SUMMARY-BATCHER

Usage (example):
    python scripts/replay_batch.py \
        --logs-dir data/shadow_logs/runA \
        --runs 10 \
        --out-dir artifacts/replay_reports \
        --profile default \
        --config living_latent/cfg/master.yaml \
        --seed-base 1337

What it does:
  * Invokes the existing single-run replay script (living_latent.scripts.run_r0) multiple times with distinct seeds.
  * Collects produced summaries into --out-dir (filenames summary_<ts>_<seed>.json).
  * Builds an index.json with per-file metric availability required by AUR-CI-705 derive step.
  * Marks eligibility of each metric (finite numeric) and aggregates finite sample counts.

Exit codes:
  0 success
  2 partial (at least one run failed or produced no summary)
  3 no successful summaries

Idempotency: re-running will append new summaries; existing files are left intact. Index is rebuilt fresh each time.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Metrics we care about for threshold derivation
METRIC_PATHS = {
    'coverage_empirical': ('coverage_empirical',),
    'tvf2.dcts': ('tvf2', 'dcts'),
    'tvf_ctr.ctr': ('tvf_ctr', 'ctr'),
    'decision_churn_per_1k': ('decision_churn_per_1k',),
    'acceptance.dro_penalty': ('acceptance', 'dro_penalty'),
    'r1.tau_drift_ema': ('r1', 'tau_drift_ema'),  # optional future metric
}


def parse_args(argv: List[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description='Batch replay summaries generator')
    ap.add_argument('--logs-dir', required=True, help='Directory containing shadow log jsonl files (same input reused across runs).')
    ap.add_argument('--runs', type=int, default=10, help='Number of replay runs to execute (default 10).')
    ap.add_argument('--out-dir', default='artifacts/replay_reports', help='Directory to write summary_*.json and index.json.')
    ap.add_argument('--profile', default='default', help='Profile name (forwarded to single replay script).')
    ap.add_argument('--config', default='living_latent/cfg/master.yaml', help='Master config path.')
    ap.add_argument('--seed-base', type=int, default=1337, help='Base seed; each run uses seed_base + i.')
    ap.add_argument('--python', default=sys.executable, help='Python interpreter to use for invoking run_r0.')
    ap.add_argument('--min-samples', type=int, default=5, help='Minimum finite samples per metric for later eligibility (informational).')
    ap.add_argument('--dry-run', action='store_true', help='Only print planned commands, do not execute.')
    return ap.parse_args(argv)


def _extract(d: Dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _is_finite_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not math.isnan(x) and math.isfinite(float(x))


def run_single(logs_dir: Path, out_path: Path, profile: str, config: str, seed: int, py_exec: str, dry: bool) -> tuple[bool, str]:
    cmd = [py_exec, '-m', 'living_latent.scripts.run_r0', '--logs_dir', str(logs_dir), '--profile', profile, '--config', config, '--seed', str(seed), '--summary_out', str(out_path)]
    if dry:
        print('[DRY-RUN]', ' '.join(cmd))
        return True, 'dry'
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:  # pragma: no cover - subprocess failure
        return False, f'exception: {e}'
    if proc.returncode != 0:
        sys.stderr.write(f"[WARN] run seed={seed} failed rc={proc.returncode}\nSTDERR:\n{proc.stderr}\n")
        return False, proc.stderr[:5000]
    # Basic sanity: ensure file exists
    if not out_path.exists():
        sys.stderr.write(f"[WARN] summary file not produced for seed={seed}: {out_path}\n")
        return False, 'missing summary'
    return True, ''


def build_index(out_dir: Path, min_samples: int) -> dict:
    runs: List[dict] = []
    finite_counts = {k: 0 for k in METRIC_PATHS}
    summary_files = sorted(out_dir.glob('summary_*.json'))
    for fp in summary_files:
        try:
            data = json.loads(fp.read_text(encoding='utf-8'))
        except Exception as e:  # pragma: no cover - corrupted file
            sys.stderr.write(f"[WARN] failed to read {fp}: {e}\n")
            continue
        metrics_block: Dict[str, Any] = {}
        eligible_block: Dict[str, bool] = {}
        for m, path in METRIC_PATHS.items():
            val = _extract(data, path)
            metrics_block[m] = val
            is_fin = _is_finite_number(val)
            if is_fin:
                finite_counts[m] += 1
            eligible_block[m] = is_fin
        runs.append({
            'file': fp.name,
            'n': data.get('n'),
            'metrics': metrics_block,
            'eligible': eligible_block,
        })
    total = len(runs)
    eligible_ratio = {k: (finite_counts[k] / total if total else 0.0) for k in finite_counts}
    index = {
        'generated': datetime.utcnow().isoformat() + 'Z',
        'total_runs': total,
        'min_samples_hint': min_samples,
        'runs': runs,
        'finite_counts': finite_counts,
        'eligible_ratio': eligible_ratio,
        'schema_version': 1,
    }
    return index


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    logs_dir = Path(args.logs_dir)
    if not logs_dir.exists():
        sys.stderr.write(f"[ERROR] logs-dir not found: {logs_dir}\n")
        return 1
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    successful = 0
    failures = 0

    for i in range(args.runs):
        seed = args.seed_base + i
        ts = datetime.utcnow().strftime('%Y%m%dT%H%M%S%f')[:-3]
        summary_path = out_dir / f'summary_{ts}_s{seed}.json'
        ok, msg = run_single(logs_dir, summary_path, args.profile, args.config, seed, args.python, args.dry_run)
        if ok:
            successful += 1
        else:
            failures += 1
    # Always rebuild index (even if dry-run it just reflects existing files)
    index = build_index(out_dir, args.min_samples)
    (out_dir / 'index.json').write_text(json.dumps(index, indent=2), encoding='utf-8')
    print(json.dumps({
        'batch_done': True,
        'runs_requested': args.runs,
        'runs_successful': successful,
        'runs_failed': failures,
        'out_dir': str(out_dir),
        'eligible_ratio': index.get('eligible_ratio'),
    }, indent=2))

    if successful == 0:
        return 3
    if failures > 0:
        return 2
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
