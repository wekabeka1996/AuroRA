from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

OUT = Path("logs/sim_source.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)

now = datetime.now(UTC)
lines = []
for i in range(200):
    ts = now + timedelta(seconds=i)
    rec = {
        "event": "ORDER_STATUS(sim)",
        "order_id": f"sim_{i}",
        "time": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z",
        "status": "simulated",
        "payload": {"seq": i}
    }
    lines.append(json.dumps(rec, ensure_ascii=False))

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Wrote {OUT} (rows={len(lines)})")
