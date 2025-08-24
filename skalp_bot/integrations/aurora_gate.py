
import time
import requests

DEFAULT_TIMEOUT_S = 0.010

class AuroraGate:
    """Thin HTTP client for Aurora pre-trade gate (fail-open in shadow/paper)."""
    def __init__(self, base_url: str = "http://127.0.0.1:8037", mode: str = "shadow", timeout_s: float = DEFAULT_TIMEOUT_S):
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self.timeout_s = timeout_s

    def check(self, account: dict, order: dict, market: dict, risk_tags=("scalping",), fees_bps: float = 1.0) -> dict:
        payload = {
            "ts": int(time.time()*1000),
            "req_id": f"rq-{int(time.time()*1e6)}",
            "account": {**account, "mode": self.mode},
            "order": order,
            "market": market,
            "risk_tags": list(risk_tags),
            "fees_bps": float(fees_bps),
        }
        try:
            r = requests.post(self.base_url + "/pretrade/check", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            # In shadow/paper we prefer fail-open; in prod we fail-closed.
            fail_open = (self.mode in ("shadow", "paper"))
            status = None
            try:
                status = getattr(e.response, 'status_code', None)  # type: ignore[attr-defined]
            except Exception:
                status = None
            return {
                "allow": fail_open,
                "max_qty": order.get("qty", 0),
                "risk_scale": 1.0,
                "cooldown_ms": 0,
                "reason": f"aurora_http_{status or 'NA'}:{type(e).__name__}",
                "hard_gate": (self.mode == "prod"),
                "quotas": {"trades_pm_left": 0 if not fail_open else 999, "symbol_exposure_left_usdt": 0.0 if not fail_open else 1e12},
                "observability": {}
            }

    def posttrade(self, **payload) -> bool:
        try:
            r = requests.post(self.base_url + "/posttrade/log", json=payload, timeout=self.timeout_s)
            r.raise_for_status()
            return True
        except Exception:
            return False
