from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping, Optional

import structlog


_logger = structlog.get_logger(__name__)


@dataclass
class EventEmitter:
    """Append-only JSONL event emitter.

    Writes events into AURORA_SESSION_DIR/aurora_events.jsonl if env is set,
    otherwise into logs/aurora_events.jsonl. Single-writer recommended.
    """

    path: Path = Path(os.getenv("AURORA_SESSION_DIR", "logs")) / "aurora_events.jsonl"

    def emit(
        self,
        type: str,
        payload: Mapping[str, Any],
        severity: Optional[str] = None,
        code: Optional[str] = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "type": type,
            "severity": severity,
            "code": code,
            "payload": payload,
        }
        line = json.dumps(event, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        _logger.info("event.emitted", type=type, code=code, severity=severity)
