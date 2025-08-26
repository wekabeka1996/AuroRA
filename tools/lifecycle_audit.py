#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def build_graph(records: List[Dict[str, Any]]):
    edges_by_order: Dict[str, List[str]] = defaultdict(list)
    by_oid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        oid = str(r.get("order_id") or r.get("orderId") or "")
        if not oid:
            continue
        by_oid[oid].append(r)

    anomalies = []
    for oid, evs in by_oid.items():
        # sort by ts if available to make path deterministic
        evs_sorted = sorted(
            evs,
            key=lambda x: x.get("ts") or x.get("ts_ms") or x.get("ts_iso") or "",
        )
        states = []
        for e in evs_sorted:
            s = str(e.get("status") or e.get("final_status") or e.get("state") or "").upper()
            if not s:
                continue
            if not states or states[-1] != s:
                states.append(s)
        # build edges
        for a, b in zip(states, states[1:]):
            edges_by_order[oid].append(f"{a}->{b}")
        # anomaly: duplicate terminal transitions
        terminals = {"FILLED", "CANCELLED", "EXPIRED"}
        term_count = sum(1 for s in states if s in terminals)
        if term_count > 1:
            anomalies.append({"order_id": oid, "type": "MULTIPLE_TERMINALS", "states": states})

    # also group by decision_id for later diagnostics
    dec_map: Dict[str, List[str]] = defaultdict(list)
    for r in records:
        did = str(r.get("decision_id") or r.get("decisionId") or "")
        oid = str(r.get("order_id") or r.get("orderId") or "")
        if did and oid and oid not in dec_map[did]:
            dec_map[did].append(oid)

    graph = {
        "by_order": edges_by_order,
        "by_decision": dec_map,
    }
    return graph, anomalies


def main() -> None:
    logs_dir = ROOT / "logs"
    success = load_jsonl(logs_dir / "orders_success.jsonl")
    failed = load_jsonl(logs_dir / "orders_failed.jsonl")
    denied = load_jsonl(logs_dir / "orders_denied.jsonl")
    records = []
    for r in success:
        r.setdefault("status", r.get("status") or "FILLED")
        records.append(r)
    for r in failed:
        r.setdefault("status", r.get("final_status") or "FAILED")
        records.append(r)
    for r in denied:
        r.setdefault("status", r.get("status") or "DENIED")
        records.append(r)

    graph, anomalies = build_graph(records)
    (ROOT / "reports").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "lifecycle_audit.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "reports" / "lifecycle_anomalies.json").write_text(
        json.dumps(anomalies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"orders": len(graph["by_order"]), "anomalies": len(anomalies)}))


if __name__ == "__main__":
    main()
