# Release notes — canary candidate

Branch: ci/validate-full-gates
Date: 2025-09-10

Key changes
- p_fill: parameterized via config
  - Read p_fill from `cfg['pfill']` or `cfg['execution']['pfill']`.
  - Support aliases for beta coefficients (beta0..beta4 → b0..b4) and `eps`.
  - `RouterV2` now forwards beta/eps into `core.tca.fill_prob.p_fill_at_T`.
- Tests
  - Added `tests/unit/test_pfill_config.py` verifying aliasing, eps parsing and precedence.
- CI / Quality gates
  - Enforced coverage >= 90% and mutation floor >= 60% with ≤5pp drop allowed vs baseline.
- Observability / Runbook
  - Added `runbooks/canary_checklist.md` containing quick operational checklist for canary runs.

Files changed / added (high level)
- `core/execution/router_v2.py` — p_fill config wiring
- `core/tca/fill_prob.py` — logistic p_fill model
- `tests/unit/test_pfill_config.py` — new unit test
- `.github/workflows/ci.yml`, `.github/workflows/ci-pipeline.yml` — CI gates
- `runbooks/canary_checklist.md` — new checklist

Summary
This candidate enables config-driven p_fill tuning, tightens CI gates, and provides the operational artifacts needed to run a safe canary.
