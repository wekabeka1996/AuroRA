#!/usr/bin/env python3
import os, time, math, sys
from pathlib import Path

# Ensure workspace root is on sys.path so `import core...` works when script is run
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tca.tca_analyzer import TCAAnalyzer, OrderExecution, FillEvent

OUT = Path("logs/tca_identity_check.txt")
OUT.parent.mkdir(parents=True, exist_ok=True)


def run_case(side, liq, fee_signed, edge_bps=0.0, spread_bps=1.0, latency_ms=10.0, adverse_bps=0.0, slip_bps=0.0, price=100.0):
    now = time.time_ns()
    fills = [FillEvent(ts_ns=now, qty=100.0, price=price, fee=fee_signed, liquidity_flag=liq, queue_pos=1)]
    ex = OrderExecution(
        order_id=f"{side}_{liq}_{fee_signed:+.2f}",
        symbol="TEST",
        side=side,
        target_qty=100.0,
        fills=fills,
        arrival_ts_ns=now - 2_000_000_000,
        decision_ts_ns=now - 2_500_000_000,
        arrival_price=price,
        arrival_spread_bps=spread_bps,
        latency_ms=latency_ms
    )
    md = {"mid_price":price, "micro_price":price, "slip_bps":slip_bps, "expected_edge_bps":edge_bps, "adverse_bps":adverse_bps}
    m = TCAAnalyzer().analyze_order(ex, md)

    # Fallbacks for old/new fields
    spread   = getattr(m, "spread_cost_bps", 0.0) or getattr(m, "slippage_in_bps", 0.0)
    latency  = getattr(m, "latency_slippage_bps", 0.0) or getattr(m, "latency_bps", 0.0)
    adverse  = getattr(m, "adverse_selection_bps", 0.0) or getattr(m, "adverse_bps", 0.0)
    impact   = getattr(m, "temporary_impact_bps", 0.0) or getattr(m, "impact_bps", 0.0)
    fees     = getattr(m, "fees_bps", 0.0)
    rebate   = getattr(m, "rebate_bps", 0.0)
    raw_edge = getattr(m, "raw_edge_bps", getattr(m, "expected_gain_bps", 0.0))
    is_bps   = getattr(m, "implementation_shortfall_bps")
    canonical_is = getattr(m, "canonical_is_bps", None)

    # Implementation shortfall identity (legacy-positive): components use absolute fee magnitude and rebate reduces cost
    rhs = raw_edge + abs(fees) + spread + latency + adverse + impact - rebate
    delta = abs(is_bps - rhs)

    # Canonical identity (signed components): canonical_is_bps should equal raw + fees + canonical components + rebate
    canonical_rhs = None
    canonical_delta = None
    if canonical_is is not None:
        canonical_rhs = raw_edge + fees + (-spread) + (-latency) + (-adverse) + (-impact) + rebate
        # Note: here 'spread' holds legacy positive value; canonical slippage_in_bps = -spread
        canonical_delta = abs(canonical_is - canonical_rhs)
    return {
        "side": side, "liq": liq,
        "raw_edge": raw_edge, "fees": fees, "rebate": rebate,
        "spread": spread, "latency": latency, "adverse": adverse, "impact": impact,
        "IS": is_bps, "RHS": rhs, "Δ": delta
    }


def fmt(row):
    def f(x):
        return f"{x:.6f}" if isinstance(x, float) else str(x)
    cols = ["side","liq","raw_edge","fees","rebate","spread","latency","adverse","impact","IS","RHS","Δ"]
    return " | ".join(f(row[c]) for c in cols)


rows = []
# 4 basic scenarios
rows += [run_case("BUY","M",-1.0), run_case("BUY","T",+1.0),
         run_case("SELL","M",-1.0), run_case("SELL","T",+1.0)]
# stress cases
rows += [run_case("BUY","T",+0.5, edge_bps=+3.0, adverse_bps=-2.0, slip_bps=4.0),
         run_case("SELL","M",-0.2, edge_bps=-1.0, adverse_bps=-1.5, slip_bps=2.5),
         run_case("BUY","M",-0.3, edge_bps=+0.0, adverse_bps=0.0, slip_bps=0.0)]

header = "side | liq | raw_edge | fees | rebate | spread | latency | adverse | impact | IS | RHS | Δ"
sep = "-"*len(header)

with OUT.open("w", encoding="utf-8") as f:
    f.write("# TCA Identity Check (BUY/SELL × Maker/Taker + stress)\n")
    f.write(header + "\n" + sep + "\n")
    for r in rows:
        f.write(fmt(r) + "\n")
    worst = max(r["Δ"] for r in rows)
    f.write("\nMax Δ = %.12f  (tolerance ≤ 1e-6)\n" % worst)

print(f"Wrote {OUT} (rows={len(rows)})")
