# Aurora Testnet Deployment Runbook

**Version:** 1.0
**Last Updated:** 2025-09-07
**Authors:** Aurora DevOps Team

## Overview

This runbook provides step-by-step instructions for deploying Aurora to the testnet environment. The deployment process includes pre-deployment validation, safe-mode deployment, monitoring, and rollback procedures.

## Prerequisites

### Environment Requirements
- AWS CLI configured with appropriate credentials
- Docker installed and running
- Python 3.11+ with required dependencies
- Access to Aurora testnet infrastructure

### Access Requirements
- AWS ECR push permissions
- ECS deployment permissions
- Testnet database access
- Monitoring system access (Prometheus/Grafana)

### Pre-deployment Checklist
- [ ] CI/CD pipeline passed all quality gates
- [ ] Coverage > 90% (lines), > 85% (branches)
- [ ] Mutation score > 80% for critical modules
- [ ] XAI audit trail validation passed
- [ ] Security scan passed (no HIGH/CRITICAL issues)
- [ ] Performance benchmarks within thresholds
- [ ] All integration tests passed

## Deployment Steps

### Phase 1: Pre-deployment Validation

#### 1.1 Environment Setup
```bash
# Set deployment environment variables
export AURORA_ENV=testnet
export AURORA_MODE=live
export AWS_REGION=us-east-1
export ECR_REPO=123456789012.dkr.ecr.us-east-1.amazonaws.com/aurora

# Authenticate with AWS
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_REPO
```

#### 1.2 Code Validation
```bash
# Run local validation suite
python -m pytest tests/smoke/ -v
python tools/check_xai.py --validate-events
python tools/validate_config.py --env testnet

# Validate coverage and mutation
python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=90
python scripts/run_mutation_tests.py --compare --baseline artifacts/baselines/mutation_baseline.json
```

#### 1.3 Configuration Validation
```bash
# Validate testnet configuration
python -c "
from common.config import load_config
config = load_config('configs/testnet.yaml')
print('Configuration validation passed')
"

# Check environment variables
python -c "
import os
required_vars = ['AURORA_API_KEY', 'DATABASE_URL', 'REDIS_URL']
missing = [v for v in required_vars if not os.getenv(v)]
if missing:
    print(f'Missing environment variables: {missing}')
    exit(1)
print('Environment variables validated')
"
```

### Phase 2: Safe-Mode Deployment

#### 2.1 Build and Push Docker Image
```bash
# Build testnet image
TAG=$(date +%Y%m%d_%H%M%S)
docker build -t aurora:testnet-$TAG \
  --build-arg AURORA_MODE=live \
  --build-arg AURORA_SIMULATOR_MODE=true \
  .

# Tag and push to ECR
docker tag aurora:testnet-$TAG $ECR_REPO:testnet-$TAG
docker push $ECR_REPO:testnet-$TAG

echo "Docker image pushed: $ECR_REPO:testnet-$TAG"
```

#### 2.2 Deploy to Testnet (Safe Mode)
```bash
# Update ECS service with new task definition
TASK_DEF_ARN=$(aws ecs describe-task-definition \
  --task-definition aurora-testnet \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)

# Create new task definition
NEW_TASK_DEF=$(aws ecs register-task-definition \
  --family aurora-testnet \
  --container-definitions '[
    {
      "name": "aurora-api",
      "image": "'$ECR_REPO:testnet-$TAG'",
      "essential": true,
      "portMappings": [
        {
          "containerPort": 8080,
          "hostPort": 8080,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "AURORA_MODE", "value": "live"},
        {"name": "AURORA_SIMULATOR_MODE", "value": "true"},
        {"name": "AURORA_SAFE_MODE", "value": "true"}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/aurora-testnet",
          "awslogs-region": "'$AWS_REGION'",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]' \
  --cpu "256" \
  --memory "512" \
  --network-mode "awsvpc" \
  --requires-compatibilities "FARGATE" \
  --execution-role-arn "arn:aws:iam::123456789012:role/ecsTaskExecutionRole" \
  --task-role-arn "arn:aws:iam::123456789012:role/auroraTaskRole")

# Deploy new version
aws ecs update-service \
  --cluster aurora-testnet \
  --service aurora-api \
  --task-definition aurora-testnet \
  --force-new-deployment
```

#### 2.3 Health Check Validation
```bash
# Wait for deployment and health checks
echo "Waiting for deployment to complete..."
for i in {1..30}; do
  HEALTH=$(aws ecs describe-services \
    --cluster aurora-testnet \
    --services aurora-api \
    --query 'services[0].deployments[0].rolloutState' \
    --output text)

  if [ "$HEALTH" = "COMPLETED" ]; then
    echo "Deployment completed successfully"
    break
  fi

  echo "Waiting... ($i/30)"
  sleep 30
done

# API health check
for i in {1..10}; do
  if curl -f -s http://testnet.aurora.internal/health > /dev/null; then
    echo "API health check passed"
    break
  fi
  echo "Health check failed, retrying... ($i/10)"
  sleep 10
done
```

### Phase 3: Post-deployment Validation

#### 3.1 Smoke Tests
```bash
# Run smoke tests against testnet
export AURORA_API_URL=http://testnet.aurora.internal

python -m pytest tests/smoke/ -v --tb=short \
  --junitxml=artifacts/testnet_smoke_results.xml

# Validate XAI events are being generated
python -c "
import requests
import time

# Make a test trade request
response = requests.post(f'{os.getenv(\"AURORA_API_URL\")}/pretrade/check',
  json={
    'symbol': 'BTCUSDT',
    'side': 'buy',
    'size': 0.01,
    'price': 50000.0
  })

if response.status_code == 200:
    print('Trade request successful')
    time.sleep(2)  # Wait for events to be written

    # Check XAI events
    events_response = requests.get(f'{os.getenv(\"AURORA_API_URL\")}/events/recent')
    if events_response.status_code == 200:
        events = events_response.json()
        trace_ids = set(e.get('trace_id') for e in events if e.get('trace_id'))
        if len(trace_ids) > 0:
            print(f'XAI events validated: {len(events)} events, {len(trace_ids)} unique traces')
        else:
            print('WARNING: No trace_ids found in events')
    else:
        print('WARNING: Could not fetch events')
else:
    print(f'ERROR: Trade request failed: {response.status_code}')
"
```

#### 3.2 Performance Validation
```bash
# Run performance tests against testnet
python -m pytest tests/performance/ -v \
  --benchmark-only \
  --benchmark-json=artifacts/testnet_performance.json

# Validate against baseline
python -c "
import json

with open('artifacts/testnet_performance.json') as f:
    results = json.load(f)

# Check key metrics
thresholds = {
    'test_order_submit_latency': 0.5,  # 500ms
    'test_fill_processing': 0.1,       # 100ms
    'test_position_update': 0.05       # 50ms
}

failed = []
for benchmark in results.get('benchmarks', []):
    name = benchmark['name']
    mean_time = benchmark['stats']['mean']

    if name in thresholds and mean_time > thresholds[name]:
        failed.append(f'{name}: {mean_time:.3f}s > {thresholds[name]}s')

if failed:
    print('Performance validation failed:')
    for failure in failed:
        print(f'  - {failure}')
    exit(1)
else:
    print('Performance validation passed')
"
```

#### 3.3 Monitoring Setup
```bash
# Validate monitoring is working
echo "Validating monitoring setup..."

# Check Prometheus metrics
curl -s http://testnet.aurora.internal/metrics | grep -E "(aurora_|order_|trade_)" | head -10

# Check Grafana dashboards
curl -s http://grafana.testnet.aurora.internal/api/health

# Validate alert rules
python -c "
import requests

prometheus_url = 'http://prometheus.testnet.aurora.internal'
response = requests.get(f'{prometheus_url}/api/v1/rules')

if response.status_code == 200:
    rules = response.json()
    aurora_rules = [r for r in rules.get('data', {}).get('groups', []) if 'aurora' in r.get('name', '').lower()]
    print(f'Found {len(aurora_rules)} Aurora alert rules')
else:
    print('WARNING: Could not validate Prometheus rules')
"
```

### Phase 4: Go-Live Decision

#### 4.1 Final Validation Checklist
- [ ] API responding correctly
- [ ] XAI events being generated with proper trace_ids
- [ ] Performance within acceptable thresholds
- [ ] Error rates below 1%
- [ ] Monitoring alerts configured
- [ ] Logs being collected properly
- [ ] Database connections healthy

#### 4.2 Go-Live Command
```bash
# Remove safe mode restrictions
aws ecs update-service \
  --cluster aurora-testnet \
  --service aurora-api \
  --task-definition aurora-testnet-live \
  --force-new-deployment

echo "Aurora testnet deployment completed successfully!"
echo "Monitor dashboards at: http://grafana.testnet.aurora.internal"
```

## Rollback Procedures

### Emergency Rollback
```bash
# Immediate rollback to previous version
PREVIOUS_TASK_DEF=$(aws ecs describe-task-definition \
  --task-definition aurora-testnet \
  --query 'taskDefinition.taskDefinitionArn' \
  --output text)

aws ecs update-service \
  --cluster aurora-testnet \
  --service aurora-api \
  --task-definition aurora-testnet-previous \
  --force-new-deployment

echo "Rollback initiated to: $PREVIOUS_TASK_DEF"
```

### Gradual Rollback
```bash
# Scale down new deployment
aws ecs update-service \
  --cluster aurora-testnet \
  --service aurora-api \
  --desired-count 0

# Scale up previous version
aws ecs update-service \
  --cluster aurora-testnet \
  --service aurora-previous \
  --desired-count 2
```

## Monitoring and Alerts

### Key Metrics to Monitor
- **API Latency:** p95 < 500ms
- **Error Rate:** < 1%
- **XAI Coverage:** > 99%
- **Order Fill Rate:** > 95%
- **Memory Usage:** < 80%
- **CPU Usage:** < 70%

### Alert Thresholds
```yaml
# Critical Alerts
- alert: HighErrorRate
  expr: rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m]) > 0.05
  for: 5m

- alert: XAIMissing
  expr: aurora_xai_events_total - aurora_trades_total > 0
  for: 10m

- alert: HighLatency
  expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 1.0
  for: 5m

# Warning Alerts
- alert: CoverageDrop
  expr: aurora_test_coverage < 90
  for: 15m

- alert: MutationScoreDrop
  expr: aurora_mutation_score < 80
  for: 15m
```

## Stop Conditions

### Automatic Stop Conditions
- **Coverage Drop:** If line coverage < 85% or branch coverage < 75%
- **Mutation Score:** If mutation score drops > 10% from baseline
- **XAI Coverage:** If XAI event coverage < 95%
- **Performance:** If p95 latency > 2s or error rate > 5%
- **Security:** If HIGH/CRITICAL security issues detected

### Manual Stop Conditions
- **Business Logic Issues:** Unexpected trading behavior
- **Data Corruption:** Invalid data in database
- **External Dependencies:** Issues with exchanges or data providers
- **Resource Exhaustion:** Memory/CPU usage > 90%

## Communication Plan

### Deployment Notification
```bash
# Slack notification
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Aurora testnet deployment started - Monitor: http://grafana.testnet.aurora.internal"}' \
  $SLACK_WEBHOOK_URL
```

### Rollback Notification
```bash
# Alert team of rollback
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"🚨 Aurora testnet rollback initiated - Check logs"}' \
  $SLACK_WEBHOOK_URL
```

## Post-deployment Tasks

### 1. Update Documentation
- Update deployment tags in documentation
- Update monitoring dashboard links
- Update contact information

### 2. Performance Baseline Update
```bash
# Update performance baselines
cp artifacts/testnet_performance.json artifacts/baselines/performance_baseline.json
cp artifacts/testnet_coverage.json artifacts/baselines/coverage_baseline.json
```

### 3. Monitoring Validation
- Verify all alerts are working
- Test alert notifications
- Validate dashboard accuracy

### 4. Team Handover
- Document any issues encountered
- Update known issues list
- Schedule post-mortem if needed

## Troubleshooting

### Common Issues

#### Issue: Health Check Failing
```bash
# Check container logs
aws ecs describe-tasks --cluster aurora-testnet --tasks $(aws ecs list-tasks --cluster aurora-testnet --service-name aurora-api --query 'taskArns[0]' --output text) --query 'tasks[0].taskArn' --output text | xargs aws ecs describe-tasks --cluster aurora-testnet --tasks

# Check application logs
aws logs tail /ecs/aurora-testnet --follow
```

#### Issue: XAI Events Not Generated
```bash
# Check XAI logger configuration
curl http://testnet.aurora.internal/debug/xai_config

# Validate event storage
curl http://testnet.aurora.internal/events/count
```

#### Issue: Performance Degradation
```bash
# Check resource usage
aws ecs describe-tasks --cluster aurora-testnet --tasks $(aws ecs list-tasks --cluster aurora-testnet --service-name aurora-api --query 'taskArns[0]' --output text)

# Profile application
curl http://testnet.aurora.internal/debug/profile
```

## Contact Information

### Emergency Contacts
- **DevOps Lead:** devops@aurora.com | +1-555-0101
- **Security Team:** security@aurora.com | +1-555-0102
- **Business Stakeholders:** biz@aurora.com | +1-555-0103

### Monitoring
- **Grafana:** http://grafana.testnet.aurora.internal
- **Prometheus:** http://prometheus.testnet.aurora.internal
- **Logs:** AWS CloudWatch /ecs/aurora-testnet

---

**Remember:** Always test rollback procedures before going live with production traffic!