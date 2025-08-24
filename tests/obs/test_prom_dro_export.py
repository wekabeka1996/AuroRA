import tempfile, json
from pathlib import Path
import math

from living_latent.obs.metrics import Metrics

def test_prom_dro_export_gauges():
    m = Metrics(profile='test', buckets={})
    # baseline: nothing set yet -> gauges exist but no scrape needed
    # set values
    base = 0.75
    factor = 0.8
    adj = base * factor
    m.set_dro_risk_adjustment(base=base, factor=factor, adj=adj)
    fams = list(m.registry.collect())
    name_to_samples = {f.name: f for f in fams}
    assert 'aurora_risk_dro_factor' in name_to_samples, 'dro factor gauge missing'
    assert 'aurora_risk_dro_adj' in name_to_samples, 'dro adjusted gauge missing'
    # extract sample values
    factor_samples = [s.value for s in name_to_samples['aurora_risk_dro_factor'].samples if s.name=='aurora_risk_dro_factor']
    adj_samples = [s.value for s in name_to_samples['aurora_risk_dro_adj'].samples if s.name=='aurora_risk_dro_adj']
    assert factor_samples and math.isclose(factor_samples[0], factor, rel_tol=1e-9)
    assert adj_samples and math.isclose(adj_samples[0], adj, rel_tol=1e-9)
