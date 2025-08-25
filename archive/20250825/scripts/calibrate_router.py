"""Script to calibrate RegimeRouter temperature via validation set.

Usage example:
  python scripts/calibrate_router.py --router-checkpoint ckpt_router.pt \
      --data val_features.npy --labels val_labels.npy --out calibrated_router.pt

Assumptions:
 - val_features.npy shape (N, d_obs)
 - val_labels.npy shape (N,) integer class labels
 - Router architecture params (d_input, num_regimes) loaded from JSON config or checkpoint meta.
"""
from __future__ import annotations
import argparse
import json
import torch
import numpy as np
from models.router import RegimeRouter
from models.metrics_calibration import expected_calibration_error, temperature_scale

def load_arrays(path_feats: str, path_labels: str):
    feats = np.load(path_feats)
    labels = np.load(path_labels)
    if feats.ndim != 2:
        raise ValueError("Features array must be 2D (N, d_obs)")
    if labels.ndim != 1:
        raise ValueError("Labels array must be 1D (N,)")
    if feats.shape[0] != labels.shape[0]:
        raise ValueError("Features and labels count mismatch")
    return feats, labels

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--router-checkpoint', required=True)
    ap.add_argument('--data', required=True, help='NumPy .npy features file')
    ap.add_argument('--labels', required=True, help='NumPy .npy labels file')
    ap.add_argument('--config', required=False, help='JSON with d_input & num_regimes if not in checkpoint')
    ap.add_argument('--out', required=True, help='Output path for calibrated checkpoint')
    ap.add_argument('--bins', type=int, default=15)
    args = ap.parse_args()

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    feats_np, labels_np = load_arrays(args.data, args.labels)
    feats = torch.from_numpy(feats_np).float().to(device)
    labels = torch.from_numpy(labels_np).long().to(device)

    # Load router
    meta = {}
    ckpt = torch.load(args.router_checkpoint, map_location=device)
    state_dict = ckpt
    if isinstance(ckpt, dict) and 'state_dict' in ckpt:
        state_dict = ckpt['state_dict']
        meta = ckpt.get('meta', {})

    d_input = meta.get('d_input')
    num_regimes = meta.get('num_regimes')
    if (d_input is None or num_regimes is None) and args.config:
        with open(args.config, 'r', encoding='utf-8') as fh:
            cfg_json = json.load(fh)
        d_input = d_input or cfg_json.get('d_input')
        num_regimes = num_regimes or cfg_json.get('num_regimes')
    if d_input is None:
        d_input = feats.shape[1]
    if num_regimes is None:
        num_regimes = int(labels.max().item() + 1)

    router = RegimeRouter(d_input=d_input, num_regimes=num_regimes).to(device)
    missing, unexpected = router.load_state_dict(state_dict, strict=False)
    print(f"Router loaded. Missing: {missing if missing else 'None'} Unexpected: {unexpected if unexpected else 'None'}")
    router.eval()

    with torch.no_grad():
        probs_before, logits = router(feats)
        ece_before = expected_calibration_error(probs_before, labels, n_bins=args.bins)
    print(f"ECE before: {ece_before:.4f}")

    # Temperature scaling
    scaled_logits, T = temperature_scale(logits, labels)
    with torch.no_grad():
        probs_after = torch.softmax(scaled_logits, dim=-1)
        ece_after = expected_calibration_error(probs_after, labels, n_bins=args.bins)
    print(f"Optimized temperature T={T:.4f}; ECE after: {ece_after:.4f}")

    # Save calibrated router (update temperature parameter)
    with torch.no_grad():
        router.temperature.copy_(torch.tensor([T], device=device))
    torch.save({'state_dict': router.state_dict(), 'meta': {'d_input': d_input, 'num_regimes': num_regimes, 'temperature': T}}, args.out)
    print(f"Calibrated router saved to {args.out}")

    if ece_after > ece_before:
        print("[WARN] ECE did not improve; investigate class imbalance or binning.")

if __name__ == '__main__':
    main()
