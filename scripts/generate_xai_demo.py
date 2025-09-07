#!/usr/bin/env python3
"""
Simple XAI Chain Demo - Generate sample XAI events for testing
"""

import json
import time
import uuid
from pathlib import Path

def generate_sample_xai_events():
    """Generate sample XAI events for demonstration"""

    # Create artifacts/xai directory
    xai_dir = Path("artifacts/xai")
    xai_dir.mkdir(parents=True, exist_ok=True)

    # Sample trace_id for the chain
    trace_id = str(uuid.uuid4())

    events = [
        {
            "ts": int(time.time() * 1000),
            "component": "signal",
            "decision": "long",
            "input": {"score": 2.1, "symbol": "BTCUSDT"},
            "explanation": {"type": "momentum", "threshold": 2.0},
            "confidence": 0.88,
            "trace_id": trace_id
        },
        {
            "ts": int(time.time() * 1000) + 100,
            "component": "risk",
            "decision": {"size": 0.05, "approved": True},
            "input": {"signal": "long"},
            "explanation": {"type": "risk_check", "var_limit": 0.02, "passed": True},
            "confidence": 0.92,
            "trace_id": trace_id
        },
        {
            "ts": int(time.time() * 1000) + 200,
            "component": "oms",
            "decision": {"order_id": "test_order_123", "status": "sent"},
            "input": {"order": {"symbol": "BTCUSDT", "side": "long", "size": 0.05}},
            "explanation": {"type": "order_routing", "exchange": "binance", "route": "spot"},
            "confidence": 0.95,
            "trace_id": trace_id
        }
    ]

    # Write events to file
    output_file = xai_dir / "xai_events.jsonl"
    with open(output_file, 'w', encoding='utf-8') as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')

    print(f"✅ Generated sample XAI events: {output_file}")
    print(f"📊 Trace ID: {trace_id}")
    print(f"🔗 Components: signal → risk → oms")

    return str(output_file)

if __name__ == "__main__":
    generate_sample_xai_events()