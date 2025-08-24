#!/usr/bin/env python
"""Checkpoint Analyzer v2

Compares recent checkpoints to reference, reporting:
 - Cosine similarity distribution
 - Layer-wise std and fraction of (near) frozen layers
 - NaN / Inf detection
 - xxhash64 signatures per tensor for quick drift detection

Exit codes:
 0 OK, 3 anomaly when --exit-on-anomaly
"""
from __future__ import annotations
import argparse, json, sys, math, time
from pathlib import Path
from typing import Dict, Any, List, Tuple
import torch, yaml, hashlib


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--ckpt-dir', required=True)
    p.add_argument('--ref', default='latest-1', help='reference: latest-1 means previous sorted by mtime')
    p.add_argument('--limit', type=int, default=50)
    p.add_argument('--topk', type=int, default=15)
    p.add_argument('--jsonl', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--exit-on-anomaly', action='store_true')
    p.add_argument('--ttl-days', type=int, default=14)
    p.add_argument('--profile', default='strict')
    p.add_argument('--config', default='configs/ckpt_analyzer.yaml')
    return p.parse_args()


def load_profile(path: Path, name: str):
    cfg = yaml.safe_load(path.read_text(encoding='utf-8'))
    return cfg['profiles'][name]


def list_checkpoints(dir_path: Path) -> List[Path]:
    cks = [p for p in dir_path.glob('*.pt')]
    return sorted(cks, key=lambda p: p.stat().st_mtime, reverse=True)


def pick_reference(cks: List[Path], ref_spec: str) -> Path | None:
    if ref_spec.startswith('latest-'):
        try:
            idx = int(ref_spec.split('-')[1])
            if idx < len(cks):
                return cks[idx]
        except ValueError:
            return None
    else:
        # find by name substring
        for c in cks:
            if ref_spec in c.name:
                return c
    return None


def tensor_iter(state_dict: Dict[str, Any]):
    for k, v in state_dict.items():
        if torch.is_tensor(v) and v.dtype.is_floating_point:
            yield k, v


def cosine(a: torch.Tensor, b: torch.Tensor):
    if a.numel() != b.numel():
        return float('nan')
    a_f = a.float().reshape(-1)
    b_f = b.float().reshape(-1)
    denom = a_f.norm() * b_f.norm()
    if denom == 0:
        return float('nan')
    return float((a_f @ b_f) / denom)


def analyze_pair(ref_sd: Dict[str, Any], cur_sd: Dict[str, Any], profile: Dict[str, Any]):
    stats: List[Dict[str, Any]] = []
    frozen = 0
    total = 0
    min_nonzero_std = profile['min_nonzero_std']
    has_nan = False
    has_inf = False
    cos_list: List[float] = []
    for k, v in tensor_iter(cur_sd):
        total += 1
        if torch.isnan(v).any():
            has_nan = True
        if torch.isinf(v).any():
            has_inf = True
        std = float(v.std().cpu())
        if std < min_nonzero_std:
            frozen += 1
        rv = ref_sd.get(k)
        c = cosine(rv, v) if torch.is_tensor(rv) else float('nan')
        if not math.isnan(c):
            cos_list.append(c)
        # stable content hash per tensor (fast enough for current sizes)
        h = hashlib.blake2b(v.detach().cpu().numpy().tobytes(), digest_size=16).hexdigest()
        stats.append({'layer': k, 'std': std, 'cosine': c, 'hash': h})
    frozen_fraction = frozen / total if total else 0.0
    return {
        'layers': stats,
        'frozen_fraction': frozen_fraction,
        'has_nan': has_nan,
        'has_inf': has_inf,
        'cosine_min': min(cos_list) if cos_list else float('nan'),
        'cosine_mean': sum(cos_list)/len(cos_list) if cos_list else float('nan'),
    }


def detect_anomaly(analysis: Dict[str, Any], profile: Dict[str, Any]):
    if analysis['has_nan'] and not profile['allow_nan']:
        return True, 'nan'
    if analysis['has_inf'] and not profile['allow_inf']:
        return True, 'inf'
    if not math.isnan(analysis['cosine_min']) and analysis['cosine_min'] < profile['min_cosine']:
        return True, 'low_cosine'
    if analysis['frozen_fraction'] > profile['max_frozen_fraction']:
        return True, 'frozen_fraction'
    return False, ''


def main():
    args = parse_args()
    profile = load_profile(Path(args.config), args.profile)
    ckpts = list_checkpoints(Path(args.ckpt_dir))
    if not ckpts:
        print('[ERROR] No checkpoints found', file=sys.stderr)
        return 3
    ref = pick_reference(ckpts, args.ref)
    if ref is None:
        print('[ERROR] Reference checkpoint not found', file=sys.stderr)
        return 3
    ref_sd = torch.load(ref, map_location='cpu')
    out_jsonl = Path(args.jsonl); out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    report_data = {'reference': ref.name, 'analyses': [], 'profile': args.profile}
    anomaly_triggered = False
    anomaly_reason = ''
    for ck in ckpts[:args.limit]:
        if ck == ref:
            continue
        cur_sd = torch.load(ck, map_location='cpu')
        analysis = analyze_pair(ref_sd, cur_sd, profile)
        analysis['checkpoint'] = ck.name
        is_anom, reason = detect_anomaly(analysis, profile)
        analysis['anomaly'] = is_anom
        analysis['reason'] = reason
        if is_anom and not anomaly_triggered:
            anomaly_triggered = True
            anomaly_reason = reason
        with out_jsonl.open('a', encoding='utf-8') as jf:
            jf.write(json.dumps(analysis)+'\n')
        report_data['analyses'].append({k:analysis[k] for k in ['checkpoint','cosine_min','cosine_mean','frozen_fraction','anomaly','reason']})
    rep_path = Path(args.report); rep_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.write_text(json.dumps(report_data, indent=2), encoding='utf-8')
    if args.exit_on_anomaly and anomaly_triggered:
        print(f"[ANOMALY] {anomaly_reason}", file=sys.stderr)
        return 3
    return 0

if __name__ == '__main__':
    sys.exit(main())
