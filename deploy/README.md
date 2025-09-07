# Aurora P3-D Deployment Package

This directory contains all necessary files for production deployment of Aurora P3-D Live Feed system.

## 📁 Files Overview

### Configuration Files
- **`nginx.conf`** - Nginx reverse proxy configuration optimized for SSE
- **`aurora-live-feed.service`** - Systemd service file for live feed

### Documentation
- **`GO_LIVE_GUIDE.md`** - Complete go-live checklist and deployment guide
- **`alerts.yml`** - Monitoring alerts configuration for various systems

### Testing
- **`smoke_test.sh`** - Automated smoke test script (30-minute verification)

## 🚀 Quick Deployment

### 1. Install Dependencies
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install nginx python3 python3-pip jq curl

# Install Python dependencies
pip install -r ../requirements.txt
```

### 2. Configure Services
```bash
# Copy configurations
sudo cp nginx.conf /etc/nginx/sites-available/aurora
sudo cp aurora-live-feed.service /etc/systemd/system/

# Enable services
sudo ln -s /etc/nginx/sites-available/aurora /etc/nginx/sites-enabled/
sudo systemctl daemon-reload
sudo systemctl enable aurora-live-feed
```

### 3. Run Smoke Tests
```bash
chmod +x smoke_test.sh
./smoke_test.sh
```

### 4. Start Production Services
```bash
sudo systemctl start aurora-live-feed
sudo systemctl reload nginx
```

## 🔍 Verification

After deployment, verify everything works:

```bash
# Check service status
sudo systemctl status aurora-live-feed

# Test endpoints
curl https://your-domain.com/healthz
curl https://your-domain.com/health

# Check logs
sudo journalctl -u aurora-live-feed -f
```

## 📊 Monitoring Setup

1. Configure alerts from `alerts.yml` in your monitoring system
2. Set up dashboards for key metrics
3. Configure log aggregation
4. Set up automated health checks

## 🆘 Troubleshooting

- **SSE not connecting**: Check nginx `proxy_buffering off` setting
- **Service crashes**: Check logs with `journalctl -u aurora-live-feed`
- **High error rates**: Review log files for corruption
- **Performance issues**: Monitor memory and CPU usage

## 📚 Documentation

For detailed deployment instructions, see `GO_LIVE_GUIDE.md`.

---

*Generated for Aurora P3-D production deployment - September 2025*