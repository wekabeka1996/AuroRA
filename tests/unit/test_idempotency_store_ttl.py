import time

class FakeClock:
    def __init__(self, start_ns=0):
        self.t = start_ns
    def __call__(self):
        return self.t
    def advance_ms(self, ms):
        self.t += int(ms * 1e6)


def test_ttl_sweep():
    from core.infra.idempotency_store import IdempotencyStore
    clk = FakeClock()
    store = IdempotencyStore(ttl_sec=1, now_ns_fn=clk)  # 1s TTL

    store.put("a", 1)              # t=0
    clk.advance_ms(500)            # t=0.5s
    store.put("b", 2)
    clk.advance_ms(600)            # t=1.1s

    removed = store.sweep()        # "a" протух
    assert removed == 1
    assert not store.seen("a") and store.seen("b")

    clk.advance_ms(500)            # t=1.6s
    removed = store.sweep()        # "b" протух
    assert removed == 1
    assert not store.seen("b")
