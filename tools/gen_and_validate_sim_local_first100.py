from __future__ import annotations

import json
import os
import re
import runpy

# Try to import generator as module; fall back to executing the script directly via runpy
try:
    from tools.gen_sim_local_first100 import main as gen_main  # type: ignore
except Exception:
    gen_main = None


def iso_z_re(s: str) -> bool:
    # simple ISO-8601Z check: YYYY-MM-DDTHH:MM:SSZ (allow fractional seconds)
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$", s))


def main():
    os.makedirs('logs', exist_ok=True)
    # generate upstream aurora_events.jsonl
    src = 'logs/aurora_events.jsonl'
    # remove any previous file so validation inspects only newly generated events
    try:
        if os.path.exists(src):
            os.remove(src)
    except Exception:
        pass

    if gen_main is not None:
        gen_main()
    else:
        # Execute the generator script in tools/ directly
        runpy.run_path('tools/gen_sim_local_first100.py', run_name='__main__')
    # src already defined above after generation
    out = 'logs/sim_local_first100.jsonl'
    val = 'logs/sim_local_first100_validate.txt'
    written = 0
    first_seed_present = False
    # Fields we want to ensure are present either at top-level or inside details
    req_fields = {'order_id', 'side', 'px', 'qty', 'status', 'reason', 'latency_ms_action', 'latency_ms_fill', 'fill_ratio', 'ttl_ms'}

    with open(out, 'w', encoding='utf8') as fout, open(val, 'w', encoding='utf8') as fv:
        with open(src, encoding='utf8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except Exception as e:
                    fv.write(f'BAD_JSON: {e} -- {ln[:200]}\n')
                    continue
                # only keep ORDER_STATUS(sim) records
                if rec.get('event_code') != 'ORDER.STATUS(SIM)':
                    continue
                details = rec.get('details', {})
                # ts can be in details or at top-level (ts_ns exists at top-level). Prefer details 'ts'.
                ts = details.get('ts') or details.get('timestamp') or None
                if not ts:
                    # try to synthesize an ISO-like ts from top-level ns if available
                    ts_ns = rec.get('ts_ns')
                    if ts_ns:
                        try:
                            # convert ns to seconds and format roughly (no fractional seconds fine)
                            import datetime

                            ts = datetime.datetime.utcfromtimestamp(int(ts_ns) / 1_000_000_000).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'
                        except Exception:
                            ts = None
                if not ts or not iso_z_re(ts):
                    fv.write(f'BAD_TS: {ts} in record {written}\n')

                # Build a combined view of fields: keys present at top-level or in details
                combined_keys = set(details.keys()) | set(k for k in ('order_id', 'side', 'px', 'qty', 'status', 'reason', 'latency_ms_action', 'latency_ms_fill', 'fill_ratio', 'ttl_ms') if rec.get(k) is not None)
                # Also accept 'oid' as equivalent to 'order_id'
                if rec.get('oid') is not None:
                    combined_keys.add('order_id')
                # If some required fields are present at top-level (e.g., 'side', 'qty'), include them
                for fld in ('side', 'qty', 'px', 'status', 'reason', 'latency_ms_action', 'latency_ms_fill', 'fill_ratio', 'ttl_ms'):
                    if rec.get(fld) is not None:
                        combined_keys.add(fld)

                missing = req_fields - combined_keys
                # rng_seed may be present in details or top-level under 'rng_seed'
                seed_present = ('rng_seed' in details) or (rec.get('rng_seed') is not None) or ('rng_seed' in rec)
                if written == 0 and seed_present:
                    first_seed_present = True

                if missing:
                    # permit certain missing maker/taker fields; still record
                    fv.write(f'MISSING_FIELDS: {missing} in record {written}\n')

                # Write out a normalized details object that includes top-level fallbacks for downstream checks
                norm = dict(details)
                # populate common fallbacks
                norm.setdefault('order_id', details.get('order_id') or rec.get('oid') or rec.get('order_id'))
                norm.setdefault('side', details.get('side') or rec.get('side'))
                norm.setdefault('px', details.get('px') or details.get('price') or rec.get('price'))
                norm.setdefault('qty', details.get('qty') or rec.get('qty'))
                norm.setdefault('status', details.get('status') or rec.get('status'))
                norm.setdefault('reason', details.get('reason') or rec.get('reason'))
                norm.setdefault('latency_ms_action', details.get('latency_ms_action') or rec.get('latency_ms_action'))
                norm.setdefault('latency_ms_fill', details.get('latency_ms_fill') or rec.get('latency_ms_fill'))
                norm.setdefault('fill_ratio', details.get('fill_ratio') or rec.get('fill_ratio'))
                norm.setdefault('ttl_ms', details.get('ttl_ms') or rec.get('ttl_ms'))

                fout.write(json.dumps(norm, ensure_ascii=False) + '\n')
                written += 1
                if written >= 100:
                    break
        # summary
        if written < 100:
            fv.write(f'WRITTEN_LESS_THAN_100: {written}\n')
        if not first_seed_present:
            fv.write('MISSING_FIRST_RNG_SEED\n')
        if written >= 100 and fv.tell() == 0:
            fv.write('OK\n')

    print(f'Generated {out} and validation {val}')


if __name__ == '__main__':
    main()
