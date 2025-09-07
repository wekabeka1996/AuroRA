#!/bin/bash
# Aurora P3-D Automated Deployment Script
# Complete production deployment with all security and monitoring features

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
INSTALL_DIR="/opt/aurora"
USER="aurora"
GROUP="aurora"
DOMAIN="your-domain.com"
EMAIL="alerts@your-domain.com"

# Functions
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a /var/log/aurora_deploy.log
}

success() {
    echo -e "${GREEN}✓ $1${NC}" | tee -a /var/log/aurora_deploy.log
}

warning() {
    echo -e "${YELLOW}⚠ $1${NC}" | tee -a /var/log/aurora_deploy.log
}

error() {
    echo -e "${RED}❌ $1${NC}" | tee -a /var/log/aurora_deploy.log
    exit 1
}

info() {
    echo -e "${BLUE}ℹ $1${NC}" | tee -a /var/log/aurora_deploy.log
}

# Pre-flight checks
echo "🚀 Aurora P3-D Automated Deployment"
echo "==================================="
log "Starting automated deployment"

if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo)"
fi

# Check Ubuntu version
if ! grep -q "Ubuntu 22.04" /etc/os-release; then
    warning "Not Ubuntu 22.04 - some features may not work correctly"
fi

echo ""

# 1. System Preparation
echo "1. System Preparation"
echo "---------------------"
info "Updating system packages..."
apt update && apt upgrade -y
success "System packages updated"

# Install required packages
info "Installing required packages..."
apt install -y python3 python3-pip nginx certbot python3-certbot-nginx jq curl mailutils
success "Required packages installed"

# Create aurora user
if ! id "$USER" &>/dev/null; then
    useradd -r -s /bin/false "$USER"
    success "Aurora user created"
else
    success "Aurora user already exists"
fi

echo ""

# 2. Directory Structure
echo "2. Directory Structure"
echo "----------------------"
info "Creating directory structure..."

mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR/backup"
mkdir -p "$INSTALL_DIR/scripts"
mkdir -p "$INSTALL_DIR/secrets"
mkdir -p "$INSTALL_DIR/configs"

chown -R "$USER:$GROUP" "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"
chmod 700 "$INSTALL_DIR/secrets"

success "Directory structure created"

echo ""

# 3. Application Deployment
echo "3. Application Deployment"
echo "-------------------------"
info "Deploying application files..."

# Copy application files (assuming current directory contains the code)
cp -r * "$INSTALL_DIR/" 2>/dev/null || true
cp -r .[^.]* "$INSTALL_DIR/" 2>/dev/null || true

# Make scripts executable
chmod +x "$INSTALL_DIR/scripts/"*.sh
chmod +x "$INSTALL_DIR/deploy/"*.sh

success "Application files deployed"

echo ""

# 4. Python Dependencies
echo "4. Python Dependencies"
echo "----------------------"
info "Installing Python dependencies..."

cd "$INSTALL_DIR"
pip3 install -r requirements.txt
pip3 install gunicorn

success "Python dependencies installed"

echo ""

# 5. Authentication Setup
echo "5. Authentication Setup"
echo "-----------------------"
info "Setting up authentication..."

# Generate random auth token
AUTH_TOKEN=$(openssl rand -hex 32)
echo "$AUTH_TOKEN" > "$INSTALL_DIR/secrets/auth_token"
chmod 600 "$INSTALL_DIR/secrets/auth_token"
chown "$USER:$GROUP" "$INSTALL_DIR/secrets/auth_token"

success "Authentication token generated"

echo ""

# 6. SSL Certificate Setup
echo "6. SSL Certificate Setup"
echo "-----------------------"
info "Setting up SSL certificates..."

# Check if domain is configured
if [ "$DOMAIN" = "your-domain.com" ]; then
    warning "Domain not configured - using self-signed certificate"
    # Generate self-signed certificate
    openssl req -x509 -newkey rsa:4096 -keyout /etc/ssl/private/aurora.key -out /etc/ssl/certs/aurora.pem -days 365 -nodes -subj "/C=US/ST=State/L=City/O=Organization/CN=$DOMAIN"
else
    # Use certbot for Let's Encrypt
    certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "$EMAIL"
fi

success "SSL certificates configured"

echo ""

# 7. Nginx Configuration
echo "7. Nginx Configuration"
echo "----------------------"
info "Configuring Nginx..."

# Backup existing config
cp /etc/nginx/sites-available/default /etc/nginx/sites-available/default.backup 2>/dev/null || true

# Deploy nginx configuration
cp "$INSTALL_DIR/deploy/nginx.conf" /etc/nginx/sites-available/aurora

# Update domain in nginx config
sed -i "s/your-domain.com/$DOMAIN/g" /etc/nginx/sites-available/aurora

# Enable site
ln -sf /etc/nginx/sites-available/aurora /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test configuration
nginx -t
success "Nginx configuration deployed"

echo ""

# 8. Systemd Service
echo "8. Systemd Service"
echo "------------------"
info "Configuring systemd service..."

cp "$INSTALL_DIR/deploy/aurora-live-feed.service" /etc/systemd/system/

# Update paths in service file
sed -i "s|/opt/aurora|$INSTALL_DIR|g" /etc/systemd/system/aurora-live-feed.service
sed -i "s|/usr/bin/python3|/usr/bin/python3|g" /etc/systemd/system/aurora-live-feed.service

systemctl daemon-reload
success "Systemd service configured"

echo ""

# 9. Log Rotation Setup
echo "9. Log Rotation Setup"
echo "---------------------"
info "Setting up log rotation..."

# Create logrotate configuration
cat > /etc/logrotate.d/aurora << EOF
/opt/aurora/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 aurora aurora
    postrotate
        systemctl reload aurora-live-feed || true
    endscript
}
EOF

success "Log rotation configured"

echo ""

# 10. Cron Jobs Setup
echo "10. Cron Jobs Setup"
echo "-------------------"
info "Setting up automated tasks..."

# Install cron jobs
cp "$INSTALL_DIR/deploy/aurora-backup" /etc/cron.d/

# Update paths in cron file
sed -i "s|/opt/aurora|$INSTALL_DIR|g" /etc/cron.d/aurora-backup

success "Cron jobs configured"

echo ""

# 11. Monitoring Setup
echo "11. Monitoring Setup"
echo "--------------------"
info "Setting up monitoring..."

# Install Prometheus node exporter (if not present)
if ! systemctl is-active --quiet prometheus-node-exporter; then
    apt install -y prometheus-node-exporter
    systemctl enable prometheus-node-exporter
    systemctl start prometheus-node-exporter
    success "Prometheus node exporter installed"
else
    success "Prometheus node exporter already running"
fi

echo ""

# 12. Firewall Configuration
echo "12. Firewall Configuration"
echo "--------------------------"
info "Configuring firewall..."

# Enable UFW if not enabled
ufw --force enable

# Allow SSH, HTTP, HTTPS
ufw allow ssh
ufw allow 80
ufw allow 443

# Allow internal Aurora port
ufw allow 8001

success "Firewall configured"

echo ""

# 13. Service Startup
echo "13. Service Startup"
echo "-------------------"
info "Starting services..."

# Start Aurora service
systemctl enable aurora-live-feed
systemctl start aurora-live-feed

# Start Nginx
systemctl enable nginx
systemctl start nginx

# Verify services are running
if systemctl is-active --quiet aurora-live-feed; then
    success "Aurora service started"
else
    error "Aurora service failed to start"
fi

if systemctl is-active --quiet nginx; then
    success "Nginx service started"
else
    error "Nginx service failed to start"
fi

echo ""

# 14. Health Verification
echo "14. Health Verification"
echo "-----------------------"
info "Running health checks..."

# Wait for services to fully start
sleep 5

# Test internal health
if curl -s --max-time 5 http://localhost:8001/healthz | grep -q '"status":"ok"'; then
    success "Internal health check passed"
else
    error "Internal health check failed"
fi

# Test public health
if curl -s --max-time 10 https://$DOMAIN/healthz | grep -q '"status":"ok"'; then
    success "Public health check passed"
else
    warning "Public health check failed - check DNS propagation"
fi

# Test SSE endpoint
if curl -s --max-time 5 -H "X-Auth-Token: $AUTH_TOKEN" https://$DOMAIN/sse | head -1 | grep -q "retry:"; then
    success "SSE endpoint responding"
else
    error "SSE endpoint not responding"
fi

echo ""

# 15. Backup Creation
echo "15. Backup Creation"
echo "-------------------"
info "Creating initial backup..."

"$INSTALL_DIR/scripts/automated_backup.sh"

success "Initial backup created"

echo ""

# Final status
echo "🎉 Deployment Complete!"
echo "======================="
success "Aurora P3-D deployed successfully"

echo ""
echo "📊 Deployment Summary:"
echo "• Application installed to: $INSTALL_DIR"
echo "• Domain configured: $DOMAIN"
echo "• Auth token: $AUTH_TOKEN"
echo "• SSL certificates: Configured"
echo "• Services: Running"
echo "• Monitoring: Enabled"
echo "• Backups: Automated"
echo ""

echo "🔧 Next Steps:"
echo "1. Update DNS records if needed"
echo "2. Configure monitoring dashboards"
echo "3. Set up alert notifications"
echo "4. Run pre-launch verification:"
echo "   sudo $INSTALL_DIR/deploy/pre_launch_check.sh"
echo "5. Run smoke tests:"
echo "   sudo $INSTALL_DIR/deploy/smoke_test.sh"
echo ""

echo "📝 Important Information:"
echo "• Auth Token: $AUTH_TOKEN (save securely)"
echo "• Health URL: https://$DOMAIN/healthz"
echo "• SSE URL: https://$DOMAIN/sse"
echo "• Logs: $INSTALL_DIR/logs/"
echo "• Backups: $INSTALL_DIR/backup/"
echo ""

echo "📞 Support:"
echo "• Logs: /var/log/aurora_deploy.log"
echo "• Service status: sudo systemctl status aurora-live-feed"
echo "• Emergency rollback: sudo $INSTALL_DIR/deploy/emergency_rollback.sh"
echo ""

log "Automated deployment completed successfully"
echo "✅ Aurora P3-D is ready for production!"

exit 0