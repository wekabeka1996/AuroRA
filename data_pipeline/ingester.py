# data_pipeline/ingester.py
import pandas as pd
import numpy as np
from .connectors import BinanceConnector, PolygonConnector, S3DataLoader
from .utils import ensure_time_grid
from tenacity import retry, stop_after_attempt, wait_exponential
import pandas as pd
from datetime import datetime

class DataIngester:
    def __init__(self):
        # Лінива ініціалізація конекторів, щоб уникнути вимоги ccxt, якщо Binance не використовується
        self.sources = {
            'binance': BinanceConnector,
            'polygon': PolygonConnector,
            'historical': S3DataLoader
        }

    def _get_connector(self, source: str):
        if source not in self.sources:
            raise ValueError(f"Source '{source}' is not supported.")
        ctor = self.sources[source]
        return ctor()
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def fetch_ohlcv(self, source, **kwargs):
        """
        Завантажує OHLCV дані з вказаного джерела.
        
        :param source: 'binance', 'polygon', or 'historical'
        :param kwargs: Аргументи для відповідного конектора 
                       (e.g., symbol, timeframe, start, end for binance)
        :return: pd.DataFrame
        """
        # Тут реальна логіка з retry, валідацією та заповненням пропусків
        connector = self._get_connector(source)
        if source == 'historical':
            df = connector.get_data(kwargs.get('path', 'default/path'))
        else:
            symbol = kwargs.get('symbol')
            timeframe = kwargs.get('timeframe', '1h')
            start = kwargs.get('start')
            end = kwargs.get('end')
            if symbol is None or start is None:
                raise ValueError("symbol and start are required for live sources")
            df = connector.get_data(symbol=symbol, timeframe=timeframe, start=start, end=end)

        # Ensure UTC index and monotonic
        if not df.index.tz:
            df.index = df.index.tz_localize('UTC')
        df = df.sort_index()
        # Gap fill / enforce grid if timeframe present
        timeframe = kwargs.get('timeframe', '1h')
        try:
            df = ensure_time_grid(df, timeframe)
        except Exception as e:  # pragma: no cover
            print(f"WARN: ensure_time_grid failed: {e}")
        return df

    def _calculate_atr(self, df, window=14):
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/window, adjust=False).mean()
        return atr

    def _calculate_rsi(self, df, window=14):
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/window, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/window, adjust=False).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_vwap(self, df):
        q = df['volume']
        p = (df['high'] + df['low'] + df['close']) / 3
        vwap = (p * q).cumsum() / q.cumsum()
        return vwap

    def _calculate_realized_vol(self, df, window=20):
        log_returns = np.log(df['close'] / df['close'].shift())
        realized_vol = log_returns.rolling(window=window).std() * np.sqrt(252) # Annualized
        return realized_vol

    def calculate_features(self, df):
        """
        Розраховує фічі згідно з концепцією.
        """
        features = pd.DataFrame(index=df.index)

        # Основні фічі
        features['atr'] = self._calculate_atr(df)
        features['rsi_lite'] = self._calculate_rsi(df)
        features['vwap'] = self._calculate_vwap(df)
        features['realized_vola'] = self._calculate_realized_vol(df)

        # Додаткові базові фічі
        features['log_returns'] = np.log(df['close'] / df['close'].shift())
        features['momentum_5'] = df['close'] - df['close'].shift(5)
        features['vol_change'] = df['volume'] / df['volume'].rolling(window=10).mean()

        # EMA (12, 26)
        features['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
        features['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
        # MACD and signal
        macd = features['ema_12'] - features['ema_26']
        features['macd'] = macd
        features['macd_signal'] = macd.ewm(span=9, adjust=False).mean()
        # Bollinger Bandwidth (20, 2)
        ma20 = df['close'].rolling(window=20).mean()
        std20 = df['close'].rolling(window=20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        width = upper - lower
        features['bb_width'] = (width / ma20).replace([np.inf, -np.inf], np.nan)

        # Додаємо OHLCV, якщо потрібно студенту
        features = features.join(df[['open', 'high', 'low', 'close', 'volume']])

        # Прибираємо NaN після розрахунків
        features.dropna(inplace=True)

        print(f"INFO: [DataIngester] Calculated {len(features.columns)} features.")
        return features

    def build_dataset(self, source: str, feature_params: dict, **fetch_kwargs):
        """High-level helper: fetch raw OHLCV then compute features.
        Returns (raw_df, features_df)."""
        raw = self.fetch_ohlcv(source, **fetch_kwargs)
        feats = self.calculate_features(raw)
        # Align indices (features already dropna)
        raw = raw.loc[feats.index]
        return raw, feats
