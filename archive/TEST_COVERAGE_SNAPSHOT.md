# Aurora Test Coverage Snapshot

**Generated:** 2025-09-07 16:51:00

## Executive Summary

| Metric | Value |
|--------|-------|
| **Overall Line Coverage** | 54.7% |
| **Overall Branch Coverage** | 37.1% |
| **Lines Covered** | 5,481/10,029 |
| **Branches Covered** | 1,034/2,788 |
| **Modules Analyzed** | 21 |

## Coverage Status

🔴 **POOR** - Line coverage is below 70%

🔴 **POOR** - Branch coverage is below 50%

## Module-Level Coverage Analysis

| Module | Line Coverage | Branch Coverage | Files | Lines | Branches |
|--------|---------------|-----------------|-------|-------|----------|
| observability | 3.3% | N/A | 2 | 2/60 | 0/15 |
| config | 12.2% | 0.5% | 6 | 113/924 | 1/191 |
| ingestion | 21.4% | 2.7% | 1 | 36/168 | 1/37 |
| calibration | 22.4% | 5.5% | 2 | 123/550 | 4/73 |
| universe | 27.4% | N/A | 3 | 51/186 | 0/17 |
| signal | 34.8% | 25.0% | 4 | 138/397 | 16/64 |
| sizing | 35.6% | 35.4% | 2 | 112/315 | 23/65 |
| scalper | 46.0% | 5.0% | 3 | 104/226 | 1/20 |
| regime | 53.6% | 33.3% | 4 | 120/224 | 9/27 |
| features | 56.3% | 55.7% | 6 | 479/851 | 59/106 |
| xai | 58.8% | 55.0% | 4 | 150/255 | 22/40 |
| root | 60.1% | 49.0% | 14 | 746/1241 | 76/155 |
| risk | 63.4% | 76.9% | 1 | 59/93 | 10/13 |
| aurora | 64.3% | 77.8% | 2 | 240/373 | 42/54 |
| logging | 65.2% | 75.0% | 2 | 75/115 | 15/20 |
| execution | 66.1% | 66.8% | 19 | 1512/2286 | 173/259 |
| tca | 78.5% | 88.9% | 7 | 551/702 | 80/90 |
| market | 79.3% | 68.4% | 2 | 111/140 | 13/19 |
| governance | 81.7% | 84.1% | 4 | 723/885 | 106/126 |
| infra | 93.5% | 50.0% | 1 | 29/31 | 1/2 |
| utils | 100.0% | 100.0% | 1 | 7/7 | 1/1 |

## Critical Modules (< 70% Line Coverage)

### observability
- **Line Coverage:** 3.3%
- **Lines:** 2/60
- **Files:** 2

**Worst Files:**
- `observability/metrics_bridge.py`: 0.0%

### config
- **Line Coverage:** 12.2%
- **Lines:** 113/924
- **Files:** 6

**Worst Files:**
- `config/api_integration.py`: 0.0%
- `config/production_loader.py`: 0.0%
- `config/schema_validator.py`: 12.0%

### ingestion
- **Line Coverage:** 21.4%
- **Lines:** 36/168
- **Files:** 1

**Worst Files:**
- `ingestion/normalizer.py`: 21.4%

### calibration
- **Line Coverage:** 22.4%
- **Lines:** 123/550
- **Files:** 2

**Worst Files:**
- `calibration/icp.py`: 17.3%
- `calibration/calibrator.py`: 25.8%

### universe
- **Line Coverage:** 27.4%
- **Lines:** 51/186
- **Files:** 3

**Worst Files:**
- `universe/ranking.py`: 22.5%
- `universe/hysteresis.py`: 35.2%

### signal
- **Line Coverage:** 34.8%
- **Lines:** 138/397
- **Files:** 4

**Worst Files:**
- `signal/leadlag_hy.py`: 15.0%
- `signal/fdr.py`: 41.2%

### sizing
- **Line Coverage:** 35.6%
- **Lines:** 112/315
- **Files:** 2

**Worst Files:**
- `sizing/kelly.py`: 30.3%
- `sizing/portfolio.py`: 49.4%

### scalper
- **Line Coverage:** 46.0%
- **Lines:** 104/226
- **Files:** 3

**Worst Files:**
- `scalper/trap.py`: 35.6%
- `scalper/sprt.py`: 43.1%
- `scalper/calibrator.py`: 66.7%

### regime
- **Line Coverage:** 53.6%
- **Lines:** 120/224
- **Files:** 4

**Worst Files:**
- `regime/glr.py`: 27.3%
- `regime/page_hinkley.py`: 37.5%

### features
- **Line Coverage:** 56.3%
- **Lines:** 479/851
- **Files:** 6

**Worst Files:**
- `features/scaling.py`: 0.0%
- `features/microstructure.py`: 27.3%

### xai
- **Line Coverage:** 58.8%
- **Lines:** 150/255
- **Files:** 4

**Worst Files:**
- `xai/logger.py`: 26.6%
- `xai/alerts.py`: 66.7%

### root
- **Line Coverage:** 60.1%
- **Lines:** 746/1241
- **Files:** 14

**Worst Files:**
- `env.py`: 0.0%
- `lifecycle_correlation.py`: 0.0%
- `ack_tracker.py`: 28.6%

### risk
- **Line Coverage:** 63.4%
- **Lines:** 59/93
- **Files:** 1

**Worst Files:**
- `risk/guards.py`: 63.4%

### aurora
- **Line Coverage:** 64.3%
- **Lines:** 240/373
- **Files:** 2

**Worst Files:**
- `aurora/pipeline.py`: 64.3%
- `aurora/pretrade.py`: 64.5%

### logging
- **Line Coverage:** 65.2%
- **Lines:** 75/115
- **Files:** 2

**Worst Files:**
- `logging/anti_flood.py`: 64.6%

### execution
- **Line Coverage:** 66.1%
- **Lines:** 1512/2286
- **Files:** 19

**Worst Files:**
- `execution/exchange/config.py`: 0.0%
- `execution/exchange/unified.py`: 0.0%
- `execution/exchange/binance.py`: 22.4%

## Recommendations

### Immediate Actions
1. **Increase line coverage to 80%+**
   - Focus on modules with <70% coverage
   - Add unit tests for uncovered functions
   - Test error handling paths

2. **Improve branch coverage to 70%+**
   - Test conditional logic thoroughly
   - Cover both true/false branches
   - Test edge cases and boundary conditions

### Best Practices
1. **Maintain coverage standards** - No PR should reduce coverage
2. **Test-driven development** - Write tests before implementing features
3. **Regular coverage audits** - Review coverage weekly
4. **Focus on critical paths** - Ensure high coverage for business logic

## Mutation Testing Status

*Pending - Run mutation tests on critical modules*

## Files Generated

- `artifacts/coverage.xml` - Detailed XML coverage report
- `artifacts/coverage.json` - JSON format coverage data
- `TEST_COVERAGE_SNAPSHOT.md` - This summary report

---
*Generated by Aurora Coverage Analyzer*
