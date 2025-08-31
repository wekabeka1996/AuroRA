from pathlib import Path
from core.utils.timescale import to_ns
out = Path("logs/timescale_normalizer_test.txt"); out.parent.mkdir(parents=True, exist_ok=True)
vals = [("ns", 123), ("ms", 1.5), ("s", 2)]
lines = [f"{u}:{v} -> {to_ns(v,u)}" for u,v in vals]
out.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {out}")
