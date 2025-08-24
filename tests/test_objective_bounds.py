from living_latent.core.metrics_io import derive_calib_metrics, compute_objective_v_b008_v1

def test_obj_in_range_and_uses_clips():
    acc = dict(PASS_share=0.8, DERISK_share=0.1, BLOCK_share=0.1,
               violations=5, surprisal_p95_pre=0.5, surprisal_p95_post=0.1,
               latency_p95_ms=350)
    m = derive_calib_metrics(acc)
    obj = compute_objective_v_b008_v1(m)
    assert -1.0 <= obj <= 1.0
    assert m['violations'] <= 1.0
    assert m['dS_norm'] <= 1.0
    assert m['lat_norm'] <= 1.0
