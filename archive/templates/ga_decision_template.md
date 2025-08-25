# GA Decision Template (for PR)

## AURORA 0.4.0 GA Promotion Decision

**Date:** {{ 21 августа 2025 г. }}  
**RC Version:** 0.4.0-rc1  
**Target GA:** 0.4.0  
**Decision By:** @owner @sre @quantlead

---

### ✅ GA Gates Status (5/5 PASS required)

**Fill values from:** `artifacts/ga/ga_gates_now.md`

| Gate | Metric | Threshold | Current | Status | Notes |
|------|--------|-----------|---------|---------|--------|
| 1. Stability | exit=3 count + warn_rate | 0 + ≤5% | [exit_3_24h] + [warn_rate] | ✅ PASS | From logs/*.log + prometheus |
| 2. DCTS Robustness | var_ratio + divergence | ≤0.85 + 0 alerts | [variance_ratio] + [divergence] | ✅ PASS | From dcts_audit/report.json |
| 3. Coverage Control | EMA breaches | ≥95% in tolerance | [coverage_precision]% | ✅ PASS | From ga_gates_eval output |
| 4. DRO Health | factor p05 + |Δλ| p95 | ≥0.6 + ≤0.15 | [dro_p05] + [lambda_delta] | ✅ PASS | From prometheus metrics |
| 5. Model QA | anomalies + cos similarity | 0 + ≥0.995 | [anomaly_count] + [cos_sim] | ✅ PASS | From ckpt/report.json |

**Overall GA Gates:** ✅ ALL PASS / ⚠️ CONDITIONAL / ❌ BLOCKED

---

### 🕊️ Canary Results

```bash
python scripts/canary_run.py --profile configs/profiles/r2.yaml --runs 10 --gating=soft
```

- **Total Runs:** {{ total }} / 10
- **Success Rate:** {{ success_rate }}% (≥70% required)  
- **Health Rate:** {{ health_rate }}% (≥70% required)
- **Avg Duration:** {{ duration }}s
- **Status:** ✅ PASS / ❌ FAIL

---

### 🔒 Infrastructure Readiness

- ✅ **Profile Locks:** r2.yaml + smoke.yaml validated (SHA256 verified)
- ✅ **Monitoring:** Grafana dashboard + Prometheus alerts active
- ✅ **Rollback Plan:** Emergency scripts ready, RC bundle available
- ✅ **Documentation:** Runbooks updated, decision trail complete

---

### 🎯 Final Decision

**Decision:** ✅ **GO** - Proceed with GA promotion

**Rationale:** All 5 GA gates passed, canary tests successful ({{ success_rate }}% success rate), infrastructure validated, rollback plan confirmed ready.

**Risk Assessment:** LOW - All critical metrics within thresholds, monitoring coverage complete.

---

### 📋 Next Steps (if GO)

1. **Enable Hard Gating:** Set `ci_gating.hard_override: auto` in master.yaml
2. **Execute Cutover:** Run Day-0 cutover scripts
3. **Start 24h Watch:** Monitor GA gates hourly for first 24h
4. **Deploy to Production:** Use locked r2.yaml profile
5. **Post-deployment:** Schedule 24h health check

---

### ⚡ Emergency Procedures

**Rollback Trigger Conditions:**
- Any GA gate fails for >2 consecutive hours
- Hard gating violations (exit=3) detected
- Critical alerts firing continuously

**Rollback Command:**
```bash
python scripts/emergency_rollback.py --force
```

**Emergency Contacts:**
- Release Manager: {{ contact }}
- SRE Lead: {{ contact }}  
- On-call: {{ contact }}

---

### 📊 Supporting Artifacts

- 📄 **GA Gates Report:** artifacts/ga/cutover_gates.md
- 📄 **Canary Results:** artifacts/ga/cutover_canary.json  
- 📄 **Profile Locks:** configs/profiles/*.lock.json
- 📄 **Rollback Plan:** scripts/emergency_rollback.py

---

**Approvals:**

- [ ] **Release Manager:** @{{ manager }} _(Infrastructure ready, decision approved)_
- [ ] **SRE Lead:** @{{ sre }} _(Monitoring confirmed, rollback validated)_
- [ ] **Product Owner:** @{{ owner }} _(Business requirements met, risk acceptable)_

**Final Approval:** ✅ **APPROVED FOR GA PROMOTION**

---

*This decision was made using AURORA GA Promotion Kit v1.0 with definitive criteria and automated validation.*