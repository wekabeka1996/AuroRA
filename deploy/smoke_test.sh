#!/bin/bash
# Aurora P3-D Post-Deployment Smoke Test
# Run immediately after production deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "🚀 Aurora P3-D Post-Deployment Smoke Test"
echo "========================================="
echo ""

PASSED=0
FAILED=0
WARNINGS=0

check_result() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $1${NC}"
        ((PASSED++))
    else
        echo -e "${RED}✗ $1${NC}"
        ((FAILED++))
    fi
}

warn_result() {
    echo -e "${YELLOW}⚠ $1${NC}"
    ((WARNINGS++))
}

info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Load auth token
if [ -f /opt/aurora/secrets/auth_token ]; then
    AUTH_TOKEN=$(cat /opt/aurora/secrets/auth_token)
    info "Auth token loaded"
else
    echo -e "${RED}❌ Auth token file not found at /opt/aurora/secrets/auth_token${NC}"
    exit 1
fi

# Test 1: Basic Health Checks
echo "1. Basic Health Checks"
echo "----------------------"
info "Testing healthz endpoint..."
if curl -s --max-time 5 https://your-domain.com/healthz | grep -q '"status":"ok"'; then
    check_result "Healthz endpoint responding"
else
    check_result "Healthz endpoint failed"
fi

info "Testing health endpoint..."
if curl -s --max-time 10 https://your-domain.com/health | jq -e '.status' >/dev/null 2>&1; then
    check_result "Health endpoint responding with valid JSON"
else
    check_result "Health endpoint failed or invalid JSON"
fi

echo ""

# Test 2: Authentication
echo "2. Authentication Tests"
echo "-----------------------"
info "Testing SSE without authentication..."
if curl -s --max-time 5 -w "%{http_code}" https://your-domain.com/sse | tail -1 | grep -q "401"; then
    check_result "SSE properly rejects unauthenticated requests"
else
    check_result "SSE authentication bypass detected"
fi

info "Testing SSE with header authentication..."
if curl -s --max-time 5 -H "X-Auth-Token: $AUTH_TOKEN" https://your-domain.com/sse | head -1 | grep -q "retry:"; then
    check_result "SSE header authentication working"
else
    check_result "SSE header authentication failed"
fi

info "Testing SSE with query parameter authentication..."
if curl -s --max-time 5 "https://your-domain.com/sse?token=$AUTH_TOKEN" | head -1 | grep -q "retry:"; then
    check_result "SSE query parameter authentication working"
else
    check_result "SSE query parameter authentication failed"
fi

echo ""

# Test 3: SSE Stream Functionality
echo "3. SSE Stream Functionality"
echo "---------------------------"
info "Testing SSE stream connectivity (10 second test)..."
timeout 10 curl -s -H "X-Auth-Token: $AUTH_TOKEN" https://your-domain.com/sse > /tmp/sse_test.log 2>&1 &
CURL_PID=$!

sleep 5

if kill -0 $CURL_PID 2>/dev/null; then
    kill $CURL_PID 2>/dev/null
    check_result "SSE stream connection maintained"
else
    check_result "SSE stream connection failed"
fi

# Check for SSE format
if grep -q "data:" /tmp/sse_test.log 2>/dev/null; then
    check_result "SSE data format correct"
else
    warn_result "No SSE data received (may be normal if no events)"
fi

rm -f /tmp/sse_test.log

echo ""

# Test 4: Security Headers
echo "4. Security Headers"
echo "-------------------"
info "Testing security headers..."
HEADERS=$(curl -s -I https://your-domain.com/healthz)

if echo "$HEADERS" | grep -q "Strict-Transport-Security:"; then
    check_result "HSTS header present"
else
    check_result "HSTS header missing"
fi

if echo "$HEADERS" | grep -q "Content-Security-Policy:"; then
    check_result "CSP header present"
else
    check_result "CSP header missing"
fi

if echo "$HEADERS" | grep -q "X-Frame-Options:"; then
    check_result "X-Frame-Options header present"
else
    check_result "X-Frame-Options header missing"
fi

echo ""

# Test 5: CORS
echo "5. CORS Configuration"
echo "---------------------"
info "Testing CORS headers..."
CORS_HEADERS=$(curl -s -H "Origin: https://unauthorized-domain.com" -I https://your-domain.com/healthz)

if echo "$CORS_HEADERS" | grep -q "Access-Control-Allow-Origin: https://your-domain.com"; then
    check_result "CORS properly restricts origins"
elif echo "$CORS_HEADERS" | grep -q "Access-Control-Allow-Origin: \*"; then
    warn_result "CORS allows all origins (review for production)"
else
    check_result "CORS configuration present"
fi

echo ""

# Test 6: Load Test
echo "6. Load Test"
echo "------------"
info "Testing concurrent connections (light load)..."
for i in {1..5}; do
    curl -s --max-time 5 -H "X-Auth-Token: $AUTH_TOKEN" https://your-domain.com/sse > /dev/null &
    PIDS[$i]=$!
done

sleep 3

ALIVE=0
for pid in "${PIDS[@]}"; do
    if kill -0 $pid 2>/dev/null; then
        ((ALIVE++))
    fi
    kill $pid 2>/dev/null
done

if [ $ALIVE -ge 3 ]; then
    check_result "Concurrent connections handled ($ALIVE/5 successful)"
else
    check_result "Concurrent connections failed ($ALIVE/5 successful)"
fi

echo ""

# Test 7: Error Handling
echo "7. Error Handling"
echo "-----------------"
info "Testing invalid token..."
if curl -s --max-time 5 -H "X-Auth-Token: invalid_token" -w "%{http_code}" https://your-domain.com/sse | tail -1 | grep -q "401"; then
    check_result "Invalid token properly rejected"
else
    check_result "Invalid token handling failed"
fi

info "Testing malformed request..."
if curl -s --max-time 5 -X POST https://your-domain.com/sse -w "%{http_code}" | tail -1 | grep -q "405"; then
    check_result "Malformed request properly rejected"
else
    check_result "Malformed request handling failed"
fi

echo ""

# Test 8: Monitoring Integration
echo "8. Monitoring Integration"
echo "-------------------------"
info "Checking service metrics..."
if curl -s --max-time 5 http://localhost:8001/metrics 2>/dev/null | grep -q "aurora_"; then
    check_result "Service metrics exposed"
else
    warn_result "Service metrics not accessible (check internal endpoint)"
fi

echo ""

# Test 9: Log Rotation
echo "9. Log Rotation"
echo "---------------"
info "Checking log files..."
if [ -f /opt/aurora/logs/aurora_events.jsonl ]; then
    check_result "Log file exists"
    if [ -w /opt/aurora/logs/aurora_events.jsonl ]; then
        check_result "Log file is writable"
    else
        check_result "Log file is not writable"
    fi
else
    check_result "Log file missing"
fi

echo ""

# Test 10: System Resources
echo "10. System Resources"
echo "--------------------"
info "Checking system resources..."
CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1}')
if (( $(echo "$CPU_USAGE < 80" | bc -l) )); then
    check_result "CPU usage acceptable (${CPU_USAGE}%)"
else
    warn_result "High CPU usage (${CPU_USAGE}%)"
fi

MEM_USAGE=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
if [ $MEM_USAGE -lt 80 ]; then
    check_result "Memory usage acceptable (${MEM_USAGE}%)"
else
    warn_result "High memory usage (${MEM_USAGE}%)"
fi

echo ""

# Summary
echo "📊 Smoke Test Summary"
echo "====================="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "Warnings: $WARNINGS"
echo "Total Checks: $((PASSED + FAILED + WARNINGS))"
echo ""

if [ $FAILED -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}🎉 All smoke tests passed! System is production-ready.${NC}"
        echo ""
        echo "✅ Deployment successful - proceed with confidence"
        exit 0
    else
        echo -e "${YELLOW}⚠️ Smoke tests passed with $WARNINGS warning(s). Review before full production use.${NC}"
        echo ""
        echo "⚠️ Address warnings before scaling up traffic"
        exit 0
    fi
else
    echo -e "${RED}❌ $FAILED smoke test(s) failed. Do not proceed with production traffic.${NC}"
    echo ""
    echo "🚨 Immediate action required:"
    echo "1. Check service logs: sudo journalctl -u aurora-live-feed -f"
    echo "2. Verify configuration: sudo nginx -t"
    echo "3. Test locally: curl -H 'X-Auth-Token: $AUTH_TOKEN' http://localhost:8001/sse"
    echo "4. Contact on-call engineer"
    exit 1
fi