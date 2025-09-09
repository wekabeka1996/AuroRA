# Tools

Small utilities used for canary preflight and offline validation.

1) Seed synthetic flow

  python tools/seed_synthetic_flow.py --out logs/synth.jsonl --seed 1 --scenarios maker,taker,low_pfill,size_zero,sla_deny --n 1

2) Validate canary logs

  python tools/validate_canary_logs.py \
    --path logs/synth.jsonl \
    --window-mins 5 \
    --p95-latency-ms-max 500 \
    --deny-share-max 0.60 \
    --low-pfill-share-max 0.50 \
    --net-after-tca-median-min 0 \
    --xai-missing-rate-max 0.01 \
    --pfill-median-min 0.40 \
    --pfill-median-max 0.80 \
    --corrupt-rate-max 0.01

KPI units:
- latency: milliseconds (ms)
- edge/net_after_tca: basis points (bps) integer
- p_fill: fraction in [0..1]
- shares/rates: fraction in [0..1]

Exit codes:
- 0 — pass (all thresholds satisfied)
- 2 — fail (one or more thresholds violated)
