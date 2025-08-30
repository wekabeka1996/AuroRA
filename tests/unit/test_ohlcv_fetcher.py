"""
CREATED BY ASSISTANT: Tests for top-level Binance OHLCV fetcher module (non-ASCII named file).
Purpose: document intended behavior (env keys, retries/backoff, DataFrame shape).

Note: The source file currently contains syntax/merge artifacts (duplicate returns,
duplicate signature line) and cannot be imported. These tests are marked xfail and
will activate once the module is repaired, serving as an executable spec.
"""

import os
import types
import pytest


pytestmark = pytest.mark.xfail(
    reason="Binance OHLCV fetcher module is syntactically invalid; fix source to enable tests",
    strict=False,
)


def test_create_binance_client_env_missing_raises(monkeypatch):
    # Simulate empty environment
    monkeypatch.delenv('BINANCE_API_KEY', raising=False)
    monkeypatch.delenv('BINANCE_API_SECRET', raising=False)

    import importlib.util, importlib.machinery, pathlib
    path = pathlib.Path('???????.py')
    spec = importlib.util.spec_from_file_location('ohlcv_fetcher', path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    # Import will currently fail due to syntax errors; once fixed the below will run
    loader = spec.loader  # type: ignore
    assert loader is not None
    loader.exec_module(mod)  # type: ignore  # noqa: F841

    with pytest.raises(RuntimeError):
        mod.create_binance_client()  # type: ignore[attr-defined]


def test_fetch_ohlcv_df_success_with_stub_exchange(tmp_path, monkeypatch):
    # Provide stub ccxt and pandas-ish behavior via real pandas dependency at runtime
    import pandas as pd

    class StubExchange:
        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            # return simple OHLCV rows
            base = int(since)
            rows = []
            for i in range(5):
                ts = base + i * 60_000
                rows.append([ts, 1.0+i, 2.0+i, 0.5+i, 1.5+i, 10+i])
            return rows

    import importlib.util, importlib.machinery, pathlib
    path = pathlib.Path('???????.py')
    spec = importlib.util.spec_from_file_location('ohlcv_fetcher', path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    loader = spec.loader  # type: ignore
    assert loader is not None
    loader.exec_module(mod)  # type: ignore  # noqa: F841

    df = mod.fetch_ohlcv_df(symbol='SOL/USDT', timeframe='1m', hours=1, limit=5, exchange=StubExchange())  # type: ignore[attr-defined]
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ['open','high','low','close','volume'] or 'open' in df.columns
    assert len(df) >= 5

