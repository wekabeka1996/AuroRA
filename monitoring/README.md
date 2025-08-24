# Monitoring Stack (Phase 0)

## Components
- Prometheus scrape endpoint: `/metrics` (FastAPI service)
- Exported metrics:
  - `aurora_prediction_latency_ms` (Histogram) with SLO bucketization
  - `aurora_kappa_plus` (Gauge)
  - `aurora_regime` (Gauge)
  - `aurora_prediction_requests_total` (Counter)

## Grafana Dashboard
Import `grafana_dashboard_example.json` into Grafana to visualize latency p95/p99, Kappa+, regime stream.

## Local Run
```
docker compose up -d prometheus grafana api
```
(Check your docker-compose.yml to ensure services names match.)

## Alerting (Next Steps)
- Add Prometheus alert rules: latency_p95 > 50ms for 5m, kappa_plus spikes, regime flip rate.
- Wire Alertmanager → Slack/Webhook.

## Roadmap
Phase 1: Add coverage/ECE metrics.
Phase 2: Add ICP quantile drift, DRO-ES objective, CTR/DCTS once implemented.
