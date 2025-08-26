from __future__ import annotations

import json
from pathlib import Path
from tools.lifecycle_audit import build_graph


def test_build_graph_simple(tmp_path: Path):
    records = [
        {"decision_id": "d1", "order_id": "o1", "status": "CREATED"},
        {"decision_id": "d1", "order_id": "o1", "status": "SUBMITTED"},
        {"decision_id": "d1", "order_id": "o1", "status": "FILLED"},
        {"decision_id": "d1", "order_id": "o2", "status": "CREATED"},
        {"decision_id": "d1", "order_id": "o2", "status": "CANCELLED"},
    ]
    graph, anomalies = build_graph(records)
    assert graph["by_decision"]["d1"] == ["o1", "o2"]
    assert graph["by_order"]["o1"] == ["CREATED->SUBMITTED", "SUBMITTED->FILLED"]
    assert graph["by_order"]["o2"] == ["CREATED->CANCELLED"]
    assert anomalies == []
