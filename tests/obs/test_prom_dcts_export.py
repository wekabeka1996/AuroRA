import json, tempfile, os, numpy as np
from pathlib import Path

# Minimal test focusing on metrics exporter extended layer

def test_prom_dcts_export_basic(tmp_path):
    from living_latent.obs.metrics import Metrics
    m = Metrics(profile='test', buckets={})
    # simulate call
    grids = {'0.5':0.9,'1.0':0.88}
    m.export_tvf_dcts_layer(base=0.87, robust=0.885, dmin=0.86, grids=grids, export_grids=True)
    # pull registry samples
    fams = list(m.registry.collect())
    names = {f.name for f in fams}
    assert 'aurora_tvf2_dcts_robust_value' in names
    assert 'aurora_tvf2_dcts_min_value' in names
    # ensure grid metrics exported
    grid_metric = [f for f in fams if f.name=='aurora_tvf2_dcts_grid']
    assert grid_metric, 'grid gauge missing'
    # sample labels check
    gm = grid_metric[0]
    label_sets = [tuple(s.labels.values()) for s in gm.samples if s.name=='aurora_tvf2_dcts_grid']
    assert any('0.5' in ls for ls in label_sets)
