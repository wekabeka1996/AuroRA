import time, yaml
from skalp_bot.exch.ccxt_binance import CCXTBinanceAdapter
from skalp_bot.core.signals import micro_price, obi_from_l5, tfi_from_trades, combine_alpha

def load_cfg(path='configs/default.yaml'):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def main():
    cfg = load_cfg()
    ex = CCXTBinanceAdapter(cfg)
    alpha = cfg['alpha']
    print('Starting live (polling) loop — dry_run:', cfg.get('dry_run', True))
    while True:
        mid, spread, bids, asks, trades = ex.fetch_top_of_book()
        mp = micro_price(bids[0], asks[0])
        obi = obi_from_l5(bids, asks, alpha['obi_levels'])
        tfi = tfi_from_trades(trades)
        score = combine_alpha(obi, tfi, mp, mid, (alpha['obi_weight'], alpha['tfi_weight'], alpha['micro_weight']))
        print(f"mid={mid:.2f} score={score:+.3f} obi={obi} tfi={tfi}")
        time.sleep(1.0)

if __name__ == '__main__':
    main()
