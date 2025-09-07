# Aurora P3-D Operations Runbook
## Production Troubleshooting Guide

*Version: 1.0 | Last Updated: September 3, 2025*

---

## 🚨 Critical Issues

### SSE Stream Not Connecting

**Symptoms:**
- Dashboard shows "reconnecting..." banner
- `client_count == 0` in health endpoint
- No metrics updates in dashboard

**Immediate Checks:**
```bash
# 1. Check service status
sudo systemctl status aurora-live-feed

# 2. Check health endpoints
curl -k https://your-domain.com/healthz
curl -k https://your-domain.com/health | jq '.sse_clients'

# 3. Check nginx logs
sudo tail -f /var/log/nginx/error.log

# 4. Check application logs
sudo journalctl -u aurora-live-feed -f
```

**Common Causes & Solutions:**

1. **Authentication Failure**
   ```bash
   # Check if auth token is configured
   ls -la /opt/aurora/secrets/auth_token
   cat /opt/aurora/secrets/auth_token

   # Verify dashboard is sending correct token
   # Check browser dev tools -> Network -> SSE request headers
   ```

2. **Nginx Configuration**
   ```bash
   # Test nginx config
   sudo nginx -t
   sudo systemctl reload nginx

   # Check proxy_buffering is off
   grep -A 5 "location /sse" /etc/nginx/sites-enabled/aurora
   ```

3. **CORS Issues**
   ```bash
   # Check CORS headers in nginx
   curl -I -k https://your-domain.com/sse
   # Should see: Access-Control-Allow-Origin: *
   ```

4. **Network/Firewall**
   ```bash
   # Check if port 8001 is accessible locally
   curl http://localhost:8001/healthz

   # Check firewall rules
   sudo ufw status
   ```

### Dead/Empty Stream

**Symptoms:**
- SSE connects but no data flows
- Dashboard shows static metrics
- `tailer.malformed_lines` or `oversized_lines` increasing

**Diagnosis:**
```bash
# Check log file status
ls -la /opt/aurora/logs/*.jsonl

# Check tailer stats
curl -k https://your-domain.com/health | jq '.tailer_stats'

# Check file rotation
find /opt/aurora/logs -name "*.jsonl" -exec wc -l {} \;

# Check for file rotation issues
sudo journalctl -u aurora-live-feed | grep -i rotation
```

**Solutions:**

1. **File Rotation Detected**
   ```bash
   # Check if files were rotated during tailing
   ls -la /opt/aurora/logs/archive/

   # Verify tailer reset file position
   curl -k https://your-domain.com/health | jq '.tailer_stats.file_positions'
   ```

2. **Malformed JSON**
   ```bash
   # Check recent malformed lines
   sudo journalctl -u aurora-live-feed | grep "Malformed JSON" | tail -10

   # Validate JSON in log files
   python3 -c "
   import json
   with open('/opt/aurora/logs/aurora_events.jsonl', 'r') as f:
       for i, line in enumerate(f):
           try:
               json.loads(line.strip())
           except json.JSONDecodeError as e:
               print(f'Line {i+1}: {e}')
               break
   "
   ```

3. **Oversized Lines**
   ```bash
   # Find oversized lines
   find /opt/aurora/logs -name "*.jsonl" -exec awk 'length > 1048576 {print NR ": " length " bytes"}' {} \;
   ```

### Latency Spikes

**Symptoms:**
- `decision_ms.p90 > 50` for extended periods
- Dashboard shows high latency metrics
- Circuit breaker may trip

**Investigation:**
```bash
# Check system resources
top -p $(pgrep -f live_feed.py)
free -h
iostat -x 1 5

# Check for CPU/memory pressure
sudo journalctl -u aurora-live-feed | grep -i "memory\|cpu"

# Check NTP sync
timedatectl status

# Check circuit breaker status
curl -k https://your-domain.com/health | jq '.current_metrics.circuit_breaker'
```

**Common Causes:**
1. **System Resource Exhaustion**
   - Increase memory limits in systemd
   - Check for memory leaks
   - Monitor CPU usage patterns

2. **Time Sync Issues**
   ```bash
   # Check NTP status
   sudo systemctl status chrony
   chronyc tracking
   ```

3. **High Event Volume**
   - Check `metrics_buffer_size`
   - Monitor event rates
   - Consider increasing buffer limits

### High Denial Rate (>50%)

**Symptoms:**
- `orders.deny_rate > 50%` sustained
- Governance α-exhaustion
- Market condition changes

**Response:**
```bash
# Check governance status
curl -k https://your-domain.com/health | jq '.current_metrics.governance'

# Review recent orders
tail -20 /opt/aurora/logs/orders_denied.jsonl | jq '.reason'

# Check market conditions (external)
# Review governance configuration
cat /opt/aurora/config/governance.yaml
```

---

## 🔧 Standard Maintenance

### Daily Checks
```bash
# Health verification
curl -k https://your-domain.com/healthz
curl -k https://your-domain.com/health | jq '.status'

# Resource monitoring
sudo systemctl status aurora-live-feed
df -h /opt/aurora

# Log rotation status
ls -la /opt/aurora/logs/archive/ | wc -l
```

### Weekly Maintenance
```bash
# Manual log rotation test
/opt/aurora/scripts/log_rotate.sh

# SSL certificate check
openssl x509 -in /etc/ssl/certs/your_cert.pem -text -noout | grep -A 2 "Validity"

# Security audit
sudo journalctl -u aurora-live-feed | grep -i "unauthorized\|error\|fail"
```

### Monthly Reviews
- Review alert thresholds
- Update dependencies
- Security patches
- Performance optimization

---

## 📞 Escalation Matrix

### Level 1 (Ops Team)
- Service restarts
- Configuration changes
- Log analysis
- Basic troubleshooting

### Level 2 (Dev Team)
- Code changes required
- Architecture issues
- Performance optimization
- Security incidents

### Level 3 (Management)
- Business impact assessment
- Stakeholder communication
- Disaster recovery
- Compliance issues

---

## 🚀 Emergency Procedures

### Service Down (< 5 min SLA)
1. **Immediate Assessment**
   ```bash
   sudo systemctl status aurora-live-feed
   curl -k https://your-domain.com/healthz
   ```

2. **Quick Recovery**
   ```bash
   sudo systemctl restart aurora-live-feed
   sudo systemctl reload nginx
   ```

3. **Verification**
   ```bash
   curl -k https://your-domain.com/healthz
   curl -k https://your-domain.com/health | jq '.status'
   ```

### Data Loss Incident
1. **Stop Processing**
   ```bash
   sudo systemctl stop aurora-live-feed
   ```

2. **Backup Current State**
   ```bash
   cp -r /opt/aurora/logs /opt/aurora/logs.backup.$(date +%Y%m%d_%H%M%S)
   ```

3. **Restore from Archive**
   ```bash
   # Restore from last known good backup
   cp /opt/aurora/logs.backup.latest/* /opt/aurora/logs/
   ```

4. **Resume Operations**
   ```bash
   sudo systemctl start aurora-live-feed
   ```

---

## 📊 Monitoring Dashboards

### Key Metrics to Monitor
- SSE connection count and stability
- Latency percentiles (P50, P90, P95)
- Error rates (malformed, oversized lines)
- System resources (CPU, memory, disk)
- Order success/denial rates
- Circuit breaker status

### Alert Response Times
- Critical: Immediate (< 5 min)
- High: Within 15 minutes
- Medium: Within 1 hour
- Low: Within 4 hours

---

*This runbook should be updated after each incident with lessons learned.*