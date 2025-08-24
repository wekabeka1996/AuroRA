import pandas as pd


def timeframe_to_pandas_freq(timeframe: str) -> str:
    mapping = {
        # minutes
        '1m': '1min', '3m': '3min', '5m': '5min', '15m': '15min', '30m': '30min',
        # hours (lowercase 'h' to avoid deprecation)
        '1h': '1h', '2h': '2h', '4h': '4h', '6h': '6h', '8h': '8h', '12h': '12h',
        # days
        '1d': '1d'
    }
    return mapping.get(timeframe, '1h')


essential_price_cols = ['open', 'high', 'low', 'close']


def ensure_time_grid(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Ensure uniform time grid based on timeframe, UTC DateTimeIndex, and fill gaps.
    - For price columns (OHLC): forward-fill
    - For 'volume': fill missing with 0 then forward-fill as fallback
    - Others: forward-fill
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError('DataFrame must have a DateTimeIndex (UTC).')
    df = df.sort_index()
    freq = timeframe_to_pandas_freq(timeframe)
    full_index = pd.date_range(df.index.min(), df.index.max(), freq=freq, tz='UTC')

    before = len(df)
    df = df.reindex(full_index)
    missing = df.isna().any(axis=1).sum()

    # Filling strategy
    for col in df.columns:
        if col == 'volume':
            df[col] = df[col].fillna(0).ffill()
        else:
            df[col] = df[col].ffill()

    after_missing = df.isna().sum().sum()
    if missing > 0 or after_missing > 0:
        print(f"WARN: ensure_time_grid filled {int(missing)} missing rows; remaining NaNs: {int(after_missing)}")

    df.index.name = 'timestamp'
    return df
