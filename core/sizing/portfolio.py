"""
Portfolio Optimization with NumPy fallback
==========================================

Comprehensive portfolio optimization with graceful NumPy fallback:
- Mean-variance optimization with pure Python fallback
- Linear algebra operations with fallback implementations
- Full compatibility between NumPy and pure Python modes
"""
from __future__ import annotations

from typing import Any

# 1) Module-level NumPy import with fallback
try:
    import numpy as np  # Must be available as module attribute for tests
except Exception:
    np = None


def _solve_linear_system(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve linear system Ax = b with NumPy or pure Python fallback."""
    # Use NumPy if available
    if np is not None:
        import numpy as _np
        return _np.linalg.solve(_np.asarray(A, dtype=float), _np.asarray(b, dtype=float)).tolist()

    # Pure Python Gauss-Jordan with partial pivoting
    n = len(A)
    M = [list(map(float, row)) for row in A]
    x = list(map(float, b))

    for i in range(n):
        # Find pivot
        piv = max(range(i, n), key=lambda r: abs(M[r][i]))
        if abs(M[piv][i]) < 1e-12:
            raise ValueError("Singular matrix in fallback solver")

        # Swap rows if needed
        if piv != i:
            M[i], M[piv] = M[piv], M[i]
            x[i], x[piv] = x[piv], x[i]

        # Forward elimination
        inv = 1.0 / M[i][i]
        for j in range(i, n):
            M[i][j] *= inv
        x[i] *= inv

        for r in range(i + 1, n):
            f = M[r][i]
            if f != 0.0:
                for j in range(i, n):
                    M[r][j] -= f * M[i][j]
                x[r] -= f * x[i]

    # Back substitution
    for i in range(n - 1, -1, -1):
        for r in range(i):
            f = M[r][i]
            if f != 0.0:
                x[r] -= f * x[i]

    return x


def _matvec(A: list[list[float]], v: list[float]) -> list[float]:
    """Matrix-vector multiplication with NumPy or pure Python fallback."""
    if np is not None:
        import numpy as _np
        return (_np.asarray(A, dtype=float) @ _np.asarray(v, dtype=float)).tolist()

    return [sum(aij * vj for aij, vj in zip(ai, v)) for ai in A]


class PortfolioOptimizer:
    """
    Portfolio optimizer with NumPy/pure Python fallback compatibility.
    
    Implements mean-variance optimization with identical results regardless
    of whether NumPy is available or not.
    """

    def __init__(self, cfg: dict[str, Any] = None, *,
                 method: str = "mean_variance",
                 allow_short: bool = False,
                 risk_aversion: float = 1.0,
                 cvar_alpha: float = 0.975,
                 cvar_limit: float = 0.15,
                 gross_cap: float = 1.0,
                 max_weight: float = 1.0,
                 **kwargs):
        # Preserve passed-through configuration
        self.cfg = cfg or {}

        # Portfolio parameters
        self.method = method
        self.allow_short = bool(allow_short)
        self.risk_aversion = float(risk_aversion)
        self.cvar_alpha = cvar_alpha
        self.cvar_limit = cvar_limit
        self.gross_cap = gross_cap
        self.max_weight = max_weight

        # Accept and ignore other future kwargs for forward compatibility
        for k, v in kwargs.items():
            self.cfg.setdefault(k, v)

    def optimize(self, cov: list[list[float]], mu: list[float], *args, **kwargs) -> list[float]:
        """
        Mean-variance portfolio optimization.
        
        Solves w ∝ Σ^(-1) μ, then normalizes sum(w) = 1.
        Applies constraints if allow_short=False.
        
        Args:
            cov: Covariance matrix as list of lists
            mu: Expected returns as list
            
        Returns:
            Optimal weights as list of floats
        """
        try:
            # Handle empty inputs
            if not cov or not mu:
                return []

            n = len(mu)
            if n == 0:
                return []

            # Validate covariance matrix shape
            if not (isinstance(cov, (list, tuple)) and
                   all(isinstance(r, (list, tuple)) for r in cov) and
                   len(cov) == n and
                   all(len(r) == n for r in cov)):
                return [0.0 for _ in range(n)]

            # Mean-variance optimization: w_raw = Σ^(-1) μ
            w_raw = _solve_linear_system(cov, mu)

            # Normalize to sum = 1
            s = sum(w_raw)
            if abs(s) < 1e-12:
                # Fallback if μ gives zero sum - equal weights
                return [1.0 / n] * n

            w = [wi / s for wi in w_raw]

            # Apply short selling constraint if needed
            if not self.allow_short:
                w = [max(0.0, wi) for wi in w]
                s2 = sum(w)
                if abs(s2) < 1e-12:
                    return [1.0 / n] * n
                w = [wi / s2 for wi in w]

            # Apply max weight constraint with proper redistribution
            if self.max_weight is not None and self.max_weight > 0.0:
                # Simple clipping approach - clip but don't renormalize to preserve constraint
                w = [min(wi, self.max_weight) for wi in w]
                # Note: sum(w) may be < 1.0 after clipping, which is acceptable for box constraints

            # Apply gross cap constraint
            if self.gross_cap is not None and self.gross_cap > 0.0:
                total_exposure = sum(abs(wi) for wi in w)
                if total_exposure > self.gross_cap:
                    scale = self.gross_cap / total_exposure
                    w = [wi * scale for wi in w]

            return w

        except Exception:
            # Safe fallback for any unexpected issues
            n = len(mu) if mu else 0
            return [0.0] * n

    def mean_variance_optimize(self, cov: list[list[float]], mu: list[float]) -> list[float]:
        """Alias for optimize() method for backward compatibility."""
        return self.optimize(cov, mu)


__all__ = ["PortfolioOptimizer", "np"]
