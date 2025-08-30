from __future__ import annotations

"""
Aurora Ingestion — Normalizer
-----------------------------
Goals
  • Convert heterogeneous raw market events (trades/quotes) into a canonical SSOT format
  • Enforce anti–look-ahead invariants (monotone non-decreasing timestamps per (symbol,type))
  • Provide deterministic types/units (timestamps in nanoseconds, prices/sizes as floats)
  • Be vendor-agnostic: recognize common key aliases (Binance/GateIO/CSV/Parquet loaders)

Canonical event schema (dict):
{
  'ts_ns': int,                  # UNIX epoch in nanoseconds (monotone per stream)
  'type': 'trade' | 'quote',     # event kind
  'symbol': str,                 # normalized symbol (upper, no spaces)
  'source': str,                 # data source tag (e.g., 'binance', 'replay', 'live')
  'seq': int | None,             # optional sequence number; used for strict ordering when ts_ns equal
  # trade fields
  'price': float | None,         # mid/price for trade; None for quote
  'size': float | None,          # trade size (base units)
  'side': 'buy' | 'sell' | None, # optional trade aggressor side
  # quote fields (top of book)
  'bid_px': float | None,
  'bid_sz': float | None,
  'ask_px': float | None,
  'ask_sz': float | None,
}

Invariants (enforced):
  • Event-time: ts_ns is monotonically non-decreasing per (symbol, type) stream
  • No look-ahead: future events cannot appear before past events in the same stream
  • Units: ts_ns in nanoseconds, prices/sizes as positive floats
  • Positivity: price > 0, size > 0 for trades; bid_px > 0, ask_px > 0 for quotes
  • Book integrity: bid_px ≤ ask_px (allows equality for crossed book detection)
  • Symbol normalization: uppercase, no spaces, deterministic

Design choices:
  • Pure-Python, zero external deps. Robust to partial/dirty inputs (drops/flags invalids).
  • Anti–look-ahead enforcement with per-(symbol,type) state; equal ts_ns ordered by seq if present.
  • Heuristics for vendor aliases, e.g., ts keys: ['ts','timestamp','T','E','time'],
    size keys: ['qty','size','amount'], price keys: ['p','price'] etc.

Usage:
    from core.ingestion.normalizer import Normalizer
    norm = Normalizer(source_tag='replay', strict=True)
    for evt in norm.normalize_iter(raw_events):
        ...  # evt is canonical dict

Notes:
  • If strict=True, invalid events raise ValueError; if False, they are skipped with a debug log.
  • TS detection auto-infers unit from magnitude (s/ms/us/ns). Floats allowed; coerced to int ns.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, Mapping, MutableMapping, Optional, Tuple

logger = logging.getLogger("aurora.ingestion.normalizer")
logger.setLevel(logging.INFO)

# -------------------- timestamp handling --------------------

def _detect_ts_unit(x: float | int) -> int:
    """Return multiplier to convert given epoch value to nanoseconds.
    Heuristic based on magnitude (2020s epoch ~ 1.6e9 s):
      seconds      ~ 1e9 .. 1e10     → *1e9
      milliseconds ~ 1e12 .. 1e13    → *1e6
      microseconds ~ 1e15 .. 1e16    → *1e3
      nanoseconds  ~ 1e18 .. 1e19    → *1
    """
    v = float(x)
    if v < 1e11:
        return 1_000_000_000  # seconds
    if v < 1e14:
        return 1_000_000      # milliseconds
    if v < 1e17:
        return 1_000          # microseconds
    return 1                   # nanoseconds


def to_ns(ts: Any) -> int:
    """Coerce a variety of timestamp inputs to integer nanoseconds since epoch."""
    if ts is None:
        raise ValueError("timestamp is None")
    if isinstance(ts, (int,)):
        mult = _detect_ts_unit(ts)
        return int(ts * mult)
    if isinstance(ts, float):
        # float seconds / ms / us / ns by magnitude
        mult = _detect_ts_unit(ts)
        return int(ts * mult)
    # strings: try to parse numeric
    s = str(ts).strip()
    if not s:
        raise ValueError("empty timestamp")
    try:
        if "." in s:
            val = float(s)
        else:
            val = int(s)
    except Exception as e:
        raise ValueError(f"unrecognized timestamp: {ts!r}") from e
    mult = _detect_ts_unit(val)
    return int(val * mult)

# -------------------- field helpers --------------------

_PRICE_KEYS = ("price", "p")
_SIZE_KEYS = ("size", "qty", "amount", "q")
_SIDE_KEYS = ("side", "S")
_BID_PX_KEYS = ("bid", "bid_px", "b")
_ASK_PX_KEYS = ("ask", "ask_px", "a")
_BID_SZ_KEYS = ("bid_size", "bid_sz", "bs")
_ASK_SZ_KEYS = ("ask_size", "ask_sz", "as")
_TS_KEYS = ("ts", "timestamp", "T", "E", "time", "event_time")
_SEQ_KEYS = ("seq", "sequence", "u", "U")
_TYPE_KEYS = ("type", "event_type", "e")
_SYMBOL_KEYS = ("symbol", "sym", "s", "instrument")


def _first(d: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d:
            return d[k]
    return None


def _normalize_symbol(sym: Any) -> str:
    s = str(sym).strip()
    if not s:
        raise ValueError("empty symbol")
    return s.upper().replace(" ", "")


def _normalize_side(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip().lower()
    if s in ("b", "buy", "bid", "taker_buy"):
        return "buy"
    if s in ("s", "sell", "ask", "taker_sell"):
        return "sell"
    # unknown → None (do not fail normalization)
    return None


def _coerce_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None

# -------------------- Normalizer --------------------

@dataclass
class _StreamState:
    last_ts_ns: int = -1
    last_seq: Optional[int] = None


class Normalizer:
    """Stateless API with stateful anti-look-ahead enforcement per (symbol, type).

    If strict=True, violations raise ValueError; else events are skipped.
    """

    def __init__(self, *, source_tag: str = "unknown", strict: bool = True) -> None:
        self._source = source_tag
        self._strict = strict
        self._state: Dict[Tuple[str, str], _StreamState] = {}

    # ---------- public API ----------

    def normalize(self, raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalize single raw event to canonical dict or return None if dropped (strict=False)."""
        try:
            evt = self._normalize_impl(raw)
            self._enforce_anti_lookahead(evt)
            return evt
        except Exception as e:
            if self._strict:
                raise
            logger.debug("drop invalid event: %s (err=%s)", raw, e)
            return None

    def normalize_iter(self, raws: Iterable[Mapping[str, Any]]) -> Iterator[Dict[str, Any]]:
        for r in raws:
            out = self.normalize(r)
            if out is not None:
                yield out

    # ---------- internals ----------

    def _normalize_impl(self, raw: Mapping[str, Any]) -> Dict[str, Any]:
        # core fields
        ts_val = _first(raw, _TS_KEYS)
        if ts_val is None:
            raise ValueError("missing timestamp")
        ts_ns = to_ns(ts_val)

        symbol = _first(raw, _SYMBOL_KEYS)
        if symbol is None:
            raise ValueError("missing symbol")
        sym = _normalize_symbol(symbol)

        typ_raw = _first(raw, _TYPE_KEYS)
        typ = str(typ_raw).lower() if typ_raw is not None else None

        seq_raw = _first(raw, _SEQ_KEYS)
        seq = None
        if seq_raw is not None:
            try:
                seq = int(seq_raw)
            except Exception:
                seq = None

        # Detect trade vs quote by presence of keys if type is ambiguous
        price = _coerce_float(_first(raw, _PRICE_KEYS))
        size = _coerce_float(_first(raw, _SIZE_KEYS))
        bid_px = _coerce_float(_first(raw, _BID_PX_KEYS))
        ask_px = _coerce_float(_first(raw, _ASK_PX_KEYS))
        bid_sz = _coerce_float(_first(raw, _BID_SZ_KEYS))
        ask_sz = _coerce_float(_first(raw, _ASK_SZ_KEYS))

        # Heuristic resolution
        kind: Optional[str] = None
        if typ in ("trade", "aggtrade", "t", "fills"):
            kind = "trade"
        elif typ in ("quote", "book_ticker", "book", "depth"):
            kind = "quote"
        else:
            # infer by keys
            if price is not None and size is not None:
                kind = "trade"
            elif bid_px is not None and ask_px is not None:
                kind = "quote"

        if kind is None:
            raise ValueError("unable to infer event type")

        base: Dict[str, Any] = {
            "ts_ns": ts_ns,
            "type": kind,
            "symbol": sym,
            "source": str(raw.get("source", self._source)),
            "seq": seq,
            "price": None,
            "size": None,
            "side": _normalize_side(raw.get("side")),
            "bid_px": None,
            "bid_sz": None,
            "ask_px": None,
            "ask_sz": None,
        }

        if kind == "trade":
            if price is None or size is None:
                raise ValueError("trade requires price and size")
            if price <= 0 or size <= 0:
                raise ValueError("trade price/size must be positive")
            base["price"] = price
            base["size"] = size
        else:  # quote
            # basic sanity: bid<=ask, sizes >=0 (None allowed)
            if bid_px is None or ask_px is None:
                raise ValueError("quote requires bid_px and ask_px")
            if bid_px <= 0 or ask_px <= 0:
                raise ValueError("quote prices must be positive")
            if bid_px > ask_px:
                # allow equality; strictly greater is invalid top-of-book
                raise ValueError("bid_px > ask_px (crossed book)")
            if bid_sz is not None and bid_sz < 0:
                raise ValueError("bid_sz < 0")
            if ask_sz is not None and ask_sz < 0:
                raise ValueError("ask_sz < 0")
            base["bid_px"] = bid_px
            base["ask_px"] = ask_px
            base["bid_sz"] = bid_sz
            base["ask_sz"] = ask_sz

        return base

    def _enforce_anti_lookahead(self, evt: Mapping[str, Any]) -> None:
        key = (evt["symbol"], evt["type"])  # per-stream ordering
        st = self._state.get(key)
        if st is None:
            st = _StreamState()
            self._state[key] = st
        ts = int(evt["ts_ns"])
        seq = evt.get("seq")
        if st.last_ts_ns > ts:
            raise ValueError(
                f"timestamp regression for {key}: {ts} < {st.last_ts_ns} (anti-look-ahead)"
            )
        if st.last_ts_ns == ts and st.last_seq is not None and seq is not None and seq < st.last_seq:
            raise ValueError(
                f"sequence regression for {key} at ts={ts}: {seq} < {st.last_seq}"
            )
        st.last_ts_ns = ts
        st.last_seq = seq if seq is not None else st.last_seq
