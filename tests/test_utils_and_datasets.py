import os
import unittest
import pandas as pd
import numpy as np

from data_pipeline.utils import ensure_time_grid
from data_pipeline.dataset import ParquetSequenceDataset, FeaturesSequenceDataset


class TestUtilsAndDatasets(unittest.TestCase):
    def setUp(self):
        os.makedirs('data/tmp', exist_ok=True)
        # Create a simple hourly DF with a gap
        idx = pd.date_range('2023-01-01', periods=10, freq='1h', tz='UTC')
        df = pd.DataFrame({
            'open': np.arange(10) + 100,
            'high': np.arange(10) + 101,
            'low': np.arange(10) + 99,
            'close': np.arange(10) + 100.5,
            'volume': np.random.randint(1, 10, size=10)
        }, index=idx)
        df = df.drop(idx[5])  # remove one row to create a gap
        self.raw_df = df

        # Save a processed-like parquet for dataset tests
        proc_idx = pd.date_range('2023-01-01', periods=300, freq='1h', tz='UTC')
        feats = pd.DataFrame({
            'atr': np.random.rand(len(proc_idx)),
            'rsi_lite': np.random.rand(len(proc_idx)),
            'vwap': np.random.rand(len(proc_idx)),
            'realized_vola': np.random.rand(len(proc_idx)),
            'log_returns': np.random.randn(len(proc_idx)) * 0.01,
            'momentum_5': np.random.randn(len(proc_idx)),
            'vol_change': np.random.rand(len(proc_idx)),
            'ema_12': np.random.rand(len(proc_idx)),
            'ema_26': np.random.rand(len(proc_idx)),
            'macd': np.random.rand(len(proc_idx)),
            'macd_signal': np.random.rand(len(proc_idx)),
            'bb_width': np.random.rand(len(proc_idx)),
            'open': np.random.rand(len(proc_idx)) * 100,
            'high': np.random.rand(len(proc_idx)) * 100,
            'low': np.random.rand(len(proc_idx)) * 100,
            'close': np.random.rand(len(proc_idx)) * 100,
            'volume': np.random.randint(1, 10, size=len(proc_idx)),
        }, index=proc_idx)
        feats.to_parquet('data/tmp/processed.parquet')

    def test_ensure_time_grid_fills_gap(self):
        fixed = ensure_time_grid(self.raw_df, '1h')
        # Gap should be filled, length increases by 1
        self.assertEqual(len(fixed), len(self.raw_df) + 1)
        self.assertFalse(fixed.isna().any().any())

    def test_parquet_sequence_dataset(self):
        # Build a simple close-only parquet
        seq_idx = pd.date_range('2023-01-01', periods=200, freq='1h', tz='UTC')
        df = pd.DataFrame({'close': np.random.rand(len(seq_idx)) * 100}, index=seq_idx)
        df.to_parquet('data/tmp/seq.parquet')
        ds = ParquetSequenceDataset('data/tmp/seq.parquet', seq_len=32, target_col='close')
        self.assertTrue(len(ds) > 0)
        x = ds[0]
        self.assertEqual(tuple(x.shape), (32, 1))

    def test_features_sequence_dataset(self):
        ds = FeaturesSequenceDataset('data/tmp/processed.parquet', seq_len=32)
        self.assertTrue(len(ds) > 0)
        x = ds[0]
        self.assertEqual(x.shape[0], 32)
        self.assertTrue(x.shape[1] > 0)


if __name__ == '__main__':
    unittest.main()
