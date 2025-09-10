from __future__ import annotations

"""
Alpha Ledger — Transaction-level α-cost accounting for statistical tests
=======================================================================

Provides transaction-level accounting for α (Type-I error) allocation across
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

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
import json
import threading
import time
from uuid import uuid4


@dataclass
class AlphaTxn:
    """Single α-spending transaction record."""
    ts_ns: int                  # transaction timestamp
    test_id: str               # test identifier (e.g., "sprt:maker_edge_btcusdt")
    alpha0: float              # initial α allocation
    spent: float               # cumulative α spent (≤ alpha0)
    outcome: str               # "open"|"accept"|"reject"|"abandon"
    token: str | None = None  # unique transaction token
    history: list[dict] = field(default_factory=list)  # per-spend audit trail
    closed_ts_ns: int | None = None                 # set on close

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

    def __init__(self, clock_ns: Callable[[], int] = time.monotonic_ns, eps: float = 1e-12):
        self._transactions: dict[str, AlphaTxn] = {}  # token -> transaction
        self._test_index: dict[str, str] = {}         # test_id -> active_token
        self._lock = threading.RLock()
        self._clock_ns = clock_ns
        self._eps = eps

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
            txn = AlphaTxn(
                ts_ns=self._clock_ns(),
                test_id=test_id,
                alpha0=alpha0,
                spent=0.0,
                outcome="open",
                token=token
            )

            self._transactions[token] = txn
            self._test_index[test_id] = token

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
        if amount <= 0:
            raise ValueError(f"spend amount must be positive, got {amount}")

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
            # Аудит-запис
            txn.history.append({
                "ts_ns": self._clock_ns(),
                "amount": amount,
                "spent": txn.spent,
            })

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
            if test_id not in by_test_id or txn.ts_ns > by_test_id[test_id]["ts_ns"]:
                by_test_id[test_id] = {
                    "alpha0": txn.alpha0,
                    "spent": txn.spent,
                    "outcome": txn.outcome,
                    "ts_ns": txn.ts_ns,
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

    def get_transaction(self, token: str) -> AlphaTxn | None:
        """Get transaction by token (returns copy to prevent mutation)."""
        with self._lock:
            if token not in self._transactions:
                return None
            txn = self._transactions[token]
            # Return copy to prevent external mutation
            return AlphaTxn(
                ts_ns=txn.ts_ns,
                test_id=txn.test_id,
                alpha0=txn.alpha0,
                spent=txn.spent,
                outcome=txn.outcome,
                token=txn.token,
                history=list(txn.history),
                closed_ts_ns=txn.closed_ts_ns,
            )

    def list_transactions(self, test_id: str | None = None) -> list[AlphaTxn]:
        """List all transactions, optionally filtered by test_id."""
        with self._lock:
            transactions = list(self._transactions.values())

        if test_id is not None:
            transactions = [txn for txn in transactions if txn.test_id == test_id]

        # Return copies sorted by timestamp
        return sorted(
            [AlphaTxn(
                ts_ns=txn.ts_ns,
                test_id=txn.test_id,
                alpha0=txn.alpha0,
                spent=txn.spent,
                outcome=txn.outcome,
                token=txn.token,
                history=list(txn.history),
                closed_ts_ns=txn.closed_ts_ns,
            ) for txn in transactions],
            key=lambda x: x.ts_ns
        )

    def to_json(self) -> str:
        """Serialize ledger state to JSON."""
        with self._lock:
            state = {
                "transactions": {
                    token: asdict(txn) for token, txn in self._transactions.items()
                },
                "test_index": self._test_index.copy()
            }
        return json.dumps(state, indent=2)

    def from_json(self, json_str: str) -> None:
        """Restore ledger state from JSON."""
        state = json.loads(json_str)

        with self._lock:
            # Clear existing state
            self._transactions.clear()
            self._test_index.clear()

            # Restore transactions
            for token, txn_dict in state["transactions"].items():
                txn = AlphaTxn(**txn_dict)
                self._transactions[token] = txn

            # Restore test index
            self._test_index.update(state["test_index"])

    def clear(self) -> None:
        """Clear all transactions (for testing/debugging)."""
        with self._lock:
            self._transactions.clear()
            self._test_index.clear()

    # ---- convenience helpers (використаємо в тестах/раннері) ----
    def is_open(self, token: str) -> bool:
        with self._lock:
            txn = self._transactions.get(token)
            return bool(txn and txn.outcome == "open")

    def remaining(self, token: str) -> float:
        with self._lock:
            txn = self._transactions[token]
            return max(0.0, txn.alpha0 - txn.spent)

    def active_token_for(self, test_id: str) -> str | None:
        with self._lock:
            return self._test_index.get(test_id)


__all__ = ["AlphaTxn", "AlphaLedger"]
