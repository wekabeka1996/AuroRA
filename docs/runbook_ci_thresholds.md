# CI Thresholds Derive → Ratchet → Gating Runbook

Version: v1 (Hard-Enable Rollout)
Owner: CI/Model Ops
Last Updated: (auto)

## 1. Overview
This runbook defines the operational pipeline that maintains Confidence/Integrity (CI) thresholds used for runtime gating. The chain:

1. Derive: `scripts/derive_ci_thresholds.py` scans recent summary_* JSON artifacts and (optionally) a DCTS audit report to produce a proposal YAML + report JSON.
2. Ratchet: `tools/ci_ratchet.py` safely applies the proposal onto the current production thresholds, clamping per-key moves to a bounded relative step.
3. Runtime Gating: Service / replay jobs load thresholds (with `hard_meta`) and enforce soft state transitions plus optional HARD termination (exit code 3) for selected metrics.

Key goals: gradual tightening (or relaxing) of thresholds, stability against noise, transparent metadata, and controlled promotion of HARD gating.

## 2. Artifacts & Files
- Input summaries: directory of `summary_*.json` produced by evaluation / replay.
- DCTS Audit JSON (optional): contains `var_ratio` and `counts.robust` fields used to judge stability of robust DCTS metric selection.
- Proposal Report JSON: richer structure (raw stats, candidates, reasons) used by ratchet.
- Thresholds YAML: canonical `configs/ci_thresholds.yaml` (or environment-specific variant) with keys:
  - `thresholds`: scalar limits (e.g. `max_churn_per_1k`, `dcts_min`)
  - `meta`: global derivation metadata (window, generation time, var_ratio_rb, etc.)
  - `hard_meta`: per-threshold hard gating enablement + reasons
  - `metric_meta`: per-metric stats (p95, p10, deltas, candidacy flags)
  - `ratchet_meta`: appended by ratchet (decisions & clamped changes)

## 3. Derive Stage
Command (example):
```
python scripts/derive_ci_thresholds.py \
  --summaries data/processed/ci/summaries_7d \
  --out configs/ci_thresholds.proposed.yaml \
  --report artifacts/ci/report_2025-08-16.json \
  --emit-hard-candidates \
  --enable-hard tvf2.dcts,ci.churn \
  --dcts-audit-json artifacts/dcts_audit/report.json \
  --audit-min-summaries 20 \
  --audit-max-age-days 2 \
  --hard-max-dcts-var-ratio 0.9
```
Important Flags:
- `--emit-hard-candidates`: annotate potential metrics for hard gating.
- `--enable-hard <csv>`: actually promote listed metrics (if candidacy reasons pass) into `hard_meta` with `hard_enabled: true`.
- Audit controls (`--dcts-audit-json` etc.) guard against stale or low-sample audits.

Promotion Logic (simplified):
- Metric-specific stability checks (sample count, drift deltas, var_ratio_rb <= limit) produce reasons.
- If reasons pass AND metric listed in `--enable-hard`, `hard_meta[threshold_key] = {hard_enabled: true, hard_reason: <joined reasons>}`.

Exit Codes:
- 0: Successful derivation, thresholds produced.
- 2: Advisory / dry or partial (used for some dry behaviors if implemented).
- 3: Reserved for future fatal conditions (not routinely emitted yet here).

## 4. Ratchet Stage
Command (dry-run):
```
python tools/ci_ratchet.py \
  --current configs/ci_thresholds.yaml \
  --proposal artifacts/ci/report_2025-08-16.json \
  --out configs/ci_thresholds.ratchet.yaml \
  --max-step 0.05 \
  --dryrun
```
Behavior:
- Reads current YAML and proposal report.
- For each overlapping scalar key in `thresholds`: compute desired new value. If relative delta `abs(new-old)/old` > `max-step`, clamp toward new by `sign * old * max_step`.
- Records decision per key: `adopted`, `clamped`, `unchanged`, `skipped_null`.
- Preserves `hard_meta`, `metric_meta`, other sections.

Exit Codes:
- 0: Applied (non-dry run).
- 2: Dry-run only output produced; no in-place production overwrite.

Compatibility Mode:
For legacy systems expecting exit=0 on dry-run success, use `--exitcode-dryrun=0`:
```
python tools/ci_ratchet.py \
  --current configs/ci_thresholds.yaml \
  --proposal artifacts/ci/report_2025-08-16.json \
  --out configs/ci_thresholds.ratchet.yaml \
  --max-step 0.05 \
  --dryrun --exitcode-dryrun=0
```
This ensures backward compatibility while preserving the new convention (exit=2) as default.

Recommend always performing dry-run in CI and diffing before applying.

Apply (non-dry):
```
python tools/ci_ratchet.py --current configs/ci_thresholds.yaml \
  --proposal artifacts/ci/report_2025-08-16.json \
  --out configs/ci_thresholds.yaml --max-step 0.05
```
(Consider writing to a temp file then atomic rename.)

## 5. Runtime Gating
Configuration (`living_latent/cfg/master.yaml` excerpt):
```
ci_gating:
  hard_enabled: true
  hard_override: auto   # force_off|force_on override global
  # ... other streak / hysteresis settings
```
Mechanics:
- Soft State Machine: tracks WARN→WATCH→STABLE transitions based on streak counters.
- Hard Enforcement: For metrics whose threshold key appears in `hard_meta` with `hard_enabled: true` AND global `hard_enabled` (subject to `hard_override`), a violation triggers HARD event and process exit code 3.
- Logs include `[CI-GATING][HARD] metric=<name> reason=<hard_reason>`.

## 6. Typical Operational Flow
1. Generate fresh summaries (cron / pipeline).
2. Run derive (with audit + emit-hard-candidates). Store proposal YAML + report JSON artifact.
3. Review `metric_meta` & `hard_meta` in proposal; confirm new hard promotions are justified.
4. Dry-run ratchet; inspect `ratchet_meta.decisions` for large clamping.
5. If acceptable, run ratchet apply (non-dry) to update production `ci_thresholds.yaml`.
6. Deploy / reload service or ensure next job picks new thresholds.
7. Monitor logs for `[CI-GATING][HARD]` events; investigate early if they appear post-update.

## 7. Rollback / Mitigation
Scenario: False positive HARD failures or over-tight thresholds.
Options:
- Immediate: Set `ci_gating.hard_override: force_off` in runtime config; redeploy -> disables all hard enforcement while investigating.
- Surgical: Edit `ci_thresholds.yaml` removing or setting `hard_enabled: false` for a specific threshold under `hard_meta`.
- Full Revert: Restore previous known-good `ci_thresholds.yaml` from version control and redeploy.

Checklist After Rollback:
- Confirm absence of new HARD logs.
- Track metric drift to understand cause (noise vs distribution shift).

## 8. Observability & Metadata
Inspect YAML sections:
- `meta.var_ratio_rb`: Stability indicator (lower usually better) from DCTS audit.
- `metric_meta[*].hard_candidate`: True indicates candidate before promotion.
- `hard_meta[*].hard_reason`: Concise reasons; retain in commit message for audit.
- `ratchet_meta.decisions`: Quick diff of which thresholds moved and whether clamped.

## 9. CI Recommendations
Automate a job:
1. Run derive (without `--enable-hard`) to preview.
2. If candidate merits promotion (policy doc), re-run derive with `--enable-hard` for specific metrics.
3. Enforce max allowed relative tightening (ratchet `--max-step`).
4. Require human approval (pull request) when any key is clamped or a new hard enable appears.

## 10. Safety Guardrails
- Always use dry-run ratchet first.
- Block merges if audit stale (var_ratio_rb missing or sample count below threshold).
- Alert on sudden large p95 churn increase even if threshold relaxes.
- Log retention: retain last N threshold YAMLs + reports for forensics.

## 11. Edge Cases & Handling
| Case | Mitigation |
|------|------------|
| Missing audit JSON | Derive still proceeds; no hard promotion for dcts unless reasons incomplete. |
| Very low historic churn (near 0) | Ratchet may clamp small absolute changes; review decisions. |
| New metric introduction | Ratchet will adopt with decision=adopted; ensure gating spec updated. |
| Metric removal | Clean manually; derive does not auto-prune unknown keys. |
| Negative or NaN proposed value | Derive should sanitize; ratchet skips null/NaN proposals. |

## 12. Manual Inspection Snippets
Show hard-enabled thresholds:
```
grep -A2 hard_meta configs/ci_thresholds.yaml
```
List clamped changes:
```
python -c "import yaml,sys;d=yaml.safe_load(open('configs/ci_thresholds.yaml'));print([k for k,v in d.get('ratchet_meta',{}).get('decisions',{}).items() if v=='clamped'])"
```

## 13. Hard Meta Schema v1 Structure
The `hard_meta` section follows a canonical schema (v1) for auditability and consistency:

```yaml
hard_meta:
  schema_version: 1
  window_n: 42        # Number of summary samples analyzed
  warn_rate_k: 0.23   # Warning rate threshold for candidacy
  p95_p10_delta: 0.15 # P95-P10 delta threshold
  var_ratio_rb: 0.8   # Variance ratio (robust baseline)
  hard_candidate:
    tvf2.dcts: true
    ci.churn: false
  reasons:
    tvf2.dcts: "stability_ok,sample_ok,drift_low"
    ci.churn: "high_variance"
  decided_by: hard_enable_decider
  timestamp: "2025-08-16T14:30:00Z"
  
  # Per-threshold enablement (only for promoted metrics)
  tvf2.dcts:
    hard_enabled: true
    hard_reason: "stability_ok,sample_ok,drift_low"
```

Key fields:
- `schema_version`: Always 1 for current implementation
- `window_n`: Sample size used for stability analysis
- `warn_rate_k`: Warning rate threshold applied during candidacy evaluation  
- `p95_p10_delta`: P95-P10 delta threshold for drift detection
- `var_ratio_rb`: Variance ratio from DCTS audit (fallback: var_ratio)
- `hard_candidate`: Boolean flags indicating candidacy status per metric
- `reasons`: Detailed reasoning strings for each metric evaluation
- `decided_by`: Tool/process that generated this metadata
- `timestamp`: ISO format timestamp of generation

## 14. Future Enhancements
- Incorporate statistical test (e.g. Brown-Forsythe) for variance stability beyond simple ratio.
- Multi-window derive (7d vs 30d) with consistency checks.
- Auto-open PR with diff & annotations (GitHub Actions).
- Canary gating: shadow HARD path before activation.

## 15. Appendix: Exit Codes Summary
| Tool | Exit 0 | Exit 2 | Exit 3 | Notes |
|------|--------|--------|--------|-------|
| derive_ci_thresholds | success | (advisory / dry reserved) | future fatal (unused) | Standard convention |
| ci_ratchet | applied | dry-run only | n/a | Use --exitcode-dryrun=0 for legacy compat |
| runtime gating | normal | n/a | HARD violation | HARD termination on threshold breach |

**Exit Code Compatibility:**
- Legacy systems: Use `--exitcode-dryrun=0` with ci_ratchet for backward compatibility
- Default behavior: ci_ratchet dry-run exits with code 2 (new convention)
- Hard gating: Always exits with code 3 on threshold violations regardless of compatibility settings

---
End of Runbook.
