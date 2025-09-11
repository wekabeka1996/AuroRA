from __future__ import annotations

from typing import Optional

from prometheus_client.registry import CollectorRegistry

from api.sli_metrics import IdemMetrics
from core.aurora_event_logger import AuroraEventLogger

from . import idem_guard as _idem_guard


def wire_idem_observability(
    registry: CollectorRegistry | None,
    event_logger: Optional[AuroraEventLogger],
) -> None:
    """Attach AuroraEventLogger and Prometheus metrics to the idempotency guard.

    Safe to call multiple times; failures are swallowed.
    """
    try:
        _idem_guard.set_event_logger(event_logger)
    except Exception:
        pass
    try:
        if registry is not None:
            metrics = IdemMetrics(registry)
            _idem_guard.set_idem_metrics(metrics)
        else:
            _idem_guard.set_idem_metrics(None)
    except Exception:
        _idem_guard.set_idem_metrics(None)


__all__ = ["wire_idem_observability"]
