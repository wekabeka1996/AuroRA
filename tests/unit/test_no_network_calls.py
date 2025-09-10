
from skalp_bot.runner.run_live_aurora import create_adapter


def test_no_network_when_sim_local(monkeypatch):
    # Make sure that attempting to import or instantiate CCXTBinanceAdapter would raise
    def fake_ccxt_init(cfg):
        raise RuntimeError("Network adapter must not be instantiated during sim_local tests")

    # Monkeypatch the real adapter class in the module where it would be used
    import skalp_bot.runner.run_live_aurora as rmod
    monkeypatch.setattr(rmod, 'CCXTBinanceAdapter', fake_ccxt_init)

    cfg = {'order_sink': {'mode': 'sim_local', 'sim_local': {'seed': 7}}, 'symbol': 'TEST/USDT'}
    adapter = create_adapter(cfg)
    # Should return SimAdapter without calling the real adapter
    assert adapter.__class__.__name__ == 'SimAdapter'
    # calling place_order should not raise
    res = adapter.place_order('sell', 0.002, price=100.0)
    assert res.get('status') == 'closed'
