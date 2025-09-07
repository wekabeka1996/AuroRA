# Aurora Monitoring Alert Rules

## Prometheus Alert Rules

### Critical Alerts (Immediate Action Required)

```yaml
groups:
  - name: aurora.critical
    rules:
      # Order Processing Critical
      - alert: AuroraOrderFillRateCritical
        expr: aurora_order_fill_rate < 0.8
        for: 5m
        labels:
          severity: critical
          team: engineering
        annotations:
          summary: "Critical: Order fill rate below 80%"
          description: "Order fill rate is {{ $value }}% (threshold: 80%)"
          runbook_url: "https://docs.aurora/runbooks/order-fill-rate-critical"

      - alert: AuroraOrderLatencyCritical
        expr: histogram_quantile(0.99, rate(aurora_order_submit_latency_bucket[5m])) > 2.0
        for: 5m
        labels:
          severity: critical
          team: engineering
        annotations:
          summary: "Critical: Order submit latency P99 > 2s"
          description: "Order submit latency P99 is {{ $value }}s (threshold: 2s)"
          runbook_url: "https://docs.aurora/runbooks/order-latency-critical"

      # Financial Risk Critical
      - alert: AuroraRealizedLossCritical
        expr: aurora_pnl_realized < -0.005  # 0.5% loss
        for: 5m
        labels:
          severity: critical
          team: risk
        annotations:
          summary: "Critical: Realized loss > 0.5% of capital"
          description: "Realized PnL is {{ $value }} (threshold: -0.005)"
          runbook_url: "https://docs.aurora/runbooks/realized-loss-critical"

      # System Health Critical
      - alert: AuroraAPIUnhealthy
        expr: up{job="aurora-api"} == 0
        for: 5m
        labels:
          severity: critical
          team: devops
        annotations:
          summary: "Critical: Aurora API is down"
          description: "Aurora API has been down for 5 minutes"
          runbook_url: "https://docs.aurora/runbooks/api-down"

      - alert: AuroraHighMemoryUsage
        expr: aurora_memory_usage_bytes / aurora_memory_limit_bytes > 0.95
        for: 10m
        labels:
          severity: critical
          team: devops
        annotations:
          summary: "Critical: Memory usage > 95%"
          description: "Memory usage is {{ $value | humanizePercentage }} (threshold: 95%)"
          runbook_url: "https://docs.aurora/runbooks/high-memory-usage"

      # Data Integrity Critical
      - alert: AuroraXAIEventLoss
        expr: aurora_xai_events_missing_ratio > 0.01
        for: 5m
        labels:
          severity: critical
          team: engineering
        annotations:
          summary: "Critical: XAI event loss > 1%"
          description: "XAI audit trail missing {{ $value | humanizePercentage }} of events"
          runbook_url: "https://docs.aurora/runbooks/xai-event-loss"

### Warning Alerts (Monitor and Investigate)

  - name: aurora.warning
    rules:
      # Order Processing Warning
      - alert: AuroraOrderFillRateWarning
        expr: aurora_order_fill_rate < 0.9
        for: 10m
        labels:
          severity: warning
          team: engineering
        annotations:
          summary: "Warning: Order fill rate below 90%"
          description: "Order fill rate is {{ $value }}% (threshold: 90%)"
          runbook_url: "https://docs.aurora/runbooks/order-fill-rate-warning"

      - alert: AuroraOrderLatencyWarning
        expr: histogram_quantile(0.95, rate(aurora_order_submit_latency_bucket[5m])) > 0.5
        for: 10m
        labels:
          severity: warning
          team: engineering
        annotations:
          summary: "Warning: Order submit latency P95 > 500ms"
          description: "Order submit latency P95 is {{ $value }}s (threshold: 500ms)"
          runbook_url: "https://docs.aurora/runbooks/order-latency-warning"

      # Position Management Warning
      - alert: AuroraOpenPositionsHigh
        expr: aurora_open_positions > aurora_expected_positions * 1.2
        for: 15m
        labels:
          severity: warning
          team: risk
        annotations:
          summary: "Warning: Open positions 20% above expected"
          description: "Open positions: {{ $value }} (expected: {{ $labels.expected_positions }})"
          runbook_url: "https://docs.aurora/runbooks/open-positions-high"

      # System Performance Warning
      - alert: AuroraCPUUsageHigh
        expr: rate(aurora_cpu_usage_percent[5m]) > 80
        for: 10m
        labels:
          severity: warning
          team: devops
        annotations:
          summary: "Warning: CPU usage > 80%"
          description: "CPU usage is {{ $value }}% (threshold: 80%)"
          runbook_url: "https://docs.aurora/runbooks/cpu-usage-high"

      - alert: AuroraDiskSpaceLow
        expr: (aurora_disk_free_bytes / aurora_disk_total_bytes) < 0.1
        for: 30m
        labels:
          severity: warning
          team: devops
        annotations:
          summary: "Warning: Disk space < 10%"
          description: "Free disk space is {{ $value | humanizePercentage }} (threshold: 10%)"
          runbook_url: "https://docs.aurora/runbooks/disk-space-low"

      # Test Quality Warning
      - alert: AuroraMutationScoreDrop
        expr: aurora_mutation_score < aurora_mutation_baseline - 0.05
        for: 1h
        labels:
          severity: warning
          team: qa
        annotations:
          summary: "Warning: Mutation score dropped > 5%"
          description: "Mutation score: {{ $value }} (baseline: {{ $labels.baseline }})"
          runbook_url: "https://docs.aurora/runbooks/mutation-score-drop"

### Info Alerts (Track for Trends)

  - name: aurora.info
    rules:
      # Deployment Events
      - alert: AuroraDeploymentStarted
        expr: aurora_deployment_status == 1
        labels:
          severity: info
          team: devops
        annotations:
          summary: "Info: Aurora deployment started"
          description: "Deployment {{ $labels.deployment_id }} started at {{ $value }}"

      - alert: AuroraDeploymentCompleted
        expr: aurora_deployment_status == 2
        labels:
          severity: info
          team: devops
        annotations:
          summary: "Info: Aurora deployment completed"
          description: "Deployment {{ $labels.deployment_id }} completed successfully"

      # Trading Activity
      - alert: AuroraHighTradingVolume
        expr: rate(aurora_orders_submitted_total[1h]) > 100
        labels:
          severity: info
          team: trading
        annotations:
          summary: "Info: High trading volume detected"
          description: "Order rate: {{ $value }}/hour (threshold: 100/hour)"

      # System Events
      - alert: AuroraConfigReload
        expr: aurora_config_reload_total > 0
        labels:
          severity: info
          team: devops
        annotations:
          summary: "Info: Configuration reloaded"
          description: "Configuration reloaded {{ $value }} times in the last hour"
```

## Grafana Dashboard Configuration

### Dashboard: Aurora System Health

```json
{
  "dashboard": {
    "title": "Aurora System Health",
    "tags": ["aurora", "trading", "system"],
    "timezone": "UTC",
    "panels": [
      {
        "title": "Order Fill Rate",
        "type": "stat",
        "targets": [
          {
            "expr": "aurora_order_fill_rate",
            "legendFormat": "Fill Rate"
          }
        ],
        "thresholds": [
          {"value": 0.8, "color": "red"},
          {"value": 0.9, "color": "yellow"},
          {"value": 0.95, "color": "green"}
        ]
      },
      {
        "title": "Order Submit Latency P95",
        "type": "stat",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, rate(aurora_order_submit_latency_bucket[5m]))",
            "legendFormat": "P95 Latency"
          }
        ],
        "thresholds": [
          {"value": 0.5, "color": "yellow"},
          {"value": 2.0, "color": "red"}
        ],
        "unit": "s"
      },
      {
        "title": "Realized PnL",
        "type": "stat",
        "targets": [
          {
            "expr": "aurora_pnl_realized",
            "legendFormat": "Realized PnL"
          }
        ],
        "thresholds": [
          {"value": -0.005, "color": "red"},
          {"value": 0, "color": "yellow"}
        ],
        "unit": "percent"
      },
      {
        "title": "XAI Event Coverage",
        "type": "stat",
        "targets": [
          {
            "expr": "1 - aurora_xai_events_missing_ratio",
            "legendFormat": "XAI Coverage"
          }
        ],
        "thresholds": [
          {"value": 0.99, "color": "green"},
          {"value": 0.95, "color": "yellow"},
          {"value": 0.90, "color": "red"}
        ],
        "unit": "percent"
      }
    ]
  }
}
```

## Alertmanager Configuration

```yaml
global:
  smtp_smarthost: 'smtp.company.com:587'
  smtp_from: 'aurora-alerts@company.com'
  smtp_auth_username: 'aurora-alerts@company.com'
  smtp_auth_password: 'password'

route:
  group_by: ['alertname', 'severity']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'aurora-alerts'
  routes:
    - match:
        severity: critical
      receiver: 'aurora-critical'
    - match:
        team: risk
      receiver: 'risk-team'
    - match:
        team: devops
      receiver: 'devops-team'

receivers:
  - name: 'aurora-alerts'
    email_configs:
      - to: 'engineering@company.com'
        subject: '[{{ .GroupLabels.alertname }}] Aurora Alert'
        body: |
          {{ range .Alerts }}
          Alert: {{ .Annotations.summary }}
          Description: {{ .Annotations.description }}
          Runbook: {{ .Annotations.runbook_url }}
          {{ end }}

  - name: 'aurora-critical'
    pagerduty_configs:
      - service_key: 'aurora-critical-service-key'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/.../.../...'
        channel: '#aurora-critical'
        title: '[CRITICAL] {{ .GroupLabels.alertname }}'
        text: |
          {{ range .Alerts }}
          *{{ .Annotations.summary }}*
          {{ .Annotations.description }}
          <{{ .Annotations.runbook_url }}|Runbook>
          {{ end }}

  - name: 'risk-team'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/.../.../...'
        channel: '#risk-alerts'

  - name: 'devops-team'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/.../.../...'
        channel: '#devops-alerts'
```

## Custom Metrics to Implement

### Application Metrics
```python
# In api/sli_metrics.py or observability/metrics.py

from prometheus_client import Counter, Gauge, Histogram

# Order Processing Metrics
ORDER_SUBMIT_LATENCY = Histogram(
    'aurora_order_submit_latency_seconds',
    'Time spent processing order submission',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

ORDER_FILL_RATE = Gauge(
    'aurora_order_fill_rate',
    'Ratio of filled orders to submitted orders'
)

# Position Metrics
OPEN_POSITIONS = Gauge(
    'aurora_open_positions',
    'Number of currently open positions'
)

EXPECTED_POSITIONS = Gauge(
    'aurora_expected_positions',
    'Expected number of positions based on strategy'
)

# PnL Metrics
PNL_REALIZED = Gauge(
    'aurora_pnl_realized',
    'Realized profit and loss as ratio of capital'
)

# XAI Audit Trail Metrics
XAI_EVENTS_TOTAL = Counter(
    'aurora_xai_events_total',
    'Total number of XAI events logged',
    ['event_type']
)

XAI_EVENTS_MISSING_RATIO = Gauge(
    'aurora_xai_events_missing_ratio',
    'Ratio of missing XAI events to expected events'
)

# System Metrics
MEMORY_USAGE = Gauge(
    'aurora_memory_usage_bytes',
    'Current memory usage in bytes'
)

CPU_USAGE = Gauge(
    'aurora_cpu_usage_percent',
    'Current CPU usage percentage'
)

# Test Quality Metrics
MUTATION_SCORE = Gauge(
    'aurora_mutation_score',
    'Current mutation testing score'
)

MUTATION_BASELINE = Gauge(
    'aurora_mutation_baseline',
    'Baseline mutation testing score'
)

# Deployment Metrics
DEPLOYMENT_STATUS = Gauge(
    'aurora_deployment_status',
    'Current deployment status (0=idle, 1=deploying, 2=success, 3=failed)',
    ['deployment_id']
)
```

## Monitoring Dashboards

### 1. Real-time Trading Dashboard
- Order submission rate (per minute)
- Fill rate over time
- Order latency distribution (P50, P95, P99)
- Active positions by symbol
- Realized PnL over time

### 2. System Health Dashboard
- API response times
- Memory and CPU usage
- Database connection pool status
- External API health (Binance, etc.)
- Error rates by component

### 3. Risk Management Dashboard
- Position size distribution
- Risk exposure by symbol
- Stop loss triggers
- Margin utilization
- Maximum drawdown tracking

### 4. Test Quality Dashboard
- Test coverage over time
- Mutation score trends
- Test execution times
- Flaky test detection
- CI pipeline success rates

## Log Aggregation Rules

```yaml
# Filebeat configuration for Aurora logs
filebeat.inputs:
  - type: log
    paths:
      - /var/log/aurora/*.log
      - /var/log/aurora/*/*.jsonl
    fields:
      service: aurora
      environment: testnet
    processors:
      - add_kubernetes_metadata:
          host: ${NODE_NAME}
          matchers:
          - logs_path:
              logs_path: "/var/log/containers/"

  - type: log
    paths:
      - /var/log/aurora/aurora_events.jsonl
    fields:
      service: aurora
      log_type: xai_events
    processors:
      - decode_json_fields:
          fields: ["message"]
          target: "aurora_event"
      - drop_fields:
          fields: ["message"]

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
  index: "aurora-%{+yyyy.MM.dd}"
```

This monitoring setup provides comprehensive coverage of Aurora's critical metrics with appropriate alerting thresholds and escalation paths.