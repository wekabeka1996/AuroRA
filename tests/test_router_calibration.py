import torch
import numpy as np
from models.router import RegimeRouter
from models.metrics_calibration import expected_calibration_error, temperature_scale

def test_temperature_scaling_reduces_ece():
    torch.manual_seed(0)
    N = 512
    d_input = 16
    num_regimes = 3
    # Synthetic features & labels with slight class imbalance
    feats = torch.randn(N, d_input)
    true_logits = torch.randn(N, num_regimes) * 0.5
    labels = true_logits.argmax(dim=1)
    # Uncalibrated model (simulate by copying weight structure)
    router = RegimeRouter(d_input=d_input, num_regimes=num_regimes)
    with torch.no_grad():
        # Initialize classifier weight deterministically: identity block in first d_input columns
        W = torch.zeros_like(router.classifier.weight)
        eye_block = torch.eye(num_regimes, d_input)
        W[:, :d_input] = eye_block
        router.classifier.weight.copy_(W)
        router.classifier.bias.zero_()
    router.eval()
    with torch.no_grad():
        probs_before, logits = router(feats)
        ece_before = expected_calibration_error(probs_before, labels)
    scaled_logits, T = temperature_scale(logits, labels, max_iter=20)
    with torch.no_grad():
        probs_after = torch.softmax(scaled_logits, dim=-1)
        ece_after = expected_calibration_error(probs_after, labels)
    # Allow small tolerance if already low ECE
    assert ece_after <= ece_before + 1e-4
