# Entry Gate Matrix

## Pre-Trade Gates

### Calibrator/ICP Gate Deny Rule

**Condition**: If calibrator/ICP gives high ECE (>0.10) or empty prediction-set

**Action**: **GATE DENY** - Block trade execution

**Rationale**: Poor calibration indicates unreliable probability estimates, which can lead to suboptimal trading decisions and increased risk.

**Thresholds**:
- ECE > 0.10: Deny (high calibration error)
- Empty prediction set: Deny (ICP uncertainty too high)
- LogLoss > 1.0: Warning (monitor closely)

**Implementation**: Check in `core/aurora/pretrade.py` before allowing order submission.