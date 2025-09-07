#!/bin/bash
# Aurora P3-D Emergency Rollback Script
# Execute only in case of critical production failure

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "🚨 Aurora P3-D Emergency Rollback"
echo "=================================="
echo ""

# Configuration
BACKUP_DIR="/opt/aurora/backup/$(date +%Y%m%d_%H%M%S)"
ROLLBACK_LOG="/var/log/aurora_rollback.log"

# Functions
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$ROLLBACK_LOG"
}

error() {
    echo -e "${RED}❌ $1${NC}" | tee -a "$ROLLBACK_LOG"
    exit 1
}

success() {
    echo -e "${GREEN}✓ $1${NC}" | tee -a "$ROLLBACK_LOG"
}

warning() {
    echo -e "${YELLOW}⚠ $1${NC}" | tee -a "$ROLLBACK_LOG"
}

info() {
    echo -e "${BLUE}ℹ $1${NC}" | tee -a "$ROLLBACK_LOG"
}

# Pre-rollback checks
echo "1. Pre-Rollback Validation"
echo "--------------------------"
log "Starting emergency rollback procedure"

# Check if we have backup files
if [ ! -d "/opt/aurora/backup/latest" ]; then
    error "No backup directory found at /opt/aurora/backup/latest"
fi

# Check system resources
MEM_USAGE=$(free | grep Mem | awk '{printf "%.0f", $3/$2 * 100.0}')
if [ $MEM_USAGE -gt 90 ]; then
    warning "High memory usage (${MEM_USAGE}%) - rollback may be slow"
fi

CPU_USAGE=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\1/" | awk '{print 100 - $1}')
if (( $(echo "$CPU_USAGE > 90" | bc -l) )); then
    warning "High CPU usage (${CPU_USAGE}%) - rollback may be slow"
fi

success "Pre-rollback validation completed"

echo ""

# Create rollback backup
echo "2. Creating Rollback Backup"
echo "---------------------------"
log "Creating backup of current state"

mkdir -p "$BACKUP_DIR"
cp -r /opt/aurora/* "$BACKUP_DIR/" 2>/dev/null || true
cp -r /etc/systemd/system/aurora-live-feed.service "$BACKUP_DIR/" 2>/dev/null || true
cp -r /etc/nginx/sites-available/aurora "$BACKUP_DIR/" 2>/dev/null || true

success "Current state backed up to $BACKUP_DIR"

echo ""

# Stop services
echo "3. Stopping Services"
echo "--------------------"
log "Stopping Aurora services"

# Stop nginx
if sudo systemctl is-active --quiet nginx; then
    sudo systemctl stop nginx
    success "Nginx stopped"
else
    warning "Nginx was not running"
fi

# Stop Aurora service
if sudo systemctl is-active --quiet aurora-live-feed; then
    sudo systemctl stop aurora-live-feed
    success "Aurora live feed stopped"
else
    warning "Aurora live feed was not running"
fi

# Kill any remaining processes
pkill -f "live_feed.py" || true
pkill -f "python.*aurora" || true

success "All services stopped"

echo ""

# Restore from backup
echo "4. Restoring from Backup"
echo "------------------------"
log "Restoring from latest backup"

BACKUP_SOURCE="/opt/aurora/backup/latest"

# Restore application files
if [ -d "$BACKUP_SOURCE/app" ]; then
    cp -r "$BACKUP_SOURCE/app"/* /opt/aurora/
    success "Application files restored"
fi

# Restore configuration files
if [ -f "$BACKUP_SOURCE/aurora-live-feed.service" ]; then
    sudo cp "$BACKUP_SOURCE/aurora-live-feed.service" /etc/systemd/system/
    sudo systemctl daemon-reload
    success "Systemd service configuration restored"
fi

if [ -f "$BACKUP_SOURCE/aurora.nginx" ]; then
    sudo cp "$BACKUP_SOURCE/aurora.nginx" /etc/nginx/sites-available/aurora
    success "Nginx configuration restored"
fi

# Restore secrets (if they exist in backup)
if [ -f "$BACKUP_SOURCE/auth_token" ]; then
    sudo cp "$BACKUP_SOURCE/auth_token" /opt/aurora/secrets/
    success "Auth token restored"
fi

success "All files restored from backup"

echo ""

# Restart services
echo "5. Restarting Services"
echo "----------------------"
log "Restarting services with rolled back configuration"

# Start Aurora service
sudo systemctl start aurora-live-feed
sleep 3

if sudo systemctl is-active --quiet aurora-live-feed; then
    success "Aurora live feed restarted"
else
    error "Failed to restart Aurora live feed"
fi

# Test health endpoint
if curl -s --max-time 10 http://localhost:8001/healthz | grep -q '"status":"ok"'; then
    success "Aurora health check passed"
else
    error "Aurora health check failed after rollback"
fi

# Start nginx
sudo systemctl start nginx
sleep 2

if sudo systemctl is-active --quiet nginx; then
    success "Nginx restarted"
else
    error "Failed to restart Nginx"
fi

# Test public endpoint
if curl -s --max-time 10 https://your-domain.com/healthz | grep -q '"status":"ok"'; then
    success "Public health endpoint responding"
else
    warning "Public health endpoint not responding - check DNS/load balancer"
fi

success "All services restarted successfully"

echo ""

# Post-rollback validation
echo "6. Post-Rollback Validation"
echo "---------------------------"
log "Running post-rollback validation"

# Check service status
sudo systemctl status aurora-live-feed --no-pager | grep -q "active (running)"
check_result "Aurora service status"

sudo systemctl status nginx --no-pager | grep -q "active (running)"
check_result "Nginx service status"

# Check log files
if [ -f /opt/aurora/logs/aurora_events.jsonl ]; then
    success "Log files present"
else
    warning "Log files missing - may need manual recreation"
fi

# Check disk space
DISK_USAGE=$(df /opt/aurora 2>/dev/null | tail -1 | awk '{print $5}' | sed 's/%//' || echo "100")
if [ "$DISK_USAGE" -lt 90 ]; then
    success "Disk usage acceptable (${DISK_USAGE}%)"
else
    warning "High disk usage (${DISK_USAGE}%) after rollback"
fi

success "Post-rollback validation completed"

echo ""

# Update backup pointer
echo "7. Updating Backup Pointers"
echo "----------------------------"
log "Updating latest backup pointer"

# Update the latest backup symlink
ln -sf "$BACKUP_DIR" /opt/aurora/backup/latest

success "Backup pointers updated"

echo ""

# Final status
echo "8. Rollback Summary"
echo "-------------------"
log "Emergency rollback completed successfully"

echo -e "${GREEN}🎉 Emergency rollback completed successfully!${NC}"
echo ""
echo "📊 Rollback Summary:"
echo "• Services stopped and restarted"
echo "• Files restored from backup"
echo "• Configuration validated"
echo "• Health checks passed"
echo ""
echo "🔍 Next Steps:"
echo "1. Monitor system for 15 minutes"
echo "2. Run smoke tests: ./deploy/smoke_test.sh"
echo "3. Notify stakeholders of rollback"
echo "4. Investigate root cause of original failure"
echo "5. Plan controlled re-deployment"
echo ""
echo "📝 Rollback Log: $ROLLBACK_LOG"
echo "📁 Rollback Backup: $BACKUP_DIR"
echo ""
echo "⚠️  Remember to investigate the original failure before re-deploying!"

exit 0