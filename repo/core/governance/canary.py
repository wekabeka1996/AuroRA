from __future__ import annotations

"""
Governance — Canary safety gates
===============================

Wraps a set of safety signals (no-trades, deny spikes, calibration drift, CVaR
breaches) into a single governance interface that can be queried from live or
shadow runs. Designed to be deterministic and dependency-free.

Usage
-----
    from core.xai.alerts import AlertResult

    canary = Canary()
    # feed decisions
    ar = canary.on_decision(ts_ns=..., action='deny', p=0.44, y=0)
    # feed returns for CVaR
    br = canary.on_return(ts_ns=..., ret=-0.002)
    # collect triggers
    trig = canary.poll()
    for t in trig: print(t.triggered, t.message)
"""

from dataclasses import dataclass

from core.xai.alerts import (
    AlertResult,
    CalibrationDriftAlert,
    CvarBreachAlert,
    DenySpikeAlert,
    NoTradesAlert,
)


@dataclass
class CanaryConfig:
    # parameters are mostly delegated to individual alerts; placeholder kept for future
    pass


class Canary:
    def __init__(self) -> None:
        self._no = NoTradesAlert()
        self._den = DenySpikeAlert()
        self._cal = CalibrationDriftAlert()
        self._cvar = CvarBreachAlert()
        self._queue: list[AlertResult] = []

    # ---------- event ingestion ----------

    def on_decision(self, *, ts_ns: int, action: str, p: float, y: int | None = None) -> None:
        # no-trades and deny spike
        r1 = self._no.update(ts_ns, action)
        if r1 is not None:
            self._queue.append(r1)
        r2 = self._den.update(ts_ns, action)
        if r2 is not None:
            self._queue.append(r2)
        # calibration drift requires labels; if unknown, assume y=1 for 'enter', else 0
        if y is None:
            y = 1 if action == "enter" else 0
        r3 = self._cal.update(ts_ns, p, int(y))
        if r3 is not None:
            self._queue.append(r3)

    def on_return(self, *, ts_ns: int, ret: float) -> None:
        r = self._cvar.update(ts_ns, float(ret))
        if r is not None:
            self._queue.append(r)

    # ---------- polling ----------

    def poll(self) -> list[AlertResult]:
        out = list(self._queue)
        self._queue.clear()
        return out


__all__ = ["Canary", "CanaryConfig"]
