from __future__ import annotations
import argparse, json, glob
from pathlib import Path
import numpy as np
from living_latent.core.alpha.aci_proxy import compute_aci_proxy, realized_vol, rolling_corr


def load_real_series(glob_pat: str, key: str = 'residuals', limit: int | None = None):
    series = []
    for fp in glob.glob(glob_pat):
        try:
            data = json.loads(Path(fp).read_text(encoding='utf-8'))
            vals = data.get(key) or data.get('residuals_T') or data.get('residuals_target')
            if isinstance(vals, list):
                series.extend([float(v) for v in vals])
        except Exception:
            continue
        if limit and len(series) >= limit:
            break
    return np.asarray(series[:limit] if limit else series, dtype=float)


def parse_args():
    ap = argparse.ArgumentParser(description='Evaluate ACI proxy correlation properties')
    ap.add_argument('--synthetic', type=int, default=200)
    ap.add_argument('--sigma-grid', type=str, default='0.1,0.2,0.4,0.8')
    ap.add_argument('--real-glob', type=str, required=False, help='Glob of real replay summaries (json)')
    ap.add_argument('--real-window', type=int, default=256)
    ap.add_argument('--out-json', type=str, default='artifacts/aci_eval/report.json')
    ap.add_argument('--out-md', type=str, default='artifacts/aci_eval/summary.md')
    return ap.parse_args()


def synth_evaluate(n: int, sigma_grid: list[float], seed: int = 42):
    rng = np.random.default_rng(seed)
    results = []
    for sigma in sigma_grid:
        base = rng.normal(0, sigma, size=n)
        proxy = compute_aci_proxy(base, window=min(64, max(16, n//4)))
        vol = realized_vol(base, window=min(64, max(16, n//4)))
        corr = np.corrcoef(np.nan_to_num(proxy), np.nan_to_num(vol))[0,1]
        results.append({'sigma': sigma, 'corr': float(corr)})
    return results


def real_evaluate(series: np.ndarray, window: int):
    if series.size < window * 2:
        return {'p25': None, 'median': None, 'p75': None, 'count': 0}
    vol = realized_vol(series, window)
    proxy = compute_aci_proxy(series, window=window)
    corr_roll = rolling_corr(proxy, vol, window)
    valid = corr_roll[np.isfinite(corr_roll)]
    if valid.size == 0:
        return {'p25': None, 'median': None, 'p75': None, 'count': 0}
    return {
        'p25': float(np.quantile(valid, 0.25)),
        'median': float(np.quantile(valid, 0.50)),
        'p75': float(np.quantile(valid, 0.75)),
        'count': int(valid.size)
    }


def main():
    args = parse_args()
    sigma_grid = [float(s) for s in args.sigma_grid.split(',') if s.strip()]
    synth = synth_evaluate(args.synthetic, sigma_grid)
    real_stat = None
    if args.real_glob:
        series = load_real_series(args.real_glob)
        real_stat = real_evaluate(series, args.real_window)
    report = {
        'synthetic': synth,
        'real': real_stat,
        'params': {
            'synthetic_n': args.synthetic,
            'sigma_grid': sigma_grid,
            'real_window': args.real_window,
        }
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if args.out_md:
        md = ["# ACI Proxy Evaluation", "", "## Synthetic", "", "| sigma | corr |", "|-------|------|"]
        for row in synth:
            md.append(f"| {row['sigma']} | {row['corr']:.4f} |")
        if real_stat:
            md.append("\n## Real Rolling Corr Stats")
            md.append(f"p25={real_stat['p25']}, median={real_stat['median']}, p75={real_stat['p75']}, count={real_stat['count']}")
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_md).write_text('\n'.join(md), encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':  # pragma: no cover
    main()
