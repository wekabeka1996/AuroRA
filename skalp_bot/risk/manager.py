
class RiskManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.start_pnl = 0.0
        self.cur_pnl = 0.0

    def update_pnl(self, pnl: float):
        self.cur_pnl = pnl

    def breach(self) -> bool:
        max_dd = float(self.cfg["risk"]["max_drawdown_pct"])
        if self.start_pnl == 0.0:
            return False
        dd = 100.0 * (self.cur_pnl - self.start_pnl) / abs(self.start_pnl)
        return dd <= -max_dd
