from core.execution.router import Router, QuoteSnapshot
from core.tca.hazard_cox import CoxPH
from core.tca.latency import SLAGate
from core.execution.exchange.common import Fees

# Setup like test fixture
cox = CoxPH()
cox._beta = {'obi': 0.1, 'spread_bps': -0.05}
cox._feat = ['obi', 'spread_bps']

sla = SLAGate(max_latency_ms=250, kappa_bps_per_ms=0.01, min_edge_after_bps=1.0)

router = Router(hazard_model=cox, slagate=sla, min_p_fill=0.25, exchange_name='fake')

fill_features = {'obi': -0.8, 'spread_bps': 5.0}
quote = QuoteSnapshot(bid_px=49995.0, ask_px=50005.0, bid_sz=0.1, ask_sz=0.1)
E = 2.0
latency_ms = 10.0

half = quote.half_spread_bps
p_fill = router._estimate_p_fill(fill_features)

# taker pre
from core.execution.router import Router as _R

# compute e_taker_pre
e_taker_pre = E - half - router._fees.taker_fee_bps
sla_res = router._sla.gate(edge_bps=e_taker_pre, latency_ms=latency_ms)
e_taker = sla_res.edge_after_bps

# e_maker
e_maker = (E + half - router._fees.maker_fee_bps) * p_fill

# tca nets
taker_net = router._tca_net_edge_bps('taker', fill_features, E, latency_ms, half)
maker_net = router._tca_net_edge_bps('maker', fill_features, E, latency_ms, half)
cancel_cost_bps = half
exp_maker = p_fill * maker_net - (1.0 - p_fill) * cancel_cost_bps

print('half:', half)
print('p_fill:', p_fill)
print('e_taker_pre:', e_taker_pre)
print('sla.allow:', sla_res.allow)
print('e_taker:', e_taker)
print('e_maker:', e_maker)
print('taker_net:', taker_net)
print('maker_net:', maker_net)
print('exp_maker:', exp_maker)

decision = router.decide(side='buy', quote=quote, edge_bps_estimate=E, latency_ms=latency_ms, fill_features=fill_features)
print('decision.route:', decision.route)
print('decision.reason:', decision.reason)
print('decision.scores:', decision.scores)
