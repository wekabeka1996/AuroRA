# Observability Runbook

## Live Calibration Monitoring

### Calibration Health Checklist

Monitor these metrics continuously in production:

**Primary Metrics**:
- **ECE (Expected Calibration Error)**: Target ≤ 0.05 (excellent), ≤ 0.10 (acceptable), > 0.10 (poor)
- **Brier Score**: Target ≤ 0.17 (good calibration), > 0.25 (poor)
- **LogLoss**: Target ≤ 0.50 (good), > 1.0 (concerning)

**Secondary Checks**:
- Prediction set size (for ICP): Should not be empty frequently
- Calibration curve: Should follow diagonal line
- Reliability diagram: Confidence vs accuracy alignment

**Alert Thresholds**:
- ECE > 0.10: **RED ALERT** - Consider recalibration or model retraining
- Brier > 0.25: **YELLOW ALERT** - Monitor closely
- Empty prediction sets > 5% of trades: **RED ALERT** - ICP parameters need adjustment

**Action Items**:
1. Daily calibration metric review
2. Weekly recalibration if metrics degrade
3. Monthly model performance audit
4. Log all calibration failures for analysis

**Tools**: Use `core/calibration/calibrator.py::evaluate_calibration()` for offline assessment.