from __future__ import annotations
"""State snapshot serialization for AdaptiveICP + Acceptance.

Versioned, tolerant JSON payloads (Batch-009).
"""
from typing import Any, Dict, Tuple
import json, os, time
from pathlib import Path

SNAPSHOT_VERSION = 1

# ---------------- ICP ---------------- #

def make_icp_state(icp) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        'alpha': getattr(icp, 'alpha', None),
        'alpha_target': getattr(icp, 'alpha_target', None),
        'coverage_ema': getattr(icp, 'coverage_ema', None),
        'n_seen': len(getattr(icp, 'scores', [])) if hasattr(icp, 'scores') else None,
    'inflation_factor': getattr(icp, '_inflation_factor', None),
    'transition_cooldown': getattr(icp, '_transition_cooldown', None),
    }
    p2 = getattr(icp, '_p2', None)
    if p2 is not None:
        try:
            payload['p2'] = p2.get_state()
        except Exception:
            pass
    # Always persist scores deque (used for fallback quantiles & P2 refresh recalculation)
    try:
        scores = list(getattr(icp, 'scores', []))
        payload['deque_scores'] = {'data': scores, 'maxlen': getattr(icp, 'window', len(scores) or None)}
    except Exception:
        pass
    return payload

def load_icp_state(icp, payload: Dict[str, Any]) -> None:
    if not payload:
        return
    # scalar restore (alpha_target kept authoritative from code unless matching)
    alpha_target_snapshot = payload.get('alpha_target')
    try:
        code_alpha_t = getattr(icp, 'alpha_target', None)
        if (alpha_target_snapshot is not None and code_alpha_t is not None
                and abs(float(alpha_target_snapshot) - float(code_alpha_t)) > 1e-9):
            print(f"WARNING [snapshot] alpha_target mismatch: snapshot={alpha_target_snapshot} , code={code_alpha_t} -> keeping code value")
    except Exception:
        pass
    for key in ('alpha','coverage_ema'):
        if key in payload and payload[key] is not None:
            try:
                setattr(icp, key, float(payload[key]))
            except Exception:
                pass
    # internal adaptive fields
    if 'inflation_factor' in payload:
        try:
            icp._inflation_factor = float(payload['inflation_factor'])
        except Exception:
            pass
    if 'transition_cooldown' in payload:
        try:
            icp._transition_cooldown = int(payload['transition_cooldown'])
        except Exception:
            pass
    # scores restore
    try:
        if 'p2' in payload and getattr(icp, '_p2', None) is not None:
            icp._p2.set_state(payload['p2'])
        if 'deque_scores' in payload:
            ds = payload['deque_scores'] or {}
            data = ds.get('data', [])
            maxlen = ds.get('maxlen', getattr(icp, 'window', len(data)))
            from collections import deque
            icp.scores = deque(data, maxlen=maxlen)
    except Exception:
        pass

# ---------------- Acceptance ---------------- #

def make_acceptance_state(acc) -> Dict[str, Any]:
    st = acc.state if hasattr(acc, 'state') else None
    if st is None:
        return {}
    # Determine current state (hysteresis current if exists else last decision approximation)
    current_state = 'PASS'
    hg = getattr(acc, 'hysteresis_gate', None)
    if hg is not None:
        current_state = getattr(hg, 'current', current_state)
    payload: Dict[str, Any] = {
        'current_state': current_state,
        'surprisal_window': list(st.surprisal_window),
        'latency_window': list(st.latency_window),
        'coverage_window': list(st.coverage_window),
        'kappa_window': list(st.kappa_window),
        'dwell': {},  # populated if hysteresis has counters (not currently exposed)
        'p95_surprisal': acc._p95('surprisal', st.surprisal_window) if hasattr(acc, '_p95') else None,
        'latency_p95': acc._p95('latency', st.latency_window) if hasattr(acc, '_p95') else None,
    }
    # attempt dwell counters
    if hg is not None:
        ctrs = getattr(hg, '_counters', None)
        if isinstance(ctrs, dict):
            payload['dwell'] = {k: int(v) for k,v in ctrs.items()}
    return payload

def load_acceptance_state(acc, payload: Dict[str, Any]) -> None:
    if not payload:
        return
    st = getattr(acc, 'state', None)
    if st is None:
        return
    # restore windows preserving maxlen
    from collections import deque
    try:
        if 'surprisal_window' in payload:
            st.surprisal_window = deque(payload['surprisal_window'], maxlen=st.surprisal_window.maxlen)
        if 'latency_window' in payload:
            st.latency_window = deque(payload['latency_window'], maxlen=st.latency_window.maxlen)
        if 'coverage_window' in payload:
            st.coverage_window = deque(payload['coverage_window'], maxlen=st.coverage_window.maxlen)
        if 'kappa_window' in payload:
            st.kappa_window = deque(payload['kappa_window'], maxlen=st.kappa_window.maxlen)
    except Exception:
        pass
    # current state
    hg = getattr(acc, 'hysteresis_gate', None)
    if hg is not None and 'current_state' in payload:
        try:
            hg.current = payload['current_state']
        except Exception:
            pass
    # dwell counters (best effort)
    if hg is not None and 'dwell' in payload:
        ctrs = getattr(hg, '_counters', None)
        src = payload.get('dwell') or {}
        if isinstance(ctrs, dict):
            for k,v in src.items():
                if k in ctrs:
                    try:
                        ctrs[k] = int(v)
                    except Exception:
                        pass

# ---------------- Snapshot IO ---------------- #

def save_snapshot(path: str, icp_payload: Dict, acc_payload: Dict) -> None:
    out = {
        'version': SNAPSHOT_VERSION,
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'icp': icp_payload,
        'acceptance': acc_payload,
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(out, f, indent=2)
    os.replace(tmp, p)


def load_snapshot(path: str) -> Tuple[Dict, Dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    data = json.loads(p.read_text(encoding='utf-8'))
    # version tolerance (future migrations)
    icp = data.get('icp', {}) if isinstance(data, dict) else {}
    acc = data.get('acceptance', {}) if isinstance(data, dict) else {}
    return icp, acc

__all__ = [
    'make_icp_state','load_icp_state','make_acceptance_state','load_acceptance_state','save_snapshot','load_snapshot'
]
