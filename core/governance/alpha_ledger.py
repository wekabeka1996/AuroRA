from __future__ import annotations

"""
Alpha Ledger — Transaction-level α-cost accounting for statistical tests
=======================================================================

Provides transaction-level accounting for α (Type-I error) allo            # return a shallow copy with copied history to avoid external mutation
            return AlphaTxn(
                ts_ns_mono=txn.ts_ns_mono,
                ts_ns_wall=txn.ts_ns_wall,
                test_id=txn.test_id,
                alpha0=txn.alpha0,
                spent=txn.spent,
                outcome=txn.outcome,
                token=txn.token,
                history=list(txn.history),
                closed_ts_ns=txn.closed_ts_ns,
            )ss
multiple statistical tests running in parallel. Each test gets an α budget,
spends it monotonically during sequential hypothesis testing, and reports
final outcomes.

Key features:
- Per-test α allocation with strict spending limits (spent ≤ alpha0)
- Monotonic spending constraint enforcement
- JSON-serializable state for persistence
- Thread-safe operations for concurrent test execution
- Audit trail with timestamps for regulatory compliance

Example usage:
    ledger = AlphaLedger()
    token = ledger.open("sprt:maker_edge_btcusdt", alpha0=0.05)
    ledger.spend(token, 0.001)  # spend 0.1% of α budget  
    ledger.spend(token, 0.002)  # total spent: 0.003
    ledger.close(token, "accept")  # finalize test
"""

import json
import math
import os
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Callable
from uuid import uuid4


@dataclass
class AlphaTxn:
    """Single α-spending transaction record."""
    ts_ns_mono: int             # transaction timestamp (monotonic)
    ts_ns_wall: int             # transaction timestamp (wall clock for audit)
    test_id: str               # test identifier (e.g., "sprt:maker_edge_btcusdt")
    alpha0: float              # initial α allocation
    spent: float               # cumulative α spent (≤ alpha0)
    outcome: str               # "open"|"accept"|"reject"|"abandon"
    token: Optional[str] = None  # unique transaction token
    history: List[dict] = field(default_factory=list)  # per-spend audit trail
    closed_ts_ns: Optional[int] = None                 # set on close (monotonic)

    def __post_init__(self):
        """Validate α spending constraints."""
        if self.spent < 0:
            raise ValueError(f"spent cannot be negative: {self.spent}")
        if self.spent > self.alpha0:
            raise ValueError(f"spent ({self.spent}) exceeds alpha0 ({self.alpha0})")
        if self.outcome not in {"open", "accept", "reject", "abandon"}:
            raise ValueError(f"invalid outcome: {self.outcome}")


class AlphaLedger:
    """Thread-safe α-cost accounting ledger for statistical tests."""

    def __init__(self, clock_ns: Callable[[], int] = time.monotonic_ns, eps: float = 1e-12, max_history_len: int = 2048):
        self._transactions: Dict[str, AlphaTxn] = {}  # token -> transaction
        self._test_index: Dict[str, str] = {}         # test_id -> active_token
        self._lock = threading.RLock()
        self._clock_ns = clock_ns
        self._eps = eps
        self._max_history_len = max_history_len
        
        # Persistence throttling state
        self._last_snapshot_ns = 0
        self._events_since_snapshot = 0

    def open(self, test_id: str, alpha0: float) -> str:
        """
        Open a new α-allocation for a statistical test.
        
        Args:
            test_id: Unique test identifier (e.g., "sprt:maker_edge_btcusdt")
            alpha0: Initial α budget allocation (0 < alpha0 ≤ 1.0)
            
        Returns:
            token: Unique transaction token for spending operations
            
        Raises:
            ValueError: If alpha0 is invalid or test_id already has active allocation
        """
        if alpha0 <= 0 or alpha0 > 1.0:
            raise ValueError(f"alpha0 must be in (0, 1.0], got {alpha0}")
        
        with self._lock:
            # Check for existing active allocation
            if test_id in self._test_index:
                existing_token = self._test_index[test_id]
                existing_txn = self._transactions[existing_token]
                if existing_txn.outcome == "open":
                    raise ValueError(f"test_id '{test_id}' already has active allocation")
            
            # Create new transaction
            token = str(uuid4())
            now_mono, now_wall = self._clock_ns(), time.time_ns()
            txn = AlphaTxn(
                ts_ns_mono=now_mono,
                ts_ns_wall=now_wall,
                test_id=test_id,
                alpha0=alpha0,
                spent=0.0,
                outcome="open",
                token=token
            )
            
            self._transactions[token] = txn
            self._test_index[test_id] = token
            
            # Increment event counter for throttling
            self._increment_event_counter()
            
            return token

    def spend(self, token: str, amount: float) -> None:
        """
        Spend α from an active allocation (monotonic increase only).
        
        Args:
            token: Transaction token from open()
            amount: Additional α to spend (amount > 0)
            
        Raises:
            ValueError: If token invalid, allocation closed, or spending exceeds budget
        """
        if not (amount > 0.0) or not math.isfinite(amount):
            raise ValueError("amount must be a finite positive number")
        
        with self._lock:
            if token not in self._transactions:
                raise ValueError(f"invalid token: {token}")
            
            txn = self._transactions[token]
            
            if txn.outcome != "open":
                raise ValueError(f"cannot spend on closed allocation (outcome: {txn.outcome})")
            
            new_spent = txn.spent + amount
            # ε-толерантність проти двійкової похибки
            if new_spent > txn.alpha0 + self._eps:
                raise ValueError(
                    f"spending {amount} would exceed budget: {new_spent} > {txn.alpha0}"
                )
            if new_spent > txn.alpha0:
                new_spent = txn.alpha0
            
            # Update spent amount (monotonic increase)
            txn.spent = new_spent
            # Аудит-запис з bounded history
            txn.history.append({
                "ts_ns": self._clock_ns(),
                "amount": amount,
                "spent": txn.spent,
            })
            # Обмеження довжини історії
            if len(txn.history) > self._max_history_len:
                txn.history = txn.history[-self._max_history_len:]
            
            # Increment event counter for throttling
            self._increment_event_counter()

    def close(self, token: str, outcome: str) -> None:
        """
        Close an α-allocation with final outcome.
        
        Args:
            token: Transaction token from open()
            outcome: Final test outcome ("accept"|"reject"|"continue"|"abandon")
            
        Raises:
            ValueError: If token invalid or already closed
        """
        valid_outcomes = {"accept", "reject", "abandon"}
        if outcome not in valid_outcomes:
            raise ValueError(f"outcome must be one of {valid_outcomes}, got '{outcome}'")
        
        with self._lock:
            if token not in self._transactions:
                raise ValueError(f"invalid token: {token}")
            
            txn = self._transactions[token]
            
            if txn.outcome != "open":
                raise ValueError(f"allocation already closed with outcome: {txn.outcome}")
            
            # Finalize transaction
            txn.outcome = outcome
            txn.closed_ts_ns = self._clock_ns()
            
            # Remove from active index if this was the active allocation
            if (txn.test_id in self._test_index and 
                self._test_index[txn.test_id] == token):
                del self._test_index[txn.test_id]
            
            # Increment event counter for throttling
            self._increment_event_counter()

    def summary(self) -> dict:
        """
        Get ledger summary statistics.
        
        Returns:
            Summary dict with total allocations, spending, and per-test breakdowns
        """
        with self._lock:
            transactions = list(self._transactions.values())
        
        if not transactions:
            return {
                "total_alloc": 0.0,
                "total_spent": 0.0,
                "active_tests": 0,
                "closed_tests": 0,
                "by_test_id": {},
                "by_outcome": {}
            }
        
        # Aggregate statistics
        total_alloc = sum(txn.alpha0 for txn in transactions)
        total_spent = sum(txn.spent for txn in transactions)
        active_tests = sum(1 for txn in transactions if txn.outcome == "open")
        closed_tests = len(transactions) - active_tests
        
        # Group by test_id (latest transaction per test)
        by_test_id = {}
        for txn in transactions:
            test_id = txn.test_id
            if test_id not in by_test_id or txn.ts_ns_mono > by_test_id[test_id]["ts_ns"]:
                by_test_id[test_id] = {
                    "alpha0": txn.alpha0,
                    "spent": txn.spent,
                    "outcome": txn.outcome,
                    "ts_ns": txn.ts_ns_mono,
                    "ts_ns_wall": txn.ts_ns_wall,
                    "utilization": txn.spent / txn.alpha0 if txn.alpha0 > 0 else 0.0,
                    "remaining": max(0.0, txn.alpha0 - txn.spent),
                }
        
        # Group by outcome
        by_outcome = {}
        for txn in transactions:
            outcome = txn.outcome
            if outcome not in by_outcome:
                by_outcome[outcome] = {"count": 0, "total_spent": 0.0, "total_alloc": 0.0}
            by_outcome[outcome]["count"] += 1
            by_outcome[outcome]["total_spent"] += txn.spent
            by_outcome[outcome]["total_alloc"] += txn.alpha0
        
        return {
            "total_alloc": total_alloc,
            "total_spent": total_spent,
            "active_tests": active_tests,
            "closed_tests": closed_tests,
            "by_test_id": by_test_id,
            "by_outcome": by_outcome
        }

    def get_transaction(self, token: str) -> Optional[AlphaTxn]:
        """Get transaction by token (returns copy to prevent mutation)."""
        with self._lock:
            if token not in self._transactions:
                return None
            txn = self._transactions[token]
            # Return copy to prevent external mutation
            return AlphaTxn(
                ts_ns_mono=txn.ts_ns_mono,
                ts_ns_wall=txn.ts_ns_wall,
                test_id=txn.test_id,
                alpha0=txn.alpha0,
                spent=txn.spent,
                outcome=txn.outcome,
                token=txn.token,
                history=list(txn.history),
                closed_ts_ns=txn.closed_ts_ns,
            )

    def list_transactions(self, test_id: Optional[str] = None) -> List[AlphaTxn]:
        """List all transactions, optionally filtered by test_id."""
        with self._lock:
            transactions = list(self._transactions.values())
        
        if test_id is not None:
            transactions = [txn for txn in transactions if txn.test_id == test_id]
        
        # Return copies sorted by timestamp
        return sorted(
            [AlphaTxn(
                ts_ns_mono=txn.ts_ns_mono,
                ts_ns_wall=txn.ts_ns_wall,
                test_id=txn.test_id,
                alpha0=txn.alpha0,
                spent=txn.spent,
                outcome=txn.outcome,
                token=txn.token,
                history=list(txn.history),
                closed_ts_ns=txn.closed_ts_ns,
            ) for txn in transactions],
            key=lambda x: x.ts_ns_mono
        )

    def to_json(self) -> str:
        """Serialize ledger state to JSON."""
        with self._lock:
            state = {
                "version": 1,  # Versioning for future migrations
                "transactions": {
                    token: asdict(txn) for token, txn in self._transactions.items()
                },
                "test_index": self._test_index.copy()
            }
        return json.dumps(state, indent=2)

    def from_json(self, json_str: str) -> None:
        """Restore ledger state from JSON."""
        state = json.loads(json_str)
        
        # Handle version compatibility
        version = state.get("version", 0)  # Default to v0 for legacy files
        
        with self._lock:
            # Clear existing state
            self._transactions.clear()
            self._test_index.clear()
            
            # Restore transactions with migration
            for token, d in state["transactions"].items():
                # Migration for legacy format
                if "ts_ns_mono" not in d and "ts_ns" in d:
                    d["ts_ns_mono"] = d["ts_ns"]  # старе поле як моно
                d.setdefault("ts_ns_mono", time.monotonic_ns())
                d.setdefault("ts_ns_wall", time.time_ns())
                d.setdefault("history", [])
                d.setdefault("closed_ts_ns", None)
                
                # Legacy 'continue' outcome → трактуємо як 'open'
                if d.get("outcome") == "continue":
                    d["outcome"] = "open"
                
                # Remove old ts_ns field if exists
                d.pop("ts_ns", None)
                
                txn = AlphaTxn(**d)
                self._transactions[token] = txn
            
            # Restore test index
            self._test_index.update(state.get("test_index", {}))

    def snapshot(self, path: Path, *, now_ns: Optional[int] = None) -> bool:
        """
        Atomically save ledger state to file.
        
        Args:
            path: Target file path
            now_ns: Current timestamp (for testing)
            
        Returns:
            True on success, False on error (logged but not raised)
        """
        try:
            path = Path(path)
            tmp_path = path.with_suffix('.tmp')
            
            # Serialize state under lock
            json_data = self.to_json()
            
            # Atomic write: write to .tmp then replace
            with tmp_path.open('w', encoding='utf-8') as f:
                f.write(json_data)
                f.flush()
                os.fsync(f.fileno())  # Ensure data hits disk
            
            # Atomic replace (works on Windows with os.replace)
            os.replace(tmp_path, path)
            
            # Update throttling state
            with self._lock:
                self._last_snapshot_ns = now_ns or self._clock_ns()
                self._events_since_snapshot = 0
            
            return True
            
        except Exception as e:
            # Log error but don't raise - fail silently for persistence
            # In production, this should use proper logging
            import sys
            print(f"DEBUG: snapshot failed: {e}", file=sys.stderr)
            
            # Clean up tmp file if it exists
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            
            return False

    def restore(self, path: Path) -> bool:
        """
        Restore ledger state from file.
        
        Args:
            path: File path to restore from
            
        Returns:
            True on success, False if file missing or corrupt
        """
        try:
            path = Path(path)
            
            if not path.exists():
                return False
            
            # Read and parse JSON
            json_data = path.read_text(encoding='utf-8')
            self.from_json(json_data)
            
            return True
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Handle corrupt file - rename it and return False
            try:
                epoch = int(time.time())
                corrupt_path = path.with_name(f"{path.stem}.corrupt-{epoch}.json")
                os.rename(path, corrupt_path)
                import sys
                print(f"DEBUG: corrupt file renamed to {corrupt_path}: {e}", file=sys.stderr)
            except Exception:
                pass
            
            return False
            
        except Exception as e:
            # Other errors - just log and return False
            import sys
            print(f"DEBUG: restore failed: {e}", file=sys.stderr)
            return False

    def maybe_snapshot(self, path: Path, *, max_interval_ms: int = 5000, max_events: int = 50, now_ns: Optional[int] = None) -> bool:
        """
        Conditionally snapshot based on time/event thresholds.
        
        Args:
            path: Target file path
            max_interval_ms: Maximum time between snapshots (ms)
            max_events: Maximum events between snapshots
            now_ns: Current timestamp (for testing)
            
        Returns:
            True if snapshot was taken, False otherwise
        """
        now_ns = now_ns or self._clock_ns()
        
        with self._lock:
            time_elapsed_ns = now_ns - self._last_snapshot_ns
            time_threshold_ns = max_interval_ms * 1_000_000  # ms to ns
            
            should_snapshot = (
                time_elapsed_ns >= time_threshold_ns or
                self._events_since_snapshot >= max_events
            )
            
            if should_snapshot:
                return self.snapshot(path, now_ns=now_ns)
            
            return False

    def _increment_event_counter(self):
        """Internal: increment event counter for throttling."""
        with self._lock:
            self._events_since_snapshot += 1

    def clear(self) -> None:
        """Clear all transactions (for testing/debugging)."""
        with self._lock:
            self._transactions.clear()
            self._test_index.clear()
            # Reset throttling state
            self._last_snapshot_ns = 0
            self._events_since_snapshot = 0

    # ---- convenience helpers (використаємо в тестах/раннері) ----
    def is_open(self, token: str) -> bool:
        with self._lock:
            txn = self._transactions.get(token)
            return bool(txn and txn.outcome == "open")

    def remaining(self, token: str) -> float:
        with self._lock:
            txn = self._transactions[token]
            return max(0.0, txn.alpha0 - txn.spent)

    def active_token_for(self, test_id: str) -> Optional[str]:
        with self._lock:
            return self._test_index.get(test_id)


__all__ = ["AlphaTxn", "AlphaLedger"]