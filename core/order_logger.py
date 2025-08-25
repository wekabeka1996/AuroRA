from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


def _make_rotating_logger(name: str, path: Path, max_mb: int = 50, backups: int = 5) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in lg.handlers):
        handler = RotatingFileHandler(str(path), maxBytes=max_mb * 1024 * 1024, backupCount=backups, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        lg.addHandler(handler)
        lg.propagate = False
    return lg


@dataclass
class OrderLoggers:
    success_path: Path = Path("logs/orders_success.jsonl")
    failed_path: Path = Path("logs/orders_failed.jsonl")
    denied_path: Path = Path("logs/orders_denied.jsonl")
    max_mb: int = 50
    backups: int = 5

    def __post_init__(self):
        self._lg_success = _make_rotating_logger("orders.success", self.success_path, self.max_mb, self.backups)
        self._lg_failed = _make_rotating_logger("orders.failed", self.failed_path, self.max_mb, self.backups)
        self._lg_denied = _make_rotating_logger("orders.denied", self.denied_path, self.max_mb, self.backups)
        # Ensure files exist immediately (Windows locks/buffering can delay file creation by handlers)
        try:
            for p in (self.success_path, self.failed_path, self.denied_path):
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    # create an empty file
                    p.open('a', encoding='utf-8').close()
        except Exception:
            # best-effort; do not fail on logger init
            pass

    def _write(self, logger: logging.Logger, rec: Dict[str, Any]) -> None:
        try:
            line = json.dumps(rec, ensure_ascii=False)
            logger.info(line)
            # RotatingFileHandler may buffer; ensure file exists by appending as fallback
            try:
                p = None
                for h in logger.handlers:
                    if isinstance(h, RotatingFileHandler):
                        p = Path(h.baseFilename)
                        break
                if p and not p.exists():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.open('a', encoding='utf-8').write(line + "\n")
            except Exception:
                pass
        except Exception:
            # best-effort logging only
            pass

    def log_success(self, **kwargs: Any) -> None:
        # expected fields: ts, symbol, side, qty, price, order_id, status, fill_qty, avg_price, fees, txid?
        self._write(self._lg_success, kwargs)

    def log_failed(self, **kwargs: Any) -> None:
        # expected fields + error_code, error_msg, retry?
        self._write(self._lg_failed, kwargs)

    def log_denied(self, **kwargs: Any) -> None:
        # expected fields + deny_reason
        self._write(self._lg_denied, kwargs)

