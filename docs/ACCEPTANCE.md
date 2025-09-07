# Acceptance Governance Attestation (C7)

This document describes the deterministic procedure to reproduce and attest the two principal governance denial paths:

1. WHY_GOV_ALPHA_EXHAUST – Alpha token fully spent.
2. WHY_GOV_SPRT_REJECT – Sequential statistical test rejects (ACCEPT_H0) under SPRT.

> All acceptance evidence MUST be produced in dry‑run mode with `AURORA_ACCEPTANCE_MODE=1` safeguards. Real trading is blocked.

## Core Mechanisms

| Component | Purpose |
|-----------|---------|
| AlphaLedger | Tracks remaining alpha tokens per test/instrument side |
| CompositeSPRT | Sequential GLR test (Pocock style boundaries) |
| OrderLoggers | Emit structured `orders_*.jsonl` with deny reasons |
| Aurora Event Logger | Emits `GOVERNANCE.SPRT.UPDATE` / `GOVERNANCE.SPRT.FINAL` events |

## Deterministic Control

Environment variable `AURORA_ACCEPTANCE_SCORE_OVERRIDE` forces a constant model score each tick:
- Positive (0.7) -> drives LLR upward (ACCEPT_H1 path) and accelerates alpha spending.
- Zero (0.0) -> keeps mean < delta/2 causing eventual ACCEPT_H0 (statistical reject).

`AURORA_EXPECTED_NET_REWARD_THRESHOLD_BPS=-999` disables ENR gate interference in acceptance mode.

## Reproducing Sessions Manually

Alpha Exhaust Example:
```
AURORA_MODE=live DRY_RUN=true AURORA_SESSION_DIR=logs/session_alpha_exhaust \
AURORA_ACCEPTANCE_MODE=1 AURORA_ACCEPTANCE_SCORE_OVERRIDE=0.7 \
AURORA_EXPECTED_NET_REWARD_THRESHOLD_BPS=-999 \
GOV_ALPHA0=0.02 GOV_SPEND_STEP=0.0025 GOV_DELTA=0.05 AURORA_MAX_TICKS=40 \
python -m skalp_bot.runner.run_live_aurora --config profiles/sol_soon_base.yaml
```

SPRT Reject Example:
```
AURORA_MODE=live DRY_RUN=true AURORA_SESSION_DIR=logs/session_sprt_reject \
AURORA_ACCEPTANCE_MODE=1 AURORA_ACCEPTANCE_SCORE_OVERRIDE=0.0 \
AURORA_EXPECTED_NET_REWARD_THRESHOLD_BPS=-999 \
GOV_ALPHA0=0.02 GOV_SPEND_STEP=0.001 GOV_DELTA=0.05 AURORA_MAX_TICKS=30 \
python -m skalp_bot.runner.run_live_aurora --config profiles/sol_soon_base.yaml
```

### Expected Artifacts
Each session directory will contain:
- `aurora_events.jsonl` – Event stream with `GOVERNANCE.SPRT.*` entries.
- `orders_denied.jsonl` – Lines with either `WHY_GOV_ALPHA_EXHAUST` or `WHY_GOV_SPRT_REJECT`.
- Optional metrics file `metrics_<port>.prom` if metrics exporter started.

## Hash Attestation
SHA256 hashes are computed over each artifact to provide tamper‑evident proof. An aggregate hash is created by lexicographically sorting and concatenating the core file hashes then hashing the result.

## Automation Script
Script: `tools/acceptance_attest.py`

Features:
- Generate scenarios (`alpha_exhaust`, `sprt_reject`) safely (always DRY_RUN=true).
- Aggregate existing or freshly generated sessions into a final JSON attestation.
- Produce counts + hashes + aggregate hash.

### Usage
Aggregate existing sessions:
```
python tools/acceptance_attest.py \
  --sessions logs/session_c7g logs/session_c7sr_final \
  --output logs/C7_attestation_final.json
```

Generate + aggregate:
```
python tools/acceptance_attest.py \
  --generate alpha_exhaust sprt_reject \
  --output logs/C7_attestation_new.json
```

Skip sessions without denies:
```
python tools/acceptance_attest.py \
  --sessions logs/session_misc \
  --skip-empty --output logs/attest_filtered.json
```

### Output Structure
```
{
  "version": "C7-final-attestation",
  "generated_utc": "...Z",
  "governance_evidence": {
     "session_alpha_exhaust": { ... },
     "session_sprt_reject": { ... }
  },
  "aggregate": {
     "deny_counts": {"WHY_GOV_ALPHA_EXHAUST": N, "WHY_GOV_SPRT_REJECT": M},
     "core_files_aggregate_sha256": "<hash>"
  }
}
```

## Safety Guards
The runner enforces:
- Acceptance mode only when `AURORA_ACCEPTANCE_MODE=1`.
- DRY_RUN must remain true for reproduction (script refuses otherwise).

## Troubleshooting
| Symptom | Cause | Fix |
|---------|-------|-----|
| No `WHY_GOV_SPRT_REJECT` lines | Score too high | Use override 0.0 and ensure `GOV_DELTA=0.05` |
| Only `WHY_GOV_ALPHA_EXHAUST` | Alpha spent before SPRT decision | Lower `GOV_SPEND_STEP` or reduce `AURORA_MAX_TICKS` for reject run |
| Empty metrics file | Exporter not started / race | Increase ticks or ensure unique `METRICS_PORT` |

## Verification Checklist
- Two deny types present across sessions.
- Hashes recorded and reproducible.
- Aggregate counts sum equals individual session totals.
- Aggregate hash stable across re-runs (unless artifact content changes).

---
This completes Acceptance Governance Attestation (C7).
