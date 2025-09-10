from __future__ import annotations

"""
Decimal utilities for precise arithmetic and wire-safe string formatting.

Design:
- Use Decimal throughout (prec=28)
- No float() usage here; inputs are converted via Decimal(str(x))
- Provide helpers for step quantization and non-exponential string formatting
"""

from decimal import ROUND_DOWN, Decimal, getcontext
from typing import Union

# Configure global precision for our domain
getcontext().prec = 28

NumberLike = Union[str, int, float, Decimal]


def q_dec(x: NumberLike) -> Decimal:
    """Convert input to Decimal via str() to avoid binary float issues.

    Note: float is accepted as input type but is not used for arithmetic.
    """
    if isinstance(x, Decimal):
        return x
    # str() is safe for ints/strs and mitigates float binary artifacts
    return Decimal(str(x))


def quantize_step(x: Decimal, step: Decimal, rounding=ROUND_DOWN) -> Decimal:
    """Quantize x to the nearest multiple of step using the specified rounding.

    For step <= 0, returns x unchanged.
    """
    if step <= 0:
        return x
    # Compute the integer multiple and multiply back by step
    q = (x / step).to_integral_value(rounding=rounding)
    return q * step


def str_decimal(x: Decimal) -> str:
    """Return a string without scientific notation for Decimal values."""
    # Normalize removes trailing zeros; quantize to avoid exponent form
    s = format(x, "f")
    # Remove trailing zeros while keeping at least one zero after decimal if needed
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def str_decimal_step(x: Decimal, step: Decimal) -> str:
    """Format Decimal x preserving trailing zeros implied by step size.

    Example: x=Decimal('30000'), step=Decimal('0.01') -> '30000.00'
    If step <= 0, falls back to str_decimal.
    """
    try:
        if step > 0:
            return format(x.quantize(step, rounding=ROUND_DOWN), "f")
    except Exception:
        # Fallback to generic formatting in any edge cases
        pass
    return str_decimal(x)


__all__ = [
    "q_dec",
    "quantize_step",
    "str_decimal",
    "str_decimal_step",
]
