from __future__ import annotations

"""
XAI — Decision Logger
=====================

Thread-safe NDJSON decision logger with deterministic hashing support.
Integrates with SSOT-config to include `config_hash` and `config_schema_version`.

Features
--------
- Append-only JSONL (one record per line), rotation by date (YYYYMMDD) optional
- Canonical JSON for stable diffing and hashing
- Optional signature field (sha256 of canonical JSON) for tamper-evidence
- Minimal dependencies; uses threading.Lock for concurrency

Usage
-----
    from core.xai.logger import DecisionLogger
    from core.xai.schema import validate_decision

    logger = DecisionLogger(base_path="logs/decisions", rotate_daily=True)
    rec = {...}; validate_decision(rec)
    logger.write(rec)

"""

import os
import threading
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, TextIO
import json

from core.config.loader import get_config, ConfigError
from core.xai.schema import validate_decision, canonical_json


class DecisionLogger:
    def __init__(
        self,
        base_path: str | os.PathLike,
        *,
        rotate_daily: bool = True,
        include_signature: bool = True,
    ) -> None:
        self._base = Path(base_path)
        self._rotate = bool(rotate_daily)
        self._sign = bool(include_signature)
        self._lock = threading.Lock()
        self._fh: Optional[TextIO] = None
        self._current_tag: Optional[str] = None
        self._base.mkdir(parents=True, exist_ok=True)

    # ------------- internals -------------

    def _file_tag(self) -> str:
        if not self._rotate:
            return "decisions"
        now = datetime.now(timezone.utc)
        return now.strftime("decisions_%Y%m%d")

    def _ensure_open(self) -> None:
        tag = self._file_tag()
        if self._fh is not None and self._current_tag == tag:
            return
        # rotate/first open
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
        path = self._base / f"{tag}.jsonl"
        self._fh = open(path, "a", encoding="utf-8")
        self._current_tag = tag

    # ------------- public -------------

    def write(self, record: Mapping[str, Any]) -> None:
        """Validate and append a decision record as canonical JSONL (with optional signature)."""
        # enrich with config metadata if missing
        rec: Dict[str, Any] = dict(record)
        try:
            cfg = get_config()
            rec.setdefault("config_hash", cfg.config_hash)
            rec.setdefault("config_schema_version", cfg.schema_version)
        except (ConfigError, Exception):
            rec.setdefault("config_hash", "")
            rec.setdefault("config_schema_version", None)

        validate_decision(rec)

        # signature (tamper-evidence)
        line = canonical_json(rec)
        if self._sign:
            sig = sha256(line.encode("utf-8")).hexdigest()
            # embed signature as a parallel line for simplicity
            out = json.dumps({"sig": sig, "rec": json.loads(line)}, separators=(",", ":"))
        else:
            out = line

        with self._lock:
            self._ensure_open()
            assert self._fh is not None
            self._fh.write(out + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                finally:
                    self._fh = None
                    self._current_tag = None
