# data_pipeline/connectors.py
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional, List, Union

try:  # pragma: no cover - середовище без ccxt допустиме для офлайн тестів
    import ccxt  # type: ignore
except Exception:  # noqa
    ccxt = None  # type: ignore

# Узгоджені проксі для типів виключень, щоб статичний аналіз не падав коли ccxt відсутній
if ccxt is None:  # pragma: no cover
    class _DummyEx(Exception):
        pass
    class NetworkError(_DummyEx):
        pass
    class ExchangeNotAvailable(_DummyEx):
        pass
    class DDoSProtection(_DummyEx):
        pass
    _CCXT_NETWORK_ERRORS = (NetworkError, ExchangeNotAvailable, DDoSProtection)
else:  # pragma: no cover
    _CCXT_NETWORK_ERRORS = (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.DDoSProtection)
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import pandas as pd

# ЦЕ ЗАГЛУШКИ. Вони імітують отримання даних з реальних джерел.
# У реальній системі тут буде логіка для роботи з API Binance, Polygon.io та S3.

class BinanceConnector:
    """
    Реальний конектор до Binance через ccxt.
    Підтримує пагінацію, коректну часову зону (UTC) та повтори при помилках мережі.
    """

    def __init__(self, api_key: Optional[str] = None, secret: Optional[str] = None):
        if ccxt is None:
            raise ImportError("ccxt is required for BinanceConnector. Please install 'ccxt'.")
        self.exchange = ccxt.binance({
            'apiKey': api_key or '',
            'secret': secret or '',
            'enableRateLimit': True,
            # 'options': {'adjustForTimeDifference': True},
        })

    def _parse_time(self, x) -> Optional[int]:
        """Return milliseconds timestamp for ccxt from str/int/datetime or None."""
        if x is None:
            return None  # type: ignore
        if isinstance(x, (int, np.integer)):
            return int(x)
        if isinstance(x, str):
            # Try ccxt parse8601 first; fallback to pandas for date-only like '2023-01-01'
            try:
                parsed = self.exchange.parse8601(x)
                if parsed is not None:
                    return parsed
            except Exception:
                pass
            # Fallback: pandas to_datetime, assume UTC if tz-naive
            dt = pd.to_datetime(x, utc=True)
            return int(dt.timestamp() * 1000)
        if isinstance(x, datetime):
            if x.tzinfo is None:
                x = x.replace(tzinfo=timezone.utc)
            return int(x.timestamp() * 1000)
        raise ValueError("Unsupported time format for start/end")

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=1, max=10),
           retry=retry_if_exception_type(_CCXT_NETWORK_ERRORS))
    def _fetch_ohlcv_once(self, symbol: str, timeframe: str, since: Optional[int], limit: int = 1000):
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)

    def get_data(self, symbol: str, timeframe: str, start, end) -> pd.DataFrame:
        print(f"INFO: [BinanceConnector] Fetching {symbol} {timeframe} {start} -> {end}")
        since = self._parse_time(start)
        end_ms = self._parse_time(end)
        if since is None:
            raise ValueError("start is required for BinanceConnector")
        if end_ms is None:
            end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)

        all_rows = []
        limit = 1000  # Binance max
        while since <= end_ms:
            batch = self._fetch_ohlcv_once(symbol, timeframe, since, limit=limit)
            if not batch:
                break
            all_rows.extend(batch)
            last_ts = batch[-1][0]
            # advance by one candle to avoid duplicates
            increment = {
                '1m': 60_000,
                '3m': 180_000,
                '5m': 300_000,
                '15m': 900_000,
                '30m': 1_800_000,
                '1h': 3_600_000,
                '2h': 7_200_000,
                '4h': 14_400_000,
                '6h': 21_600_000,
                '8h': 28_800_000,
                '12h': 43_200_000,
                '1d': 86_400_000,
            }.get(timeframe, 3_600_000)
            since = last_ts + increment
            if last_ts >= end_ms:
                break

        if not all_rows:
            return pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume'])  # empty

        df = pd.DataFrame(all_rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        # filter to [start, end] if end provided, else [start, now]
        start_dt = pd.to_datetime(start, utc=True)
        if end is not None:
            end_dt = pd.to_datetime(end, utc=True)
            df = df.loc[(df.index >= start_dt) & (df.index <= end_dt)]
        else:
            df = df.loc[df.index >= start_dt]
        # ensure numeric types
        df = df.astype({k: 'float64' for k in ['open', 'high', 'low', 'close', 'volume']})
        return df

class PolygonConnector:
    def get_data(self, symbol: str, timeframe: str, start, end) -> pd.DataFrame:
        print(f"INFO: [PolygonConnector] Fetching {symbol} {timeframe} data (stub)...")
        # Синтетичні дані як заглушка
        dates = pd.to_datetime(pd.date_range(start, end, freq=timeframe if timeframe in ['1h','1d'] else '1h'))
        price = 100 + np.random.randn(len(dates)).cumsum()
        volume = np.random.randint(100, 1000, size=len(dates))
        df = pd.DataFrame({
            'open': price,
            'high': price + np.random.uniform(0, 5, size=len(dates)),
            'low': price - np.random.uniform(0, 5, size=len(dates)),
            'close': price + np.random.uniform(-2, 2, size=len(dates)),
            'volume': volume
        }, index=dates)
        df.index.name = 'timestamp'
        df.index = df.index.tz_localize('UTC')
        return df

class S3DataLoader:
    def get_data(self, path: str) -> pd.DataFrame:
        print(f"INFO: [S3DataLoader] Fetching data from {path} (stub)...")
        # Синтетичні дані як заглушка для офлайн режиму
        dates = pd.to_datetime(pd.date_range('2023-01-01', '2023-01-31', freq='1h'))
        price = 100 + np.random.randn(len(dates)).cumsum()
        volume = np.random.randint(100, 1000, size=len(dates))
        df = pd.DataFrame({
            'open': price,
            'high': price + np.random.uniform(0, 5, size=len(dates)),
            'low': price - np.random.uniform(0, 5, size=len(dates)),
            'close': price + np.random.uniform(-2, 2, size=len(dates)),
            'volume': volume
        }, index=dates)
        df.index.name = 'timestamp'
        df.index = df.index.tz_localize('UTC')
        return df
