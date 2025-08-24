from typing import Dict
from .signals import micro_price, obi_from_l5, tfi_from_trades, combine_alpha

class BacktestResult:
    def __init__(self):
        self.pnls = []
        self.positions = []
        self.scores = []
        self.mids = []

class L5Backtester:
    def __init__(self, cfg: Dict):
        self.cfg = cfg
        self.state = {"pos": 0.0, "entry_mid": None, "drawdown": 0.0}
        self.pnl = 0.0
        self.mids = []

    def step(self, mid, spread, bids, asks, trades) -> float:
        risk = self.cfg["risk"]
        alpha = self.cfg["alpha"]
        obi = obi_from_l5(bids, asks, int(alpha["obi_levels"]))
        tfi = tfi_from_trades(trades)
        mp = micro_price(bids[0], asks[0])
        score = combine_alpha(obi, tfi, mp, mid, (alpha["obi_weight"], alpha["tfi_weight"], alpha["micro_weight"]))
        self.mids.append(mid)
        vol = 0.0
        if len(self.mids) > int(risk["vol_window"]):
            import numpy as np
            vol = float(np.std(np.diff(self.mids[-int(risk["vol_window"]):])) / max(1e-9, np.mean(self.mids)))
        allow = vol <= float(risk["vol_max"])
        pos = self.state["pos"]
        if allow:
            if score > float(alpha["entry_threshold"]) and abs(pos) < float(risk["max_inventory"]):
                pos = float(risk["max_inventory"])
                if self.state["entry_mid"] is None:
                    self.state["entry_mid"] = mid
            elif score < -float(alpha["entry_threshold"]) and abs(pos) < float(risk["max_inventory"]):
                pos = -float(risk["max_inventory"])
                if self.state["entry_mid"] is None:
                    self.state["entry_mid"] = mid
        if abs(score) < float(alpha["exit_threshold"]):
            pos = 0.0
            self.state["entry_mid"] = None
        prev_mid = self.mids[-2] if len(self.mids) > 1 else mid
        self.pnl += pos * (mid - prev_mid)
        self.state["pos"] = pos
        self.state["drawdown"] = min(self.state.get("drawdown", -0.0), self.pnl)
        return score

    def run(self, stream):
        res = BacktestResult()
        for mid, spread, bids, asks, trades in stream:
            score = self.step(mid, spread, bids, asks, trades)
            res.pnls.append(self.pnl)
            res.positions.append(self.state["pos"])
            res.scores.append(score)
            res.mids.append(mid)
        return res
