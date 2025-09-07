# Testnet Deployment Runbook

**Version:** 2.1.0
**Last Updated:** 2025-09-07
**Owner:** DevOps Team

## 📋 Overview

This runbook provides step-by-step instructions for deploying Aurora to the testnet environment. All deployments must follow the Go/No-Go checklist and require approval from Engineering Lead.

## 🎯 Prerequisites

### Required Approvals
- [ ] Engineering Lead sign-off
- [ ] QA Lead sign-off
- [ ] Security Lead sign-off
- [ ] Business Owner approval (for production-impacting changes)

### Pre-Deployment Validation
```bash
# 1. Run full test suite
pytest tests/unit/ tests/integration/ tests/e2e/ -q

# 2. Validate configuration
python tools/auroractl.py config-validate

# 3. Check mutation score
python scripts/run_mutation_tests.py --baseline-check

# 4. Validate XAI audit trail
python -c "import tests.fixtures.xai_validator; tests.fixtures.xai_validator.validate_recent_events()"

# 5. Build validation
docker build -t aurora:testnet .
```

---

## 🚀 Deployment Steps

### Phase 1: Preparation (15 minutes)

#### 1.1 Environment Setup
```bash
# Set deployment environment variables
export DEPLOY_ENV=testnet
export AURORA_MODE=testnet
export AURORA_SIMULATOR_MODE=true
export DRY_RUN=true
export DEPLOY_TAG=$(git rev-parse --short HEAD)
export DEPLOY_TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create deployment directory
mkdir -p deployments/$DEPLOY_TIMESTAMP
cd deployments/$DEPLOY_TIMESTAMP

# Backup current configuration
cp -r ../../configs/aurora/testnet.yaml .
cp -r ../../configs/runner/testnet.yaml .
```

#### 1.2 Pre-Flight Checks
```bash
# Health check current system
python tools/auroractl.py health

# Validate all configurations
for config in configs/aurora/*.yaml; do
  echo "Validating $config..."
  python tools/auroractl.py config-validate --config $config
done

# Check system resources
df -h  # Disk space
free -h  # Memory
uptime  # System load

# Validate Docker environment
docker system info
docker volume ls
```

#### 1.3 Backup Critical Data
```bash
# Backup current logs
tar -czf aurora_logs_backup_$DEPLOY_TIMESTAMP.tar.gz ../../logs/

# Backup configuration
cp -r ../../configs configs_backup_$DEPLOY_TIMESTAMP

# Create rollback point
git tag -a rollback_$DEPLOY_TIMESTAMP -m "Rollback point before testnet deployment"
```

### Phase 2: Safe Mode Deployment (30 minutes)

#### 2.1 Start in Safe Mode
```bash
# Start API in safe mode (no live trading)
AURORA_MODE=testnet \
AURORA_SIMULATOR_MODE=true \
DRY_RUN=true \
AURORA_CONFIG=../../configs/aurora/testnet.yaml \
python tools/auroractl.py start-api

# Wait for health check
for i in {1..30}; do
  if python tools/auroractl.py health; then
    echo "API healthy after $i attempts"
    break
  fi
  sleep 10
done
```

#### 2.2 Validate Safe Mode Operation
```bash
# Check API endpoints
curl -X GET "http://localhost:8080/health"
curl -X GET "http://localhost:8080/metrics"
curl -X POST "http://localhost:8080/aurora/disarm" -H "Authorization: Bearer $OPS_TOKEN"

# Validate XAI logging
tail -f ../../logs/testnet_session_*/aurora_events.jsonl | head -10

# Run smoke tests
python -m pytest tests/smoke/ -v --tb=short
```

#### 2.3 Enable Limited Trading
```bash
# Gradually enable features
export AURORA_MAX_ORDERS_PER_MINUTE=5
export AURORA_MAX_POSITION_SIZE=0.01  # 1% of normal size

# Update configuration
cat >> ../../configs/aurora/testnet.yaml << EOF
trading:
  max_orders_per_minute: 5
  max_position_size: 0.01
  allowed_symbols: ["BTCUSDT", "ETHUSDT"]
  emergency_stop_enabled: true
EOF

# Reload configuration
curl -X POST "http://localhost:8080/aurora/reload-config" -H "Authorization: Bearer $OPS_TOKEN"
```

### Phase 3: Full Operation Validation (60 minutes)

#### 3.1 Run Integration Tests
```bash
# Run targeted integration tests
pytest tests/integration/oms/test_order_lifecycle.py -v
pytest tests/integration/test_latency_slippage.py -v
pytest tests/integration/test_expected_return_gate.py -v

# Validate XAI audit trail completeness
python scripts/validate_xai_trail.py --session-id $(ls ../../logs/ | tail -1)
```

#### 3.2 Performance Validation
```bash
# Run performance benchmarks
pytest tests/performance/ -v --benchmark-only

# Monitor system metrics
watch -n 5 'python tools/auroractl.py metrics | jq ".order_latency_p95, .fill_rate, .memory_usage"'
```

#### 3.3 Business Logic Validation
```bash
# Test order flow end-to-end
python scripts/test_order_flow.py --symbol BTCUSDT --quantity 0.001

# Validate position management
python scripts/test_position_management.py --max-positions 3

# Check risk gates
python scripts/test_risk_gates.py --scenario partial_fill
```

### Phase 4: Production Readiness (30 minutes)

#### 4.1 Monitoring Setup
```bash
# Configure alerts
python tools/auroractl.py configure-alerts --environment testnet

# Validate alert rules
curl -X GET "http://localhost:8080/metrics" | grep -E "(order_submit_latency|fill_rate|open_positions)"

# Test alert triggers
python scripts/test_alerts.py --simulate-failures
```

#### 4.2 Documentation Update
```bash
# Update deployment log
cat >> deployment_log.md << EOF
## Deployment $DEPLOY_TIMESTAMP
- Start Time: $(date)
- Version: $DEPLOY_TAG
- Environment: testnet
- Safe Mode: Enabled
- Status: In Progress
EOF

# Generate post-deployment report
python scripts/generate_deployment_report.py --deployment-id $DEPLOY_TIMESTAMP
```

---

## 🔄 Rollback Procedures

### Emergency Rollback (5 minutes)
```bash
# Immediate stop
python tools/auroractl.py stop-api
python tools/auroractl.py disarm

# Rollback to previous version
git checkout rollback_$DEPLOY_TIMESTAMP
docker build -t aurora:rollback .
docker run -d --name aurora-rollback aurora:rollback

# Validate rollback
curl -X GET "http://localhost:8080/health"
```

### Graceful Rollback (15 minutes)
```bash
# Close all positions
python tools/auroractl.py close-all-positions

# Wait for position closure
watch -n 5 'python tools/auroractl.py positions | jq ".open_positions | length"'

# Stop trading
curl -X POST "http://localhost:8080/aurora/disarm" -H "Authorization: Bearer $OPS_TOKEN"

# Switch to previous version
docker stop aurora-testnet
docker run -d --name aurora-rollback aurora:testnet-previous

# Validate
python -m pytest tests/smoke/ -q
```

### Configuration Rollback
```bash
# Restore configuration
cp configs_backup_$DEPLOY_TIMESTAMP/* ../../configs/

# Reload configuration
curl -X POST "http://localhost:8080/aurora/reload-config" -H "Authorization: Bearer $OPS_TOKEN"

# Validate
python tools/auroractl.py config-validate
```

---

## 📊 Monitoring & Alerting

### Key Metrics to Monitor
```bash
# Real-time monitoring
watch -n 10 '
echo "=== System Health ==="
python tools/auroractl.py health

echo -e "\n=== Trading Metrics ==="
python tools/auroractl.py metrics | jq ".order_count, .fill_rate, .pnl_realized"

echo -e "\n=== XAI Audit Trail ==="
tail -1 ../../logs/testnet_session_*/aurora_events.jsonl | jq ".event_type, .timestamp"
'
```

### Alert Thresholds
- **Order Latency P95** > 500ms → Warning
- **Fill Rate** < 90% → Warning, <80% → Critical
- **Open Positions** > Expected + 20% → Warning
- **Memory Usage** > 1GB → Warning
- **XAI Events Missing** > 0.01 ratio → Critical
- **Realized Loss** > 0.5% of capital → Emergency Stop

### Log Monitoring
```bash
# Monitor error logs
tail -f ../../logs/testnet_session_*/aurora.log | grep -i error

# Monitor XAI events
tail -f ../../logs/testnet_session_*/aurora_events.jsonl | jq 'select(.event_type == "ORDER.FILLED" or .event_type == "ERROR")'

# Monitor performance
tail -f ../../logs/testnet_session_*/aurora.log | grep -E "(latency|fill_rate|memory)"
```

---

## 📞 Emergency Contacts

### Primary Contacts
- **Engineering Lead:** [phone] / [slack]
- **DevOps On-Call:** [phone] / [slack]
- **Security On-Call:** [phone] / [slack]

### Escalation Path
1. **Level 1:** DevOps On-Call (0-15 min response)
2. **Level 2:** Engineering Lead (15-60 min response)
3. **Level 3:** Security Lead + Business Owner (1-4 hour response)

### Communication Channels
- **Slack:** #aurora-deployments
- **PagerDuty:** Aurora Testnet Deployments
- **Email:** aurora-alerts@company.com

---

## ✅ Post-Deployment Checklist

### Functional Validation
- [ ] API health checks pass
- [ ] Order submission works
- [ ] Fill processing works
- [ ] Position updates work
- [ ] XAI audit trail complete

### Performance Validation
- [ ] Order latency < 500ms P95
- [ ] Fill rate > 90%
- [ ] Memory usage < 1GB
- [ ] No error logs

### Monitoring Validation
- [ ] All alerts configured
- [ ] Dashboard accessible
- [ ] Log aggregation working
- [ ] Metrics collection working

### Documentation
- [ ] Deployment log updated
- [ ] Runbook validated
- [ ] Contacts verified
- [ ] Rollback procedures tested

---

## 🔗 Related Documents

- [Go/No-Go Checklist](./go_no_go_checklist.md)
- [CI Pipeline](../.github/workflows/ci-pipeline.yml)
- [Monitoring Dashboard](./monitoring_dashboard.md)
- [Incident Response Plan](./incident_response.md)
- [Configuration Guide](../configs/README.md)