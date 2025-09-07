#!/bin/bash
# Aurora P3-D Pre-Launch Verification Script
# Run 24 hours before production go-live

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "🔍 Aurora P3-D Pre-Launch Verification"
echo "====================================="
echo ""

PASSED=0
FAILED=0

check_result() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $1${NC}"
        ((PASSED++))
    else
        echo -e "${RED}✗ $1${NC}"
        ((FAILED++))
    fi
}

# 1. Service Status
echo "1. Service Status Checks"
echo "------------------------"
sudo systemctl is-active --quiet aurora-live-feed
check_result "Aurora live feed service is running"

sudo systemctl is-active --quiet nginx
check_result "Nginx service is running"

echo ""

# 2. Health Checks
echo "2. Health Endpoint Checks"
echo "-------------------------"
if curl -s --max-time 5 http://localhost:8001/healthz | grep -q '"status":"ok"'; then
    check_result "Healthz endpoint responding"
else
    check_result "Healthz endpoint failed"
fi

if curl -s --max-time 10 http://localhost:8001/health | jq -e '.status' >/dev/null 2>&1; then
    check_result "Health endpoint responding with valid JSON"
else
    check_result "Health endpoint failed or invalid JSON"
fi

echo ""

# 3. Authentication
echo "3. Authentication Checks"
echo "------------------------"
if [ -f /opt/aurora/secrets/auth_token ]; then
    check_result "Auth token file exists"
    if [ -r /opt/aurora/secrets/auth_token ]; then
        check_result "Auth token file is readable"
    else
        check_result "Auth token file is not readable"
    fi
else
    check_result "Auth token file missing"
fi

# Test SSE with auth
if [ -f /opt/aurora/secrets/auth_token ]; then
    TOKEN=$(cat /opt/aurora/secrets/auth_token)
    if curl -s -H "X-Auth-Token: $TOKEN" http://localhost:8001/sse | head -1 | grep -q "retry:"; then
        check_result "SSE authentication working"
    else
        check_result "SSE authentication failed"
    fi
fi

echo ""

# 4. Configuration
echo "4. Configuration Checks"
echo "-----------------------"
sudo nginx -t >/dev/null 2>&1
check_result "Nginx configuration is valid"

if [ -f /etc/systemd/system/aurora-live-feed.service ]; then
    check_result "Systemd service file exists"
else
    check_result "Systemd service file missing"
fi

if [ -f /opt/aurora/scripts/log_rotate.sh ] && [ -x /opt/aurora/scripts/log_rotate.sh ]; then
    check_result "Log rotation script exists and is executable"
else
    check_result "Log rotation script missing or not executable"
fi

echo ""

# 5. Storage & Disk
echo "5. Storage & Disk Checks"
echo "------------------------"
DISK_USAGE=$(df /opt/aurora 2>/dev/null | tail -1 | awk '{print $5}' | sed 's/%//' || echo "100")
if [ "$DISK_USAGE" -lt 85 ] 2>/dev/null; then
    check_result "Disk usage acceptable (${DISK_USAGE}%)"
elif [ "$DISK_USAGE" -lt 95 ] 2>/dev/null; then
    echo -e "${YELLOW}⚠ Disk usage high (${DISK_USAGE}%) - monitor closely${NC}"
    ((PASSED++))
else
    check_result "Disk usage critical (${DISK_USAGE}%)"
fi

if [ -d /opt/aurora/logs/archive ]; then
    check_result "Log archive directory exists"
else
    check_result "Log archive directory missing"
fi

echo ""

# 6. Time Synchronization
echo "6. Time Synchronization"
echo "-----------------------"
if timedatectl status 2>/dev/null | grep -q "synchronized: yes"; then
    check_result "System time is synchronized"
else
    check_result "System time not synchronized"
fi

echo ""

# 7. SSL/TLS
echo "7. SSL/TLS Checks"
echo "------------------"
if [ -f /etc/ssl/certs/your_cert.pem ]; then
    if openssl x509 -checkend 86400 -in /etc/ssl/certs/your_cert.pem >/dev/null 2>&1; then
        check_result "SSL certificate is valid (>24h remaining)"
    else
        check_result "SSL certificate expired or expiring soon"
    fi
else
    echo -e "${YELLOW}⚠ SSL certificate path not checked - update script with correct path${NC}"
fi

echo ""

# 8. Log Files
echo "8. Log File Checks"
echo "------------------"
if [ -f /opt/aurora/logs/aurora_events.jsonl ]; then
    check_result "Aurora events log file exists"
    LINES=$(wc -l < /opt/aurora/logs/aurora_events.jsonl 2>/dev/null || echo "0")
    if [ "$LINES" -gt 0 ]; then
        check_result "Aurora events log has content (${LINES} lines)"
    else
        check_result "Aurora events log is empty"
    fi
else
    check_result "Aurora events log file missing"
fi

echo ""

# 9. Network
echo "9. Network Checks"
echo "------------------"
if curl -s --max-time 5 https://your-domain.com/healthz 2>/dev/null | grep -q "ok"; then
    check_result "Public health endpoint accessible"
else
    echo -e "${YELLOW}⚠ Public endpoint not accessible - check domain configuration${NC}"
fi

echo ""

# 10. Monitoring
echo "10. Monitoring Checks"
echo "---------------------"
if command -v prometheus >/dev/null 2>&1 || curl -s http://localhost:9090/-/healthy >/dev/null 2>&1; then
    check_result "Prometheus monitoring detected"
else
    echo -e "${YELLOW}⚠ Prometheus not detected - ensure monitoring is configured${NC}"
fi

echo ""
echo "📊 Verification Summary"
echo "======================="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "Total: $((PASSED + FAILED))"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 All checks passed! System is ready for production deployment.${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Schedule go-live window with stakeholders"
    echo "2. Prepare rollback procedures"
    echo "3. Notify monitoring team"
    echo "4. Execute final smoke test in production"
    exit 0
else
    echo -e "${RED}❌ $FAILED check(s) failed. Address issues before production deployment.${NC}"
    echo ""
    echo "Common fixes:"
    echo "- Check service status: sudo systemctl status aurora-live-feed"
    echo "- Verify configurations: sudo nginx -t"
    echo "- Check logs: sudo journalctl -u aurora-live-feed -f"
    exit 1
fi