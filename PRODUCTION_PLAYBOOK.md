# 🚀 AURORA Production Deployment Playbook

**Version:** 1.0  
**Target:** 0.4.0 GA Release  
**Runtime:** Day-0 → 7-day consolidation  

---

## 📋 PRE-FLIGHT CHECKLIST

### Required Infrastructure
- ✅ All GA scripts present in `scripts/`
- ✅ Profile locks in `configs/profiles/`
- ✅ Monitoring stack operational
- ✅ Emergency procedures validated

### Validation Commands
```bash
# Verify GA infrastructure
ls scripts/ga_gates_eval.py scripts/canary_run.py scripts/day0_cutover.py scripts/watch_24h.py scripts/emergency_rollback.py

# Check profile locks
ls configs/profiles/r2.yaml.lock.json configs/profiles/smoke.yaml.lock.json

# Test monitoring
curl -s localhost:9090/metrics | grep aurora || echo "Prometheus check required"
```

---

## 🎯 DAY-0 CUTOVER (Idempotent)

### **STEP 1: Final Gate Evaluation**
```bash
python scripts/ga_gates_eval.py --critical
echo "Exit code: $?" # Must be 0
```

### **STEP 2: Execute Cutover**
```bash
python scripts/day0_cutover.py --confirm --profile r2
echo "Exit code: $?" # Must be 0 for success
```

### **STEP 3: Validate GA Version**
```bash
cat VERSION # Should show "0.4.0"
curl -s localhost:8000/version | jq '.version' # Should show "0.4.0"
```

### **STEP 4: Start 24h Watch**
```bash
nohup python scripts/watch_24h.py --output logs/ga_watch.log &
echo "Watch PID: $!"
```

### **STEP 5: Confirm Production Ready**
```bash
python scripts/canary_run.py --profile configs/profiles/r2.yaml --runs 3 --gating=hard
echo "Final canary exit code: $?" # Must be 0
```

---

## ⏰ 24-HOUR WATCH PROTOCOL

### Monitoring Schedule
- **Hours 0-6:** Check every hour (critical window)
- **Hours 6-12:** Check every 2 hours
- **Hours 12-24:** Check every 4 hours

### Health Commands (run each check)
```bash
# GA Gates Status
python scripts/ga_gates_eval.py --quick --json | jq '.gates_passing'

# System Health
curl -s localhost:8000/health | jq '.status'

# Error Rate Check
grep -c "exit=3" logs/student_$(date +%Y%m%d)*.log || echo "0"
```

### Alert Thresholds
- ❌ **CRITICAL:** Any GA gate fails, exit=3 detected, health check fails
- ⚠️ **WARNING:** >2 warnings per hour, latency >500ms
- ✅ **HEALTHY:** All gates pass, error rate <1%

---

## 🔥 EMERGENCY PROCEDURES

### Immediate Rollback (if needed)
```bash
# PANIC MODE - Instant rollback
python scripts/emergency_rollback.py --force --confirm
echo "Rollback exit code: $?" # 0 = success

# Verify rollback
cat VERSION # Should show "0.4.0-rc1"
ls configs/profiles/*.panic # Check panic files created
```

### Health Recovery Steps
1. **Stop all services:** `pkill -f aurora`
2. **Clear cache:** `rm -rf data/tmp/*`
3. **Restore checkpoints:** `cp checkpoints/*.backup.pt checkpoints/`
4. **Restart with RC:** Use 0.4.0-rc1 configuration

---

## 📊 7-DAY CONSOLIDATION PLAN

### Daily Health Checks
```bash
# Run daily at 9 AM
python scripts/ga_gates_eval.py --daily-report --output artifacts/daily/$(date +%Y%m%d).md
```

### Weekly Metrics Collection
| Day | Focus | Key Metrics | Action |
|-----|--------|-------------|--------|
| D+1 | Stability | Hard failures, exit=3 rate | Monitor closely |
| D+2 | Performance | Latency, throughput | Tune if needed |
| D+3 | Accuracy | DCTS variance, model drift | Validate quality |
| D+4 | Resource | Memory, CPU usage | Optimize deployment |
| D+5 | Coverage | Control precision, fallbacks | Fine-tune parameters |
| D+6 | Integration | API health, downstream | Test full stack |
| D+7 | **FINAL REVIEW** | All gates, comprehensive report | **GA CONFIRMED** |

### Success Criteria (all required)
- ✅ **Zero exit=3 failures** for 7 consecutive days
- ✅ **All GA gates passing** daily (5/5)
- ✅ **No emergency rollbacks** triggered
- ✅ **Performance within SLA** (latency <200ms avg)
- ✅ **Model accuracy stable** (cos similarity >0.995)

---

## 🎪 POST-GA OPTIMIZATION

### After Day-7 Success
1. **Remove RC artifacts:** Clean up 0.4.0-rc1 files
2. **Update documentation:** Mark 0.4.0 as stable
3. **Tune thresholds:** Optimize based on 7-day data
4. **Plan next release:** Start 0.5.0 roadmap

### Configuration Maintenance
```bash
# Weekly profile validation
python scripts/mk_profile_lock.py --verify configs/profiles/r2.yaml

# Monthly threshold review
python scripts/derive_ci_thresholds.py --historical --days 30
```

---

## 📞 CONTACT & ESCALATION

### Immediate Response Team
- **Release Manager:** Primary decision maker
- **SRE Lead:** Infrastructure & monitoring
- **Quant Lead:** Model & risk validation

### Escalation Triggers
1. **Tier 1:** Single GA gate fails (15 min response)
2. **Tier 2:** Multiple gates fail (5 min response)
3. **Tier 3:** Hard failure (exit=3) detected (IMMEDIATE)

### Emergency Runbook
- 📖 **Primary:** `docs/emergency_procedures.md`
- 📖 **Rollback:** `scripts/emergency_rollback.py --help`
- 📖 **Recovery:** `docs/disaster_recovery.md`

---

## ✅ CHECKLIST SUMMARY

### Day-0 Cutover (Required)
- [ ] **Gates Evaluation:** 5/5 pass required
- [ ] **Cutover Execution:** Clean completion (exit=0)
- [ ] **Version Validation:** 0.4.0 confirmed
- [ ] **24h Watch Started:** Monitoring active
- [ ] **Final Canary:** Production validation pass

### 24h Watch (Critical)
- [ ] **Hour 1-6:** Hourly checks complete
- [ ] **Hour 6-24:** Scheduled checks complete
- [ ] **Zero Failures:** No exit=3 or gate failures
- [ ] **Health Confirmed:** All systems operational

### 7-Day Consolidation (Success)
- [ ] **Daily Reports:** All 7 days generated
- [ ] **Success Criteria:** All metrics within SLA
- [ ] **Zero Incidents:** No emergency rollbacks
- [ ] **Final Review:** Comprehensive validation complete
- [ ] **GA CONFIRMED:** 0.4.0 marked as stable production release

---

**🏆 Production Deployment Status: READY FOR EXECUTION**

*Generated by AURORA GA Promotion Kit v1.0 - All systems validated and production-ready*