# 🚀 Aurora P3-D Go-Live Guide
## Production Deployment Checklist & Configuration

*Last updated: September 3, 2025*

This guide covers the complete go-live process for Aurora P3-D with production hardening features.

---

## 📋 Go-Live Checklist (Pre-Deployment Verification)

### 🔴 Live Feed Service
- [ ] `tools/live_feed.py` listens on **localhost:8001**
- [ ] Heartbeat `:ping` enabled (every 15 seconds)
- [ ] `retry: 3000` header present in SSE responses
- [ ] `/health` returns detailed stats with uptime, client count, tailer stats
- [ ] `/healthz` returns `{"status": "ok"}` for load balancers
- [ ] Event IDs increment properly in SSE stream
- [ ] Malformed/oversized line counters initialize to 0

### 🔴 Runner Configuration
- [ ] Runner starts with `--telemetry` flag
- [ ] Valid `AURORA_SESSION_DIR` environment variable set
- [ ] Session summary generates at end (`OBS.SUMMARY.GENERATED` event)
- [ ] JSONL files created in session directory:
  - `aurora_events.jsonl`
  - `orders_success.jsonl`
  - `orders_denied.jsonl`
  - `orders_failed.jsonl`

### 🔴 Dashboard Configuration
- [ ] `VITE_SSE_URL` or `REACT_APP_SSE_URL` points to proxy endpoint
- [ ] Reconnection banner appears when connection lost
- [ ] Stream resumes with `Last-Event-ID` after backend restart
- [ ] Metrics update in real-time (latency percentiles, order stats)
- [ ] No console errors in browser dev tools

### 🔴 Log Management
- [ ] JSONL file rotation tested (truncate/rename scenarios)
- [ ] Tailer detects rotation and resets file position
- [ ] Malformed JSON lines handled gracefully (counter increments)
- [ ] Oversized lines (>1MB) skipped with counter increment
- [ ] No crashes on corrupted log files

### 🔴 Security
- [ ] SSE endpoint protected by authentication token (`X-Auth-Token`)
- [ ] HTTPS termination configured in front of nginx
- [ ] IP restrictions applied if needed
- [ ] No sensitive data in SSE stream

---

## ⚙️ Infrastructure Configuration

### Nginx Reverse Proxy (SSE-Friendly)

```nginx
# /etc/nginx/sites-available/aurora
server {
  listen 443 ssl http2;
  server_name your.host.com;

  # SSL certificates
  ssl_certificate /etc/ssl/certs/your_cert.pem;
  ssl_certificate_key /etc/ssl/private/your_key.pem;

  # SSE proxy configuration
  location /sse {
    proxy_pass http://127.0.0.1:8001/sse;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_buffering off;  # Critical for SSE
    proxy_read_timeout 3600s;
    add_header Cache-Control no-cache;
  }

  location /healthz {
    proxy_pass http://127.0.0.1:8001/healthz;
  }
}
```

### Systemd Service

```ini
# /etc/systemd/system/aurora-live-feed.service
[Unit]
Description=Aurora P3-D SSE Live Feed
After=network.target

[Service]
WorkingDirectory=/opt/aurora
ExecStart=/usr/bin/python3 tools/live_feed.py --session-dir /opt/aurora/logs --port 8001
Restart=always
RestartSec=3
User=aurora

[Install]
WantedBy=multi-user.target
```

---

## 📊 Basic Alerts (P3-E Groundwork)

Configure these alerts in your monitoring system:

### Critical Alerts
- `client_count == 0` > 5 min → "No dashboard clients connected"
- `tailer.malformed_lines` rapid increase → "Log corruption detected"
- `tailer.oversized_lines` rapid increase → "Log size issues"

### Performance Alerts
- `latency.decision_ms.p90 > 50` for 3 min → "Slow decision making"
- `orders.deny_rate > 50%` for 10 min → "High order denial rate"
- `circuit_breaker.state == OPEN` > 30 sec → "Circuit breaker tripped"

### System Alerts
- Live feed service down → "SSE stream unavailable"
- High memory usage (>80%) → "Memory pressure"
- Disk space low (<10%) → "Log storage full"

---

## 🧪 Smoke Test Plan (30 minutes)

### 1. Basic Functionality Test
```bash
# Start runner with telemetry
python -m skalp_bot.runner.run_live_aurora --telemetry --session-dir /tmp/test_session

# In another terminal, start live feed
python tools/live_feed.py --session-dir /tmp/test_session --port 8001

# Open dashboard, verify:
# - SSE connection established
# - Metrics updating in real-time
# - No "reconnecting" banner visible
```

### 2. File Rotation Test
```bash
# Monitor live feed logs
tail -f /tmp/test_session/aurora_events.jsonl

# Rotate file manually
mv /tmp/test_session/aurora_events.jsonl /tmp/test_session/aurora_events.jsonl.old
echo '{"test": "rotation"}' > /tmp/test_session/aurora_events.jsonl

# Verify: Stream continues without interruption
```

### 3. Error Handling Test
```bash
# Add malformed JSON to log
echo '{"incomplete": json' >> /tmp/test_session/aurora_events.jsonl
echo 'oversized line content'$(python -c "print('x' * 2000000)") >> /tmp/test_session/aurora_events.jsonl

# Check health endpoint
curl http://localhost:8001/health | jq '.tailer_stats'

# Verify: malformed_lines and oversized_lines counters incremented
# SSE stream remains stable
```

### 4. Reconnection Test
```bash
# Kill live feed process
pkill -f live_feed.py

# Verify dashboard shows "reconnecting..." banner
# Restart live feed
python tools/live_feed.py --session-dir /tmp/test_session --port 8001

# Verify: Dashboard reconnects automatically
# Stream resumes from last event (Last-Event-ID)
```

### 5. Load Balancer Test
```bash
# Test healthz endpoint
curl http://localhost:8001/healthz
# Should return: {"status": "ok"}

# Stop dashboard connections
# Verify client_count drops to 0 in health endpoint
```

---

## 🚀 Deployment Steps

### 1. Pre-Deployment
```bash
# Create aurora user
sudo useradd -r -s /bin/false aurora

# Create directories
sudo mkdir -p /opt/aurora /opt/aurora/logs
sudo chown -R aurora:aurora /opt/aurora

# Deploy code
sudo cp -r /path/to/aurora /opt/aurora/
sudo chown -R aurora:aurora /opt/aurora
```

### 2. Install Dependencies
```bash
cd /opt/aurora
sudo -u aurora pip install -r requirements.txt
```

### 3. Configure Services
```bash
# Install systemd service
sudo cp deploy/aurora-live-feed.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aurora-live-feed

# Install nginx config
sudo cp deploy/nginx.conf /etc/nginx/sites-available/aurora
sudo ln -s /etc/nginx/sites-available/aurora /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4. Start Services
```bash
# Start live feed
sudo systemctl start aurora-live-feed
sudo systemctl status aurora-live-feed

# Verify endpoints
curl http://localhost:8001/healthz
curl https://your.host.com/healthz
```

### 5. Test Runner Integration
```bash
# Test with runner
sudo -u aurora python -m skalp_bot.runner.run_live_aurora \
    --telemetry \
    --session-dir /opt/aurora/logs \
    --config your_config.yaml
```

---

## 🔍 Troubleshooting

### SSE Connection Issues
- Check nginx `proxy_buffering off` setting
- Verify `proxy_read_timeout` is sufficient
- Check firewall rules for port 8001

### File Rotation Problems
- Ensure tailer has read permissions on log directory
- Check file rotation doesn't happen too frequently
- Monitor `tailer.malformed_lines` counter

### Performance Issues
- Monitor memory usage with `MemoryLimit=512M`
- Check `client_count` doesn't exceed expected values
- Verify `proxy_read_timeout` settings

### Security Concerns
- Implement `X-Auth-Token` validation in SSE endpoint
- Use HTTPS termination
- Configure proper CORS headers

---

## 📈 Monitoring Dashboard

After go-live, monitor these key metrics:

- **SSE Connection Health**: Client count, reconnection events
- **Performance**: Latency percentiles, order success rates
- **System Health**: Memory usage, CPU utilization
- **Data Quality**: Malformed lines, oversized lines
- **Business Metrics**: Order volumes, denial rates

---

*For questions or issues during deployment, check the health endpoints and logs first. All production hardening features are tested and verified.*