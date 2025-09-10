from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from core.aurora_event_logger import AuroraEventLogger


@dataclass
class EventEmitter:
    """Compatibility wrapper over AuroraEventLogger.

    Стара сигнатура emit(type, payload, severity, code) зберігається, але під капотом
    подія надсилається у `AuroraEventLogger.emit(event_code, details, ...)` з канонічним кодом.
    Шлях лог-файлу спрямовується у AURORA_SESSION_DIR/aurora_events.jsonl або logs/.
    """

    path: Path = Path(os.getenv("AURORA_SESSION_DIR", "logs")) / "aurora_events.jsonl"

    def __post_init__(self):
        try:
            self._logger = AuroraEventLogger(path=self.path)
        except Exception:
            # Fallback: створити у дефолтній директорії
            self._logger = AuroraEventLogger()

    def emit(
        self,
        type: str,
        payload: Mapping[str, Any],
        severity: str | None = None,
        code: str | None = None,
    ) -> None:
        # Вибрати пріоритетно 'code' як канонічний event_code; інакше використати 'type'
        event_code = (code or type or "").strip()
        if not event_code:
            return
        try:
            self._logger.emit(event_code, dict(payload))
        except Exception:
            # Не зривати бізнес-потік через проблеми логування
            pass
