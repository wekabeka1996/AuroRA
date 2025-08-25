# Aurora helper Makefile (optional; Windows users can still run via Python directly)

PY ?= python

.PHONY: help api-start api-stop health canary smoke testnet wallet-check metrics disarm cooloff tests-targeted

help:
	@echo "Targets:"
	@echo "  api-start                Start FastAPI (uvicorn)"
	@echo "  api-stop                 Stop API process"
	@echo "  health                   Check /health"
	@echo "  canary                   Run canary harness (MIN or MINUTES, default 60)"
	@echo "  smoke                    Run Binance smoke (PUBLIC=1 to only public)"
	@echo "  testnet                  Run short testnet cycle (MIN=5, PRE=1)"
	@echo "  wallet-check             Audit wallet/withdrawals and write artifacts/wallet_check.json"
	@echo "  metrics                  Aggregate logs/events.jsonl -> reports + artifacts (WINDOW=3600)"
	@echo "  disarm                   POST /aurora/disarm (requires AURORA_OPS_TOKEN)"
	@echo "  cooloff                  POST /ops/cooloff (SEC=120, requires AURORA_OPS_TOKEN)"
	@echo "  tests-targeted           Run targeted pytest suite"
	@echo "  one-click-testnet        Wallet→API→Canary(15m)→Metrics→Stop"
	@echo "  one-click-live           Wallet→API→Canary(15m live)→Metrics→Stop"

api-start:
	$(PY) tools/auroractl.py start-api

api-stop:
	$(PY) tools/auroractl.py stop-api

health:
	$(PY) tools/auroractl.py health

# Allow both MIN and MINUTES (MINUTES takes precedence if provided)
MIN ?= 60
ifdef MINUTES
MIN := $(MINUTES)
endif
canary:
	$(PY) tools/auroractl.py canary --minutes $(MIN)

PUBLIC ?= 0
smoke:
ifeq ($(PUBLIC),1)
	$(PY) tools/auroractl.py smoke --public-only
else
	$(PY) tools/auroractl.py smoke
endif

# Testnet: MIN minutes; PRE=1 to include preflight
TESTNET_MIN ?= 5
PRE ?= 1
testnet:
ifeq ($(PRE),1)
	$(PY) tools/auroractl.py testnet --minutes $(TESTNET_MIN) --preflight
else
	$(PY) tools/auroractl.py testnet --minutes $(TESTNET_MIN)
endif

wallet-check:
	$(PY) tools/auroractl.py wallet-check

WINDOW ?= 3600
metrics:
	$(PY) tools/auroractl.py metrics --window-sec $(WINDOW)

disarm:
	$(PY) tools/auroractl.py disarm

SEC ?= 120
cooloff:
	$(PY) tools/auroractl.py cooloff --sec $(SEC)

tests-targeted:
	pytest -q tests/unit/test_calibrator.py tests/integration/test_expected_return_gate.py tests/integration/test_latency_slippage.py

one-click-testnet:
	$(PY) tools/auroractl.py one-click --mode testnet --minutes 15 --preflight

one-click-live:
	$(PY) tools/auroractl.py one-click --mode live --minutes 15 --preflight
