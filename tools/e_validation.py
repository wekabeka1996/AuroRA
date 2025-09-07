#!/usr/bin/env python3
"""E-Validation helper (Futures-only)

Не запускає API чи бота. Читає вже існуючі артефакти сесії та формує додаткові
звіти для E0–E10.

Підкоманди:
  env-snapshot   --out <file>
  metrics-scrape --url <metrics_url> --out <file>
  lifecycle      --session <dir> --out <file>
  deny-counts    --session <dir> --out <file>
  tree           --session <dir> --out <file>
  signoff        --session <dir> --out <file>

Sign-off JSON (E10):
  version, generated_utc, session_dir, hashes, orders{fills,failed,denies,top_reason_codes}, latency{p50_ms,p95_ms}
"""
from __future__ import annotations
import argparse, os, sys, json, hashlib, datetime as dt, re
from typing import Dict, List, Any, Optional

SESSION_FILES = [
    "aurora_events.jsonl",
    "orders_denied.jsonl",
    "orders_failed.jsonl",
    "orders_success.jsonl",
]

TS_FIELDS = ["ts", "time", "timestamp", "wall_ts", "t"]
LAT_KEYS = ["latency_ms", "order_submit_latency_ms"]
EVENT_FIELD = "event"

DENY_METRIC_RE = re.compile(r'^aurora_.*denies.*\{.*code="(?P<code>[^"]+)".*\}\s+(?P<val>[-+eE0-9\.]+)')

# -------------------- IO utils --------------------

def _read_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()

def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)

def _sha256_file(path: str) -> Dict[str, Any]:
    h = hashlib.sha256()
    sz = 0
    lines = 0
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1<<20), b''):
            h.update(chunk)
            sz += len(chunk)
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for _ in f:
            lines += 1
    return {"sha256": h.hexdigest(), "bytes": sz, "lines": lines}

# -------------------- parsing helpers --------------------

def _safe_json(line: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(line)
    except Exception:
        return None

def read_session(session_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    data: Dict[str, List[Dict[str, Any]]] = {}
    for name in SESSION_FILES:
        fp = os.path.join(session_dir, name)
        rows: List[Dict[str, Any]] = []
        if os.path.isfile(fp):
            with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    obj = _safe_json(line)
                    if obj is not None:
                        rows.append(obj)
        data[name] = rows
    return data

def parse_metrics(text: str) -> Dict[str, Any]:
    out = {"deny_counters": {}}
    for line in text.splitlines():
        m = DENY_METRIC_RE.match(line.strip())
        if m:
            try:
                out["deny_counters"][m.group('code')] = float(m.group('val'))
            except Exception:
                pass
    return out

# -------------------- analytics --------------------

def count_deny_codes(denied_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for obj in denied_rows:
        code = obj.get('reason_code') or obj.get('why') or obj.get('deny_reason') or 'UNKNOWN'
        counts[code] = counts.get(code, 0) + 1
    return counts

def _get_ts(obj: Dict[str, Any]) -> Optional[float]:
    for k in TS_FIELDS:
        v = obj.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None

def extract_lifecycle(session: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for src in ["orders_success.jsonl", "orders_failed.jsonl", "orders_denied.jsonl"]:
        for obj in session.get(src, []):
            ev = obj.get(EVENT_FIELD) or obj.get('event_code') or obj.get('code') or obj.get('action')
            ts = _get_ts(obj)
            if ev is None and 'status' in obj:
                ev = f"ORDER.{obj['status']}"
            rows.append({"source": src, "event": ev, "ts": ts, "raw": obj})
    rows.sort(key=lambda r: (r['ts'] if r['ts'] is not None else float('inf')))
    return rows

def compute_latency(session: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    vals: List[float] = []
    for src in ["orders_success.jsonl", "orders_failed.jsonl"]:
        for obj in session.get(src, []):
            for lk in LAT_KEYS:
                v = obj.get(lk)
                if isinstance(v, (int, float)) and v >= 0:
                    vals.append(float(v))
                    break
    if not vals:
        submits = [o for o in session.get("orders_success.jsonl", []) if str(o.get('event','')).endswith('SUBMIT')]
        acks = [o for o in session.get("orders_success.jsonl", []) if str(o.get('event','')).endswith('ACK')]
        if submits and acks:
            s_ts = _get_ts(submits[0])
            a_ts = _get_ts(acks[0])
            if s_ts and a_ts and a_ts >= s_ts:
                vals.append((a_ts - s_ts)*1000.0)
    if not vals:
        return {"available": False}
    vals.sort()
    def pct(p: float) -> float:
        if not vals: return 0.0
        idx = max(0, min(len(vals)-1, int(round((p/100.0)*(len(vals)-1)))))
        return vals[idx]
    return {"available": True, "count": len(vals), "p50_ms": pct(50), "p95_ms": pct(95)}

# -------------------- signoff --------------------

def build_signoff(session_dir: str) -> Dict[str, Any]:
    sess = read_session(session_dir)
    hashes = {}
    for name in SESSION_FILES:
        fp = os.path.join(session_dir, name)
        if os.path.isfile(fp):
            hashes[name] = _sha256_file(fp)
    denies = count_deny_codes(sess.get('orders_denied.jsonl', []))
    fills = sum(1 for r in sess.get('orders_success.jsonl', []) if str(r.get('event','')).endswith(('FILL', 'FILLED')))
    failed = len(sess.get('orders_failed.jsonl', []))
    latency = compute_latency(sess)
    top = sorted(denies.items(), key=lambda kv:(-kv[1], kv[0]))[:5]
    return {
        "version": "E10-signoff-v1",
        "generated_utc": dt.datetime.utcnow().isoformat()+"Z",
        "session_dir": session_dir,
        "hashes": hashes,
        "orders": {
            "fills": fills,
            "failed": failed,
            "denies": sum(denies.values()),
            "top_reason_codes": [{"code": k, "count": v} for k,v in top]
        },
        "latency": latency,
    }

# -------------------- commands --------------------

def cmd_env_snapshot(a):
    keys = [k for k in os.environ if re.search(r"^(AURORA_|BINANCE|EXCHANGE|DRY_RUN|LEVERAGE|MARGIN|SESSION|METRICS)", k, re.I)]
    lines = []
    for k in sorted(keys):
        v = os.environ.get(k, '')
        if 'SECRET' in k or 'KEY' in k:
            if len(v) > 8:
                v = v[:4] + '…' + v[-4:]
            else:
                v = '***'
        lines.append(f"{k}={v}")
    _write_text(a.out, "\n".join(lines)+"\n")
    print(f"[env-snapshot] wrote {a.out}")

def cmd_metrics_scrape(a):
    try:
        import urllib.request
        with urllib.request.urlopen(a.url, timeout=5) as r:
            text = r.read().decode('utf-8', errors='ignore')
    except Exception as e:
        text = f"ERROR: {e}\n"
    _write_text(a.out, text)
    if not text.startswith('ERROR:'):
        parsed = parse_metrics(text)
        if parsed['deny_counters']:
            print(f"[metrics] deny counters: {len(parsed['deny_counters'])}")
    print(f"[metrics-scrape] wrote {a.out}")

def cmd_lifecycle(a):
    sess = read_session(a.session)
    rows = extract_lifecycle(sess)
    with open(a.out, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False)+"\n")
    print(f"[lifecycle] rows={len(rows)} → {a.out}")

def cmd_deny_counts(a):
    sess = read_session(a.session)
    counts = count_deny_codes(sess.get('orders_denied.jsonl', []))
    lines = [f"{v:6d} {k}" for k,v in sorted(counts.items(), key=lambda kv:(-kv[1], kv[0]))]
    _write_text(a.out, "\n".join(lines)+"\n")
    print(f"[deny-counts] unique={len(counts)} → {a.out}")

def cmd_tree(a):
    files = []
    for name in SESSION_FILES:
        fp = os.path.join(a.session, name)
        if os.path.isfile(fp):
            meta = _sha256_file(fp)
            files.append({"file": name, **meta})
    _write_text(a.out, json.dumps({"session": a.session, "files": files}, indent=2))
    print(f"[tree] {len(files)} files → {a.out}")

def cmd_signoff(a):
    out = build_signoff(a.session)
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[signoff] {a.session} → {a.out}")

# -------------------- main --------------------

def main(argv: Optional[list[str]] = None):
    ap = argparse.ArgumentParser(description="E-Validation tooling (Futures-only)")
    sub = ap.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('env-snapshot', help='Зняти env для E0')
    sp.add_argument('--out', required=True)
    sp.set_defaults(func=cmd_env_snapshot)

    sp = sub.add_parser('metrics-scrape', help='Скачати /metrics і пропарсити deny лічильники')
    sp.add_argument('--url', required=True)
    sp.add_argument('--out', required=True)
    sp.set_defaults(func=cmd_metrics_scrape)

    sp = sub.add_parser('lifecycle', help='Хронологія ордерів success/failed/denied')
    sp.add_argument('--session', required=True)
    sp.add_argument('--out', required=True)
    sp.set_defaults(func=cmd_lifecycle)

    sp = sub.add_parser('deny-counts', help='Порахувати reason_code у orders_denied.jsonl')
    sp.add_argument('--session', required=True)
    sp.add_argument('--out', required=True)
    sp.set_defaults(func=cmd_deny_counts)

    sp = sub.add_parser('tree', help='Перелік файлів сесії з SHA256/bytes/lines')
    sp.add_argument('--session', required=True)
    sp.add_argument('--out', required=True)
    sp.set_defaults(func=cmd_tree)

    sp = sub.add_parser('signoff', help='Згенерувати E10_signoff.json')
    sp.add_argument('--session', required=True)
    sp.add_argument('--out', required=True)
    sp.set_defaults(func=cmd_signoff)

    args = ap.parse_args(argv)
    args.func(args)

if __name__ == '__main__':  # pragma: no cover
    main()
