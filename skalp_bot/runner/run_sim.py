import yaml
from skalp_bot.core.utils import synthetic_l5_stream
from skalp_bot.core.backtest_engine import L5Backtester
import matplotlib.pyplot as plt

def load_cfg(path='configs/default.yaml'):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def main():
    cfg = load_cfg()
    bt = L5Backtester(cfg)
    res = bt.run(synthetic_l5_stream())
    plt.figure(); plt.plot(res.pnls); plt.title('PnL (synthetic L5)'); plt.xlabel('t'); plt.ylabel('PnL'); plt.show()

if __name__ == '__main__':
    main()
