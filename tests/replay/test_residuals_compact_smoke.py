import json, tempfile, os
import numpy as np
from pathlib import Path

# We'll simulate the logic by crafting a summary similar to run_r0 output and invoking compaction helper directly.
from living_latent.core.utils.io import to_compact_stats

def test_to_compact_stats_basic():
    arr = np.arange(1000)
    stats = to_compact_stats(arr)
    assert stats['n'] == 1000
    assert 0 <= stats['q05'] <= stats['q50'] <= stats['q95'] <= 999

