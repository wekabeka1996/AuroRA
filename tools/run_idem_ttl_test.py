from pathlib import Path

from core.infra.idempotency_store import IdempotencyStore


class FakeClock:
    def __init__(self): self.t = 0
    def __call__(self): return self.t
    def advance_ms(self, ms): self.t += int(ms * 1e6)

out = Path("logs/idem_ttl_test.txt"); out.parent.mkdir(parents=True, exist_ok=True)
clk = FakeClock(); store = IdempotencyStore(ttl_sec=1, now_ns_fn=clk)

store.put("a", 1); clk.advance_ms(500); store.put("b", 2); clk.advance_ms(600)
removed1 = store.sweep(); clk.advance_ms(500); removed2 = store.sweep()

out.write_text(
    "after_sweep1_removed=%d; keys=%s\nafter_sweep2_removed=%d; keys=%s\n" % (
        removed1, list(store._data.keys()),
        removed2, list(store._data.keys())
    ),
    encoding="utf-8"
)
print(f"Wrote {out}")
