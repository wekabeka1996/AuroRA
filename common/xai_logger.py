import json
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path

ARTIFACT_DIR = Path("artifacts/xai")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

class XAILogger:
    def __init__(self, filename="xai_events.jsonl"):
        self.path = ARTIFACT_DIR / filename

    def _write(self, obj):
        with _lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False, cls=DecimalEncoder) + "\n")

    def emit(self, component, decision, input_, explanation, confidence, trace_id=None):
        if trace_id is None:
            trace_id = str(uuid.uuid4())
        ev = {
            "ts": int(time.time() * 1000),
            "component": component,
            "decision": decision,
            "input": input_,
            "explanation": explanation,
            "confidence": float(confidence),
            "trace_id": trace_id
        }
        self._write(ev)
        return trace_id

# singleton
xai = XAILogger()