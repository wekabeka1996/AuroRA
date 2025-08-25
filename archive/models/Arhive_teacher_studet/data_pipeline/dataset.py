from typing import Optional, List

import pandas as pd
import torch
from torch.utils.data import Dataset


class ParquetSequenceDataset(Dataset):
    """
    Loads a Parquet file with a DateTimeIndex and OHLCV/features,
    and produces sliding windows of length seq_len over a target column (e.g., 'close').
    Returns windows shaped (seq_len, 1) for price-only teacher training by default.
    """

    def __init__(self, parquet_path: str, seq_len: int = 128, target_col: str = 'close', device: Optional[torch.device] = None):
        df = pd.read_parquet(parquet_path)
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                df = df.set_index('timestamp')
            else:
                raise ValueError('Parquet must have DateTimeIndex or timestamp column')
        df = df.sort_index()
        self.series = torch.tensor(df[target_col].values, dtype=torch.float32)
        self.seq_len = int(seq_len)
        self.device = device

    def __len__(self):
        return max(0, len(self.series) - self.seq_len)

    def __getitem__(self, idx):
        window = self.series[idx: idx + self.seq_len]
        return window.unsqueeze(1)  # (seq_len, 1)


class FeaturesSequenceDataset(Dataset):
    """
    Loads a processed Parquet file (e.g., from build_dataset.py) and returns sliding windows of
    engineered features of shape (seq_len, num_features).

    By default excludes raw OHLCV columns and the target column if provided.
    """

    def __init__(
        self,
        parquet_path: str,
        seq_len: int = 128,
        drop_columns: Optional[List[str]] = None,
        exclude_ohlcv: bool = True,
        exclude_target: str = 'log_returns',
    ):
        df = pd.read_parquet(parquet_path)
        if not isinstance(df.index, pd.DatetimeIndex):
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
                df = df.set_index('timestamp')
            else:
                raise ValueError('Parquet must have DateTimeIndex or timestamp column')
        df = df.sort_index()

        cols = list(df.columns)
        # Exclude raw OHLCV
        if exclude_ohlcv:
            for c in ['open', 'high', 'low', 'close', 'volume']:
                if c in cols:
                    cols.remove(c)
        # Exclude target if present
        if exclude_target and exclude_target in cols:
            cols.remove(exclude_target)
        # Drop additional columns if requested
        if drop_columns:
            for c in drop_columns:
                if c in cols:
                    cols.remove(c)

        self.features = torch.tensor(df[cols].astype('float32').values, dtype=torch.float32)
        self.seq_len = int(seq_len)
        self.num_features = len(cols)
        if self.num_features == 0:
            raise ValueError('No features selected for FeaturesSequenceDataset')

    def __len__(self):
        return max(0, len(self.features) - self.seq_len)

    def __getitem__(self, idx):
        window = self.features[idx: idx + self.seq_len]
        return window  # (seq_len, num_features)
