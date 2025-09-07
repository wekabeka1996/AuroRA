# Іннциденти та тріаж - Aurora P3-E

## Огляд

Цей runbook містить процедури для ідентифікації, тріажу та вирішення інцидентів в Aurora P3-E.
Всі інциденти класифікуються за severity та мають визначені response times.

## Класифікація інцидентів

### Severity Levels

#### 🔴 **Critical (P0)**
- **Response:** Immediate (<5 хвилин)
- **Resolution:** <1 година
- **Impact:** Production down, significant revenue loss
- **Examples:** Circuit breaker OPEN, SSE availability <99%, CVaR breaches

#### 🟠 **High (P1)**
- **Response:** <15 хвилин
- **Resolution:** <4 години
- **Impact:** Degraded performance, partial revenue loss
- **Examples:** Execution latency p99 >300ms, SSE availability <99.5%

#### 🟡 **Medium (P2)**
- **Response:** <1 година
- **Resolution:** <24 години
- **Impact:** Minor degradation, monitoring alerts
- **Examples:** High reconnect rate, calibration drift

#### 🟢 **Low (P3)**
- **Response:** <4 години
- **Resolution:** <1 тиждень
- **Impact:** No production impact
- **Examples:** Log rotation issues, minor monitoring gaps

## Процедури тріажу

### 1. SSE Availability < 99.9%

#### Симптоми
- Alert: `SseAvailabilitySLOViolation`
- Метрика: `sse:availability_ratio:5m < 0.999`

#### Тріаж кроки
1. **Перевірити поточний стан:**
   ```bash
   curl -s https://aurora.example.com/healthz
   curl -s http://localhost:8001/metrics | grep sse_events
   ```

2. **Перевірити логи сервера:**
   ```bash
   sudo journalctl -u aurora-live-feed -f
   tail -f /opt/aurora/logs/aurora_events.jsonl
   ```

3. **Перевірити мережеві проблеми:**
   ```bash
   # Network connectivity
   ping -c 5 8.8.8.8

   # DNS resolution
   nslookup aurora.example.com

   # Firewall rules
   sudo ufw status
   ```

#### Можливі причини
- Network partition
- Server overload (CPU/Memory)
- Disk I/O issues
- Database connectivity problems
- SSL certificate issues

#### Дії для вирішення
1. **Перезапуск сервісу:**
   ```bash
   sudo systemctl restart aurora-live-feed
   ```

2. **Збільшити ресурси:**
   ```bash
   # Check resource usage
   top -p $(pgrep -f live_feed.py)
   free -h
   df -h /opt/aurora
   ```

3. **Очистити логи:**
   ```bash
   sudo ./scripts/log_rotate.sh
   ```

4. **Перевірити конфігурацію:**
   ```bash
   sudo nginx -t
   sudo systemctl status nginx
   ```

### 2. Circuit Breaker OPEN

#### Симптоми
- Alert: `CircuitBreakerOpen`
- Метрика: `circuit_breaker_state >= 2`
- Бізнес вплив: Trading suspended

#### Тріаж кроки
1. **Перевірити WHY-коди останніх відмов:**
   ```bash
   # Check recent policy decisions
   curl -s http://localhost:8001/metrics | grep policy_denied
   ```

2. **Перевірити ринкові умови:**
   - Spreads > threshold
   - Latency > SLA
   - API rate limits hit

3. **Перевірити калібрування:**
   ```bash
   curl -s http://localhost:9000/metrics | grep calibration
   ```

#### Можливі причини
- Wide spreads (market volatility)
- High latency (exchange issues)
- API rate limiting
- Incorrect calibration parameters

#### Дії для вирішення
1. **Тимчасове зниження активності:**
   ```bash
   # Reduce Kelly multiplier
   export KELLY_MULTIPLIER=0.5
   sudo systemctl restart aurora-runner
   ```

2. **Збільшити пороги:**
   ```bash
   # Increase spread thresholds
   export SPREAD_THRESHOLD=2.0  # from 1.5
   sudo systemctl restart aurora-runner
   ```

3. **Перевірити API limits:**
   ```bash
   # Check exchange API status
   curl -s https://api.exchange.com/status
   ```

### 3. Execution Latency p99 > SLA

#### Симптоми
- Alert: `ExecLatencyP99SLA`
- Метрика: `exec:latency_p99:10m > 300`

#### Тріаж кроки
1. **Перевірити розподіл латентності:**
   ```bash
   curl -s http://localhost:9000/metrics | grep exec_latency
   ```

2. **Перевірити мережевий ping:**
   ```bash
   ping -c 10 api.exchange.com
   ```

3. **Перевірити навантаження:**
   ```bash
   top -p $(pgrep -f run_live_aurora)
   iostat -x 1 5
   ```

#### Можливі причини
- Network latency
- Exchange API slowdown
- Local resource contention
- Queueing delays

#### Дії для вирішення
1. **Оптимізація мережі:**
   ```bash
   # Use different network interface
   # Enable TCP optimizations
   sudo sysctl -w net.ipv4.tcp_low_latency=1
   ```

2. **Зниження частоти:**
   ```bash
   # Reduce trading frequency
   export DECISIONS_PER_MINUTE=10  # from 30
   ```

3. **Переміщення ближче до exchange:**
   ```bash
   # Consider different region/AZ
   ```

### 4. Policy Deny Rate High

#### Симптоми
- Alert: `PolicyDenyRateHigh`
- Метрика: `policy:deny_ratio:15m > 0.35`

#### Тріаж кроки
1. **Перевірити deny reasons:**
   ```bash
   curl -s http://localhost:9000/metrics | grep policy_denied
   ```

2. **Перевірити калібрування:**
   ```bash
   curl -s http://localhost:9000/metrics | grep calibration
   ```

3. **Перевірити ринкові умови:**
   - Volatility
   - Spreads
   - Liquidity

#### Можливі причини
- Poor calibration (high ECE)
- Market conditions changed
- Overly conservative thresholds
- Model drift

#### Дії для вирішення
1. **Shrink p (тимчасово):**
   ```bash
   export P_THRESHOLD=0.5  # from 0.7
   sudo systemctl restart aurora-runner
   ```

2. **Перекалібрувати модель:**
   ```bash
   # Trigger recalibration
   curl -X POST http://localhost:8001/recalibrate
   ```

3. **Зменшити Kelly multiplier:**
   ```bash
   export KELLY_MULTIPLIER=0.3  # from 1.0
   ```

### 5. Calibration ECE High

#### Симптоми
- Alert: `CalibrationECEHigh`
- Метрика: `calibration_ece > 0.05`

#### Тріаж кроки
1. **Перевірити поточні метрики:**
   ```bash
   curl -s http://localhost:9000/metrics | grep calibration
   ```

2. **Перевірити дані для калібрування:**
   ```bash
   # Check recent trading data
   tail -100 /opt/aurora/logs/trades.jsonl
   ```

3. **Перевірити модель:**
   ```bash
   # Model validation
   python -c "import calibration; calibration.validate()"
   ```

#### Дії для вирішення
1. **Перекалібрувати:**
   ```bash
   python tools/calibrate.py --force
   ```

2. **Зменшити confidence:**
   ```bash
   export CONFIDENCE_THRESHOLD=0.8  # from 0.9
   ```

3. **Додати більше даних:**
   ```bash
   # Extend calibration window
   export CALIBRATION_DAYS=90  # from 30
   ```

## Ескалація

### L1 (First Response)
- **Time:** Immediate
- **Actions:**
  - Acknowledge alert
  - Gather initial diagnostics
  - Apply known fixes
  - Escalate if unresolved in 30 minutes

### L2 (Senior Engineer)
- **Trigger:** L1 unresolved >30 minutes
- **Actions:**
  - Deep dive analysis
  - Code reviews
  - Infrastructure changes
  - Coordinate with business

### L3 (Engineering Lead)
- **Trigger:** L2 unresolved >2 hours
- **Actions:**
  - Strategic decisions
  - Resource allocation
  - Communication with stakeholders
  - Post-mortem planning

### L4 (Executive)
- **Trigger:** L3 unresolved >4 hours
- **Actions:**
  - Business impact assessment
  - Crisis management
  - External communication
  - Recovery planning

## Post-Mortem

### Для кожного інциденту
1. **Timeline:** Detailed sequence of events
2. **Impact:** Quantitative business impact
3. **Root Cause:** Technical root cause analysis
4. **Actions:** Corrective and preventive actions
5. **Lessons:** What was learned

### Follow-up
- Implement fixes within 1 week
- Update documentation
- Improve monitoring/alerting
- Conduct training if needed

## Контакти

### On-Call Rotation
- **Primary:** alerts@aurora.example.com
- **Secondary:** +1-XXX-XXX-XXXX
- **Slack:** #aurora-incidents

### Key Personnel
- **SRE Lead:** sre@aurora.example.com
- **DevOps:** devops@aurora.example.com
- **Development:** dev@aurora.example.com
- **Business:** business@aurora.example.com