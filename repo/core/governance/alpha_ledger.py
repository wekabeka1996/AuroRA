from __future__ import annotations

"""
Governance — Alpha Ledger (α-budget accounting)
==============================================

Purpose
-------
Maintain an explicit budget of statistical α (type-I error) for online testing
and governance. This is a **deterministic**, dependency-free ledger that tracks
allocations and outcomes of hypothesis tests and returns budget utilization.

Model
-----
Two common accounting policies:
- **Spend-on-reject (default)**: α is only consumed when H0 is rejected.
- **Spend-on-test**: α is consumed upon opening a test regardless of outcome.

This module supports both via `spend_on_reject`.

API sketch
----------
    L = AlphaLedger(alpha_budget=0.10, spend_on_reject=True)
    tid = L.open(test_name="SPR T(GLR)", alpha=0.005, note="daily gate")
    # ... run test ...
    L.commit(tid, decision="reject", p_value=0.003)
    print(L.remaining())

Persistence
-----------
In production you may persist `history()` to NDJSON using XAI logger; here we
keep an in-memory list with a stable, canonical dict representation.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import time
import itertools


@dataclass
class LedgerEntry:
    ticket_id: str
    ts_ns: int
    test_name: str
    alpha: float
    decision: str  # 'reject' | 'accept' | 'abort'
    p_value: Optional[float]
    note: Optional[str]

    def as_dict(self) -> Dict[str, object]:
        d = asdict(self)
        # robust rounding for storage (optional)
        d["alpha"] = float(self.alpha)
        if self.p_value is not None:
            d["p_value"] = float(self.p_value)
        return d


class AlphaLedger:
    def __init__(self, *, alpha_budget: float = 0.10, spend_on_reject: bool = True) -> None:
        if alpha_budget <= 0:
            raise ValueError("alpha_budget must be > 0")
        self._budget = float(alpha_budget)
        self._policy_reject = bool(spend_on_reject)
        self._seq = itertools.count(1)
        self._open: Dict[str, float] = {}  # ticket_id -> alpha allocated
        self._hist: List[LedgerEntry] = []
        self._spent = 0.0
        self._reserved = 0.0

    # -------- tickets --------

    def open(self, *, test_name: str, alpha: float, note: Optional[str] = None) -> str:
        if alpha <= 0.0 or alpha > 1.0:
            raise ValueError("alpha must be in (0,1]")
        if self._policy_reject:
            # only reserve for visibility, not deducting from remaining
            self._reserved += alpha
        else:
            # spend-on-test policy
            if self.remaining() < alpha:
                raise RuntimeError("insufficient alpha budget")
            self._spent += alpha
        tid = f"T{next(self._seq)}"
        self._open[tid] = float(alpha)
        # pre-log open with decision=None (optional); we keep only commits in history for brevity
        return tid

    def commit(self, ticket_id: str, *, decision: str, p_value: Optional[float] = None, test_name: Optional[str] = None, note: Optional[str] = None) -> LedgerEntry:
        if ticket_id not in self._open:
            raise KeyError("unknown ticket id")
        alpha = self._open.pop(ticket_id)
        # policy: spend on reject
        if self._policy_reject and decision == "reject":
            if self.remaining() < alpha:
                raise RuntimeError("insufficient alpha budget to spend-on-reject")
            self._spent += alpha
        # clear reservation
        if self._policy_reject:
            self._reserved = max(0.0, self._reserved - alpha)
        entry = LedgerEntry(
            ticket_id=ticket_id,
            ts_ns=time.perf_counter_ns(),
            test_name=test_name or "",
            alpha=float(alpha),
            decision=str(decision),
            p_value=None if p_value is None else float(p_value),
            note=note,
        )
        self._hist.append(entry)
        return entry

    # -------- views --------

    def spent(self) -> float:
        return self._spent

    def reserved(self) -> float:
        return self._reserved

    def remaining(self) -> float:
        return max(0.0, self._budget - self._spent)

    def budget(self) -> float:
        return self._budget

    def history(self) -> List[Dict[str, object]]:
        return [h.as_dict() for h in self._hist]


__all__ = ["AlphaLedger", "LedgerEntry"]