# AURORA GA Promotion Checklist v1.0
## Production Release Decision Framework

**Date:** _____________  
**RC Version:** _____________  
**Target GA Version:** _____________  
**Release Manager:** _____________

---

## 🔍 GA Gates Assessment (1-5)

### Gate 1: Stability / Hard-fail
- [ ] **CI Gating Violations:** `exit=3` count = 0 (last 48h)
- [ ] **Warning Rate:** ≤ 5% (from `aurora_warn_rate`)
- [ ] **Logs:** No `[CI-GATING][HARD]` entries
- [ ] **Status:** ✅ PASS / ⚠️ WARN / ❌ FAIL  
- **Notes:** _________________________________________________

### Gate 2: DCTS Robustness  
- [ ] **Variance Ratio:** `robust/base ≤ 0.85`
- [ ] **Relative Diff:** `|robust-base|/|base| ≤ 0.15` (p95)
- [ ] **Alert:** No `DctsRobustDivergence` alerts
- [ ] **Status:** ✅ PASS / ⚠️ WARN / ❌ FAIL
- **Notes:** _________________________________________________

### Gate 3: Coverage Control
- [ ] **EMA Breaches:** `coverage_abs_err_ema ≤ tolerance` in ≥95% runs
- [ ] **Alert:** No `AuroraCoverageEMABreach` alerts  
- [ ] **Trend:** Stable coverage tracking
- [ ] **Status:** ✅ PASS / ⚠️ WARN / ❌ FAIL
- **Notes:** _________________________________________________

### Gate 4: Risk / DRO Health
- [ ] **DRO Factor:** p05 ≥ 0.6 (no prolonged suppression)
- [ ] **Auto-tune:** |Δλ| p95 ≤ 0.15 (stable lambda)
- [ ] **Alert:** No `DROFactorSuppressed` alerts
- [ ] **Status:** ✅ PASS / ⚠️ WARN / ❌ FAIL
- **Notes:** _________________________________________________

### Gate 5: Model QA / Checkpoints
- [ ] **Checkpoint Analysis:** `ckpt_analyzer_v2` → 0 anomalies
- [ ] **Cosine Similarity:** ≥ 0.995 (no frozen layers)
- [ ] **NaN/Inf Check:** Clean (no numerical issues)
- [ ] **Status:** ✅ PASS / ⚠️ WARN / ❌ FAIL
- **Notes:** _________________________________________________

**Overall GA Gates:** ✅ ALL PASS / ⚠️ CONDITIONAL / ❌ BLOCKED

---

## 🔒 Configuration Profile Lock

### Profile Validation
- [ ] **r2.yaml:** Exists and validated
- [ ] **smoke.yaml:** Exists and validated  
- [ ] **Lock Files:** `r2.lock.json` and `smoke.lock.json` created
- [ ] **Hash Integrity:** SHA256 checksums verified
- [ ] **Runtime Assert:** `profile_lock.enforced=true` configured

### Lock Commands Executed
```bash
# Validate existing locks
python scripts/validate_profiles.py --profile configs/profiles/r2.yaml --lock configs/profiles/r2.lock.json
python scripts/validate_profiles.py --profile configs/profiles/smoke.yaml --lock configs/profiles/smoke.lock.json

# Exit codes: 0=ok, 3=mismatch, 2=dry-run
```
- [ ] **r2 Lock Status:** Exit code = _____ 
- [ ] **smoke Lock Status:** Exit code = _____

---

## 🕊️ Canary Deployment Results

### Canary Execution
```bash
python scripts/canary_run.py --profile configs/profiles/r2.yaml --runs 10 --gating=soft
```

- [ ] **Total Runs:** _____ / 10
- [ ] **Success Rate:** _____% (≥70% required)
- [ ] **Health Rate:** _____% (≥70% required)  
- [ ] **Avg Duration:** _____s
- [ ] **Overall Status:** ✅ PASS / ❌ FAIL

### Issues Found (if any)
- _________________________________________________
- _________________________________________________

---

## 🔧 Infrastructure Readiness

### Monitoring & Alerts
- [ ] **Grafana Dashboard:** "Week-1" displays all panels
- [ ] **Prometheus Alerts:** Active and responsive
  - [ ] `AuroraCoverageEMABreach`
  - [ ] `AuroraHardGateTrip`  
  - [ ] `DctsRobustDivergence`
  - [ ] `DROFactorSuppressed`
- [ ] **Log Aggregation:** Functional and queryable

### Safety Mechanisms  
- [ ] **Panic File:** Test creation/deletion → correct effect
- [ ] **Circuit Breakers:** Configured and tested
- [ ] **Rollback Plan:** Documented and validated
- [ ] **Emergency Contacts:** Updated and accessible

### Documentation
- [ ] **Runbook:** `runbook_ci_thresholds.md` contains:
  - [ ] Exit codes reference
  - [ ] hard_meta v1 specification  
  - [ ] Rollback procedures
- [ ] **Release Notes:** Updated for GA promotion

---

## 📊 Additional Audits (Recommended)

### DCTS Audit
```bash
python tools/dcts_audit.py --summaries artifacts/replay_reports/*.json \
  --out-json artifacts/dcts_audit/report.json --out-md artifacts/dcts_audit/summary.md
```
- [ ] **Audit Status:** ✅ PASS / ⚠️ WARN / ❌ FAIL
- [ ] **Report Location:** artifacts/dcts_audit/report.json

### Hardened Configuration (Optional)
```bash  
python tools/hard_enable_decider.py --gating-log artifacts/ci/gating_state.jsonl \
  --audit-json artifacts/dcts_audit/report.json --dryrun --out configs/ci_thresholds.hardened.yaml
```
- [ ] **Generated:** configs/ci_thresholds.hardened.yaml
- [ ] **Review Status:** ✅ APPROVED / ⚠️ REVIEW NEEDED

---

## 🎯 Final Decision

### Summary Assessment
- **GA Gates:** _____ / 5 PASS
- **Profile Locks:** ✅ SECURED / ❌ UNSECURED
- **Canary Tests:** ✅ PASS / ❌ FAIL
- **Infrastructure:** ✅ READY / ❌ NOT READY

### Decision Matrix
| Component | Status | Impact | Notes |
|-----------|--------|---------|-------|
| GA Gates | | CRITICAL | |
| Profile Locks | | HIGH | |  
| Canary Tests | | HIGH | |
| Monitoring | | MEDIUM | |
| Documentation | | LOW | |

### GO / NO-GO Decision

**□ GO** - Proceed with GA promotion  
**□ NO-GO** - Address issues and re-evaluate  
**□ CONDITIONAL** - Limited promotion with monitoring

**Decision Rationale:**
_________________________________________________
_________________________________________________
_________________________________________________

### Next Steps (if GO)
- [ ] Enable `ci_gating.hard_override: auto`
- [ ] Promote r2 profile with locked configuration
- [ ] Create GA Decision PR with this checklist
- [ ] Deploy to production with enhanced monitoring
- [ ] Schedule post-deployment health check (24h)

### Responsible Parties
- **Release Manager:** _________________________
- **SRE Lead:** _________________________  
- **Product Owner:** _________________________

**Approval Signatures:**

Release Manager: _________________________ Date: _______  
SRE Lead: _________________________ Date: _______  
Product Owner: _________________________ Date: _______

---

**Checklist Version:** 1.0  
**Last Updated:** {{ date }}  
**Template Location:** `docs/ga_promotion_checklist.md`