from __future__ import annotations

"""
Aurora Ingestion — Replay
=========================

High-precision record→replay engine that:
  • Reads raw events from an iterable or a source callable
  • Normalizes into canonical SSOT schema via Normalizer
  • Enforces anti–look-ahead (delegated to Normalizer) and event pacing via TickClock
  • Supports replay filters (time window, symbols, types) and user hooks
  • Produces deterministic stats for observability/governance

Example
-------
    from core.ingestion.normalizer import Normalizer
    from core.ingestion.sync_clock import ReplayClock
    from core.ingestion.replay import Replay

    replay = Replay(source=my_raw_iterable, normalizer=Normalizer(strict=False), clock=ReplayClock(speed=2.0))
    for evt in replay.stream(symbols={"BTCUSDT"}, post_filter=lambda e: e["type"]=="trade"):
        # evt is time-paced; do work here
        pass

Design notes
------------
- Events with identical timestamps are allowed; ordering stability can leverage optional 'seq'.
- Normalizer(strict=True) will raise on invalid/out-of-order per-stream events.
- When strict=False at Replay-level, invalids are counted & dropped; strict=True will raise.
- Pacing is wall-sleep before yield/callback, using clock.sleep_until_event_ts_ns(ts).
"""

from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
import logging
from typing import Any, Union

from core.ingestion.normalizer import Normalizer
from core.ingestion.sync_clock import RealTimeClock, ReplayClock, TickClock

logger = logging.getLogger("aurora.ingestion.replay")
logger.setLevel(logging.INFO)

Raw = Mapping[str, Any]
Event = dict[str, Any]
SourceLike = Union[Iterable[Raw], Callable[[], Iterable[Raw]]]


@dataclass
class ReplayStats:
    processed: int = 0          # raw events pulled
    normalized: int = 0         # successfully normalized
    emitted: int = 0            # yielded to caller
    dropped_invalid: int = 0    # bad schema / anti-look-ahead violations (when not strict)
    dropped_filtered: int = 0   # removed by filters (time/symbol/type/post_filter)
    errors: int = 0             # exceptions from hooks/transform

    def as_dict(self) -> dict[str, int]:
        return self.__dict__.copy()


class Replay:
    def __init__(
        self,
        *,
        source: SourceLike,
        normalizer: Normalizer | None = None,
        clock: TickClock | None = None,
        strict: bool = True,
        pace: bool = True,
        log_every: int = 50_000,
        max_sleep_ns: int | None = None,
    ) -> None:
        """
        Parameters
        ----------
        source : iterable or callable returning iterable of raw dicts
        normalizer : Normalizer (defaults to Normalizer(strict=strict))
        clock : TickClock (defaults to ReplayClock(speed=1.0) if pace else RealTimeClock)
        strict : if True, exceptions propagate; else invalid events are dropped & counted
        pace : if True, wall-sleep to align with event time using clock
        log_every : progress logging interval in processed events
        max_sleep_ns : optional max sleep duration per pacing call (for cancellable runs)
        """
        self._get_source = source if callable(source) else (lambda: source)  # always callable returning iterable
        self._norm = normalizer or Normalizer(strict=strict)
        self._strict = bool(strict)
        self._pace = bool(pace)
        self._clock = clock or (ReplayClock() if self._pace else RealTimeClock())
        self._log_every = int(log_every)
        self._max_sleep_ns = max_sleep_ns
        self._stop = False
        self.stats = ReplayStats()

    # -------------------- control --------------------

    def stop(self) -> None:
        """Signal the replay to stop after the current iteration."""
        self._stop = True

    # -------------------- streaming --------------------

    def stream(
        self,
        *,
        start_ts_ns: int | None = None,
        end_ts_ns: int | None = None,
        symbols: set[str] | None = None,
        types: set[str] | None = None,
        pre_filter: Callable[[Raw], bool] | None = None,
        post_filter: Callable[[Event], bool] | None = None,
        transform: Callable[[Event], Event] | None = None,
    ) -> Iterator[Event]:
        """Yield normalized events, time-paced if pace=True.

        Filters
        -------
        start_ts_ns / end_ts_ns : include only events in [start, end] by ts_ns
        symbols                 : uppercase symbols to include (None = no symbol filter)
        types                   : include only 'trade'/'quote' subset
        pre_filter              : called on raw before normalization
        post_filter             : called on normalized event (return False to drop)
        transform               : mapping Event->Event (e.g., add derived fields)
        """
        self._stop = False
        source_iter = self._get_source()

        processed = normalized = emitted = dropped_invalid = dropped_filtered = errors = 0

        for raw in source_iter:
            if self._stop:
                break
            processed += 1
            try:
                if pre_filter is not None and not pre_filter(raw):
                    dropped_filtered += 1
                    continue

                evt = self._norm.normalize(raw)
                if evt is None:
                    # strict=False in normalizer path
                    dropped_invalid += 1
                    continue
                normalized += 1

                ts = int(evt["ts_ns"])  # canonical
                if start_ts_ns is not None and ts < int(start_ts_ns):
                    dropped_filtered += 1
                    continue
                if end_ts_ns is not None and ts > int(end_ts_ns):
                    dropped_filtered += 1
                    continue

                if symbols is not None and evt["symbol"] not in symbols:
                    dropped_filtered += 1
                    continue
                if types is not None and evt["type"] not in types:
                    dropped_filtered += 1
                    continue

                if self._pace:
                    try:
                        if self._max_sleep_ns is not None:
                            # Chunk long sleeps for cancellable runs
                            target_ts = ts
                            while True:
                                remaining = target_ts - self._clock.now_ns()
                                if remaining <= 0:
                                    break
                                chunk = min(remaining, self._max_sleep_ns)
                                chunk_target = self._clock.now_ns() + chunk
                                self._clock.sleep_until_wall_ns(chunk_target)
                                if self._stop:  # Check for cancellation during chunking
                                    break
                        else:
                            self._clock.sleep_until_event_ts_ns(ts)
                    except Exception:
                        if self._strict:
                            raise
                        dropped_invalid += 1
                        continue

                # Carry over any extra fields from raw into the normalized event
                # so downstream transform/post-processing can inspect raw tags.
                try:
                    if isinstance(raw, dict):
                        for k, v in raw.items():
                            if k not in evt:
                                evt[k] = v
                except Exception:
                    # Ignore enrichment issues in non-strict mode
                    if self._strict:
                        raise

                if post_filter is not None and not post_filter(evt):
                    dropped_filtered += 1
                    continue

                if transform is not None:
                    try:
                        evt = transform(evt)
                    except Exception as e:
                        errors += 1
                        if self._strict:
                            raise
                        logger.debug("transform failed: %s", e)
                        continue

                yielded_evt = evt
                emitted += 1
                if self._log_every and processed % self._log_every == 0:
                    logger.info(
                        "replay progress: processed=%d normalized=%d emitted=%d dropped_invalid=%d dropped_filtered=%d",
                        processed,
                        normalized,
                        emitted,
                        dropped_invalid,
                        dropped_filtered,
                    )
                yield yielded_evt

            except Exception as e:
                if self._strict:
                    raise
                dropped_invalid += 1
                logger.debug("drop invalid event (strict=False): err=%s raw=%s", e, raw)

        # store stats at the end for the user to inspect
        self.stats = ReplayStats(
            processed=processed,
            normalized=normalized,
            emitted=emitted,
            dropped_invalid=dropped_invalid,
            dropped_filtered=dropped_filtered,
            errors=errors,
        )

    # -------------------- convenience runner --------------------

    def play(
        self,
        on_event: Callable[[Event], None] | None = None,
        **stream_kwargs: Any,
    ) -> ReplayStats:
        """Consume the stream; optionally call on_event(evt). Returns final stats."""
        for evt in self.stream(**stream_kwargs):
            if on_event is None:
                continue
            try:
                on_event(evt)
            except Exception as e:
                self.stats.errors += 1
                if self._strict:
                    raise
                logger.debug("on_event error: %s", e)

        # XAI-hook: emit service log event with ReplayStats for observability
        logger.info(
            "replay completed: source='ingestion.replay' stats=%s",
            self.stats.as_dict()
        )

        return self.stats


# -------------------- Lightweight generator API (post-transform filters) --------------------

from collections.abc import Callable, Iterable, Sequence
import time
from typing import Any


def replay_events(
    records: Iterable[Any],
    *,
    transformer: Callable[[Any], dict[str, Any] | None] | None = None,
    start_ns: int | None = None,
    end_ns: int | None = None,
    symbols: Sequence[str] | None = None,
    types: Sequence[str] | None = None,
    strict: bool = True,
    pace_ms: float | None = None,
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Pipeline: raw -> transformer -> filters(start/end/symbols/types) -> (optional) pacing -> yield.
    strict=False: любые ошибки/некорректные записи тихо дропаются. Фильтры применяются ПОСЛЕ трансформации.
    This API does not print to stdout/stderr.
    """
    _clock = clock or time.monotonic
    _sleep = sleep or time.sleep
    _symbols: set[str] | None = set(symbols) if symbols else None
    _types: set[str] | None = set(types) if types else None
    _pace_s = (pace_ms or 0.0) / 1000.0
    last_emit_t: float | None = None

    for rec in records:
        try:
            item = transformer(rec) if transformer is not None else rec
            if item is None or not isinstance(item, dict):
                continue

            ts = item.get("ts_ns")
            sym = item.get("symbol")
            typ = item.get("type")

            if start_ns is not None and (ts is None or ts < start_ns):
                continue
            if end_ns is not None and (ts is None or ts > end_ns):
                continue
            if _symbols is not None and sym not in _symbols:
                continue
            if _types is not None and typ not in _types:
                continue

            if _pace_s > 0.0:
                now = _clock()
                if last_emit_t is None:
                    last_emit_t = now
                else:
                    dt = now - last_emit_t
                    if dt < _pace_s:
                        _sleep(_pace_s - dt)
                    last_emit_t = _clock()

            yield item

        except Exception:
            if strict:
                raise
            # swallow and continue


def run_replay_stream(*args, **kwargs) -> Iterator[dict[str, Any]]:
    """Back-compat wrapper for callers using an older name."""
    return replay_events(*args, **kwargs)


__all__ = [
    "ReplayStats",
    "Replay",
    "replay_events",
    "run_replay_stream",
]
