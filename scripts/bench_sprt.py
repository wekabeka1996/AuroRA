import json
import os
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

# Ensure project root on sys.path for direct script invocation
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.scalper.sprt import SPRT, SprtConfig, thresholds_from_alpha_beta


def run_latency_benchmark(n_trials: int = 100, n_obs: int = 1000) -> dict:
    alpha = float(os.getenv("AURORA_BENCH_ALPHA", "0.05"))
    beta = float(os.getenv("AURORA_BENCH_BETA", "0.2"))
    A, B = thresholds_from_alpha_beta(alpha, beta)
    cfg = SprtConfig(mu0=0.0, mu1=0.5, sigma=1.0, A=A, B=B, max_obs=n_obs)
    latencies = []
    for _ in range(n_trials):
        xs = np.random.normal(loc=0.25, scale=1.0, size=n_obs)
        sprt = SPRT(cfg)
        t0 = perf_counter()
        _ = sprt.run_with_timeout(xs.tolist(), time_limit_ms=500.0)
        t1 = perf_counter()
        latencies.append((t1 - t0) * 1000.0)
    p95 = float(np.percentile(latencies, 95))
    return {
        "n_trials": n_trials,
        "n_obs": n_obs,
        "p50_ms": float(np.percentile(latencies, 50)),
        "p90_ms": float(np.percentile(latencies, 90)),
        "p95_ms": p95,
        "p99_ms": float(np.percentile(latencies, 99)),
    }


def run_roc_curve(n_points: int = 50, n_obs: int = 200) -> tuple[np.ndarray, np.ndarray]:
    # Synthetic labels: half from H0, half from H1
    rng = np.random.default_rng(42)
    xs_h0 = rng.normal(loc=0.0, scale=1.0, size=(n_points, n_obs))
    xs_h1 = rng.normal(loc=0.5, scale=1.0, size=(n_points, n_obs))
    labels = np.array([0] * n_points + [1] * n_points)
    scores = []
    for i in range(n_points):
        cfg = SprtConfig(mu0=0.0, mu1=0.5, sigma=1.0, A=1e9, B=-1e9, max_obs=n_obs)
        sprt = SPRT(cfg)
        sprt.run(xs_h0[i])
        scores.append(sprt.llr)
    for i in range(n_points):
        cfg = SprtConfig(mu0=0.0, mu1=0.5, sigma=1.0, A=1e9, B=-1e9, max_obs=n_obs)
        sprt = SPRT(cfg)
        sprt.run(xs_h1[i])
        scores.append(sprt.llr)
    scores = np.array(scores)
    # Simple ROC by sweeping threshold on llr
    thresholds = np.quantile(scores, np.linspace(0.0, 1.0, 200))
    tpr = []
    fpr = []
    for th in thresholds:
        preds = (scores >= th).astype(int)
        tp = int(((preds == 1) & (labels == 1)).sum())
        fp = int(((preds == 1) & (labels == 0)).sum())
        tn = int(((preds == 0) & (labels == 0)).sum())
        fn = int(((preds == 0) & (labels == 1)).sum())
        tpr.append(tp / (tp + fn + 1e-9))
        fpr.append(fp / (fp + tn + 1e-9))
    return np.array(fpr), np.array(tpr)


def main():
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    # Latency stats
    lat = run_latency_benchmark()
    (reports_dir / "sprt_latency.json").write_text(json.dumps(lat, indent=2))
    # ROC image
    try:
        import matplotlib.pyplot as plt

        fpr, tpr = run_roc_curve()
        plt.figure(figsize=(4, 4))
        plt.plot(fpr, tpr, label="SPRT LLR")
        plt.plot([0, 1], [0, 1], "k--", alpha=0.5)
        plt.xlabel("FPR")
        plt.ylabel("TPR")
        plt.title("SPRT ROC")
        plt.legend()
        plt.tight_layout()
        plt.savefig(reports_dir / "sprt_roc.png", dpi=120)
        plt.close()
    except Exception as e:
        # Matplotlib optional; skip if not installed
        (reports_dir / "sprt_roc.png.missing").write_text(str(e))

    print(json.dumps(lat))
    # Simple assert for CI: p95 under 500ms
    if lat.get("p95_ms", 1e9) > 500.0:
        raise SystemExit("SPRT p95 latency exceeds 500ms")


if __name__ == "__main__":
    main()
