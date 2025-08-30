from __future__ import annotations

"""
Benjamini–Hochberg (BH) / Benjamini–Yekutieli (BY) FDR control
===============================================================

Implements:
- q-values (adjusted p-values) for BH and BY procedures
- optional Storey adaptive π₀ estimation to improve power under many alternatives
- rejection decision at level α

References
----------
Benjamini, Y., & Hochberg, Y. (1995). Controlling the False Discovery Rate.
Benjamini, Y., & Yekutieli, D. (2001). The control of the false discovery rate under dependency.
Storey, J. D. (2002). A direct approach to false discovery rates.

Notes
-----
- BH is valid under independence/PRDS on the subset; BY is valid under arbitrary dependence (but conservative).
- q-values are returned in the **original order** of p-values and are clipped to [0, 1].
- Pure Python, no NumPy dependency.
"""

from typing import Iterable, List, Sequence, Tuple

# -------------------- Utilities --------------------

def _validate_pvals(p: Sequence[float]) -> None:
    if len(p) == 0:
        raise ValueError("p-values empty")
    for x in p:
        if not (0.0 <= float(x) <= 1.0):
            raise ValueError("p-values must be in [0,1]")


def _argsort(p: Sequence[float]) -> List[int]:
    return sorted(range(len(p)), key=lambda i: float(p[i]))


def _harmonic_number(m: int) -> float:
    s = 0.0
    for k in range(1, m + 1):
        s += 1.0 / k
    return s


# -------------------- Core: q-values --------------------

def bh_qvalues(p: Sequence[float], *, pi0: float = 1.0) -> List[float]:
    """Benjamini–Hochberg q-values with optional Storey scaling by π₀.

    Parameters
    ----------
    p : sequence of p-values
    pi0 : estimate of proportion of true nulls (<=1). Defaults to 1.0 (classical BH)
    """
    _validate_pvals(p)
    m = len(p)
    order = _argsort(p)
    q_sorted = [0.0] * m

    # Compute monotone step-up adjusted values in sorted order
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):  # iterate from largest p to smallest
        j = m - rank + 1  # original rank (1..m) for p_(j)
        val = (pi0 * m * float(p[idx])) / j
        if val < prev:
            prev = val
        q_sorted[j - 1] = prev

    # Map back to original order and clip
    q = [0.0] * m
    for pos, idx in enumerate(order):
        q[idx] = q_sorted[pos]
    return [0.0 if x < 0.0 else 1.0 if x > 1.0 else x for x in q]


def by_qvalues(p: Sequence[float]) -> List[float]:
    """Benjamini–Yekutieli q-values (arbitrary dependence)."""
    _validate_pvals(p)
    m = len(p)
    c_m = _harmonic_number(m)
    # Equivalent to BH with scaling by c_m
    return bh_qvalues(p, pi0=c_m)


# -------------------- Storey π₀ estimation --------------------

def storey_pi0(p: Sequence[float], lambdas: Iterable[float] | None = None) -> float:
    """Estimate π₀ via Storey (2002) using grid of λ in [0.5, 0.95].

    π₀(λ) = #{p_i > λ} / (m * (1 - λ))
    We compute on a grid and take a smoothed, monotonically non-increasing envelope.
    Returns min(1, envelope at maximum λ).
    """
    _validate_pvals(p)
    m = len(p)
    if lambdas is None:
        lambdas = [0.50 + 0.05 * k for k in range(10)]  # 0.50..0.95
    lam = sorted([x for x in lambdas if 0.0 <= x < 1.0])
    if not lam:
        return 1.0

    # counts above each lambda
    p_sorted = sorted(float(x) for x in p)
    j = 0
    est = []
    for L in lam:
        # find first index with p > L (binary search could be used; linear OK for small m)
        while j < m and p_sorted[j] <= L:
            j += 1
        count = m - j
        denom = m * (1.0 - L)
        val = count / denom if denom > 0 else 1.0
        if val < 0:
            val = 0.0
        est.append(val)

    # enforce monotone non-increasing with respect to λ (right-to-left cumulative min)
    for i in range(len(est) - 2, -1, -1):
        if est[i] < est[i + 1]:
            est[i] = est[i + 1]

    pi0 = est[-1]
    if pi0 > 1.0:
        pi0 = 1.0
    if pi0 < 0.0:
        pi0 = 0.0
    return pi0


# -------------------- Decisions --------------------

def reject(
    p: Sequence[float],
    *,
    alpha: float = 0.05,
    method: str = "bh",
    pi0: float | None = None,
) -> Tuple[List[bool], int]:
    """Return rejection mask and number of rejections under a chosen FDR method.

    method: 'bh', 'bh_storey' (Storey π₀), or 'by'
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0,1)")
    _validate_pvals(p)

    method = method.lower()
    if method == "bh":
        q = bh_qvalues(p, pi0=1.0 if pi0 is None else float(pi0))
    elif method in ("bh_storey", "storey"):
        pi0_hat = storey_pi0(p) if pi0 is None else float(pi0)
        q = bh_qvalues(p, pi0=pi0_hat)
    elif method == "by":
        q = by_qvalues(p)
    else:
        raise ValueError("unknown method: " + method)

    mask = [qi <= alpha for qi in q]
    k = sum(mask)
    return mask, k


def bh_threshold(p: Sequence[float], *, alpha: float = 0.05) -> Tuple[float | None, int]:
    """Return (p*, k) where k is number of rejections and p* the largest p-value among rejections.

    p* = max{ p_(j) : p_(j) <= (j/m) * alpha }, computed in sorted order.
    Returns (None, 0) if no rejections.
    """
    _validate_pvals(p)
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0,1)")

    order = _argsort(p)
    m = len(p)
    pstar = None
    k = 0
    for j, idx in enumerate(order, start=1):  # ascending p
        thresh = (j / m) * alpha
        if float(p[idx]) <= thresh:
            pstar = float(p[idx])
            k = j
    return pstar, k


__all__ = [
    "bh_qvalues",
    "by_qvalue