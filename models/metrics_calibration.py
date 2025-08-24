"""Calibration metrics (ECE/MCE) and temperature scaling utility for Router.

This module provides:
- expected_calibration_error(probs, labels, n_bins)
- maximum_calibration_error(probs, labels, n_bins)
- temperature_scale(logits, labels) -> (scaled_logits, temperature)

All functions are pure (stateless) to simplify unit testing.
"""
from __future__ import annotations
import torch
import torch.nn.functional as F
from dataclasses import dataclass

@dataclass
class CalibrationResult:
    ece_before: float
    ece_after: float
    temperature: float


def expected_calibration_error(probs: torch.Tensor, labels: torch.Tensor, n_bins: int = 15) -> float:
    """Compute ECE (top-label variant) for multi-class probabilities.

    Parameters
    ----------
    probs : (N, C) tensor of probabilities (softmax output)
    labels: (N,) tensor of integer class labels
    n_bins: number of confidence bins
    """
    with torch.no_grad():
        conf, pred = probs.max(dim=1)
        correct = pred.eq(labels)
        bins = torch.linspace(0, 1, n_bins + 1, device=probs.device)
        ece = torch.zeros(1, device=probs.device)
        for i in range(n_bins):
            mask = (conf > bins[i]) & (conf <= bins[i+1]) if i < n_bins - 1 else (conf > bins[i]) & (conf <= bins[i+1])
            if mask.sum() == 0:
                continue
            acc_bin = correct[mask].float().mean()
            conf_bin = conf[mask].mean()
            ece += (mask.float().mean()) * (conf_bin - acc_bin).abs()
        return float(ece.item())


def maximum_calibration_error(probs: torch.Tensor, labels: torch.Tensor, n_bins: int = 15) -> float:
    with torch.no_grad():
        conf, pred = probs.max(dim=1)
        correct = pred.eq(labels)
        bins = torch.linspace(0, 1, n_bins + 1, device=probs.device)
        mce = torch.zeros(1, device=probs.device)
        for i in range(n_bins):
            mask = (conf > bins[i]) & (conf <= bins[i+1]) if i < n_bins - 1 else (conf > bins[i]) & (conf <= bins[i+1])
            if mask.sum() == 0:
                continue
            acc_bin = correct[mask].float().mean()
            conf_bin = conf[mask].mean()
            mce = torch.maximum(mce, (conf_bin - acc_bin).abs())
        return float(mce.item())


def temperature_scale(logits: torch.Tensor, labels: torch.Tensor, max_iter: int = 50, lr: float = 0.01):
    """Optimize single temperature parameter to minimize NLL.

    Returns scaled_logits, temperature
    """
    T = torch.ones(1, device=logits.device, requires_grad=True)
    optimizer = torch.optim.LBFGS([T], lr=lr, max_iter=max_iter)
    labels = labels.long()

    def closure():  # LBFGS closure
        optimizer.zero_grad()
        scaled = logits / T.clamp_min(1e-4)
        loss = F.cross_entropy(scaled, labels)
        loss.backward()
        return loss

    optimizer.step(closure)
    with torch.no_grad():
        scaled_logits = logits / T.clamp_min(1e-4)
    return scaled_logits, float(T.item())

__all__ = [
    'expected_calibration_error','maximum_calibration_error','temperature_scale','CalibrationResult'
]
