# 👀 AURORA 24h Watch - PromQL Queries

## 🔥 Critical Failure Detection

### Hard-fail (exit=3) Detection
```promql
increase(ci_gating_exit_code_3_total[1h])
```
**Alert if > 0**

### Coverage Control Breach
```promql
aurora_ci_coverage_abs_err_ema > 0.08
```
**Alert if > warn threshold**

### DCTS Divergence (Robust vs Base)
```promql
(aurora_tvf2_dcts_robust_value - aurora_tvf2_dcts_base_value) / clamp_max(abs(aurora_tvf2_dcts_base_value), 1e-9)
```
**Alert if abs() > 0.85**

### DRO Health Factor P05
```promql
quantile_over_time(0.05, aurora_risk_dro_factor[24h])
```
**Alert if < 0.6**

### Warning Rate
```promql
rate(ci_gating_violation_total[1h])
```
**Alert if > 5% (0.05)**

---

## 📊 Dashboard Panels (Copy to Grafana)

### System Health Overview
```promql
# API Health
up{job="aurora_api"}

# Request Rate
rate(http_requests_total[5m])

# Error Rate
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])

# Response Time P95
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
```

### Model Quality Metrics
```promql
# Model Similarity
aurora_model_cosine_similarity

# Checkpoint Status
aurora_model_checkpoint_loaded

# Training Loss
aurora_training_loss_last

# Inference Latency
histogram_quantile(0.95, rate(aurora_inference_duration_seconds_bucket[5m]))
```

### Risk & Control Metrics
```promql
# DRO Factor Distribution
aurora_risk_dro_factor

# Coverage Precision
aurora_ci_coverage_precision_current

# Fallback Rate
rate(aurora_risk_fallback_triggered_total[5m])

# Model Confidence
aurora_model_confidence_mean
```

---

## ⚡ Quick Health Check (single query)

```promql
# Combined health score (0-1, where 1 = perfect health)
(
  (aurora_model_cosine_similarity > 0.995) +
  (quantile_over_time(0.05, aurora_risk_dro_factor[1h]) > 0.6) +
  (aurora_ci_coverage_abs_err_ema < 0.08) +
  (increase(ci_gating_exit_code_3_total[1h]) == 0) +
  (rate(ci_gating_violation_total[1h]) < 0.05)
) / 5
```
**Result: 1.0 = All systems healthy, 0.8+ = Good, <0.6 = Issues**

---

## 🚨 Instant Alert Rules (Prometheus)

```yaml
groups:
- name: aurora_ga_watch
  rules:
  - alert: AuroraHardFailure
    expr: increase(ci_gating_exit_code_3_total[5m]) > 0
    for: 0s
    labels:
      severity: critical
    annotations:
      summary: "AURORA hard failure detected (exit=3)"

  - alert: AuroraCoverageBreach
    expr: aurora_ci_coverage_abs_err_ema > 0.08
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Coverage control breach detected"

  - alert: AuroraDCTSDivergence
    expr: abs((aurora_tvf2_dcts_robust_value - aurora_tvf2_dcts_base_value) / clamp_max(abs(aurora_tvf2_dcts_base_value), 1e-9)) > 0.85
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "DCTS divergence detected"

  - alert: AuroraDROUnhealthy
    expr: quantile_over_time(0.05, aurora_risk_dro_factor[10m]) < 0.6
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "DRO health factor below threshold"

  - alert: AuroraHighWarningRate
    expr: rate(ci_gating_violation_total[5m]) > 0.05
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "High CI gating warning rate"
```

---

## 🔍 Investigation Queries

### When alerts fire, use these to investigate:

#### Recent Errors
```promql
increase(aurora_errors_total[30m])
```

#### Model Drift Analysis
```promql
# Compare current vs 24h ago
aurora_model_cosine_similarity offset 24h
```

#### Performance Regression
```promql
# Latency trend over last 4 hours
histogram_quantile(0.95, rate(aurora_inference_duration_seconds_bucket[5m])) offset 4h
```

#### Resource Usage Spike
```promql
# Memory usage
process_resident_memory_bytes / 1024 / 1024

# CPU usage
rate(process_cpu_seconds_total[5m]) * 100
```

---

## 📋 Copy-Paste Commands for CLI

### Quick Health Check
```bash
curl -s "http://localhost:9090/api/v1/query?query=(aurora_model_cosine_similarity>0.995%2Bquantile_over_time(0.05,aurora_risk_dro_factor[1h])>0.6%2Baurora_ci_coverage_abs_err_ema<0.08%2Bincrease(ci_gating_exit_code_3_total[1h])==0%2Brate(ci_gating_violation_total[1h])<0.05)/5" | jq '.data.result[0].value[1]'
```

### Exit=3 Check
```bash
curl -s "http://localhost:9090/api/v1/query?query=increase(ci_gating_exit_code_3_total[1h])" | jq '.data.result[0].value[1] // "0"'
```

### Coverage Status
```bash
curl -s "http://localhost:9090/api/v1/query?query=aurora_ci_coverage_abs_err_ema" | jq '.data.result[0].value[1]'
```

---

*Use these queries during 24h watch to monitor GA health in real-time*