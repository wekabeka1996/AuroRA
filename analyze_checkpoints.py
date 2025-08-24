import os, json, math, statistics, torch

CKPT_DIR = 'checkpoints'
RESULT = []

FLOAT_TENSOR_TYPES = (torch.FloatTensor, torch.DoubleTensor, torch.HalfTensor, torch.BFloat16Tensor)

for fname in sorted(os.listdir(CKPT_DIR)):
    path = os.path.join(CKPT_DIR, fname)
    if not os.path.isfile(path):
        continue
    entry = {"file": fname}
    try:
        obj = torch.load(path, map_location='cpu')
    except Exception as e:
        entry['error'] = str(e)
        RESULT.append(entry)
        continue

    # Detect state dict
    if isinstance(obj, dict) and 'state_dict' in obj:
        sd = obj['state_dict']
    elif isinstance(obj, dict) and 'model_state_dict' in obj:
        sd = obj['model_state_dict']
    elif isinstance(obj, dict) and all(isinstance(v, torch.Tensor) for v in obj.values()):
        sd = obj
    else:
        # fallback: collect tensor-like
        sd = {k: v for k, v in obj.items() if isinstance(v, torch.Tensor)} if isinstance(obj, dict) else {}

    param_cnt = sum(int(v.numel()) for v in sd.values())
    float_params = [v for v in sd.values() if isinstance(v, torch.Tensor) and v.is_floating_point()]
    sample_items = list(sd.items())[:6]

    # Basic stats over all float params concatenated (sampled to avoid memory blow-up)
    # We'll just take up to first N elements from each tensor for summary
    stats_values = []
    for t in float_params:
        # take up to 2048 values per tensor
        flat = t.view(-1)
        take = flat[: min(2048, flat.numel())].tolist()
        stats_values.extend(take)
    if stats_values:
        mean_all = statistics.fmean(stats_values)
        std_all = statistics.pstdev(stats_values)
        min_all = min(stats_values)
        max_all = max(stats_values)
    else:
        mean_all = std_all = min_all = max_all = None

    entry.update({
        'size_mb': round(os.path.getsize(path)/1024/1024, 2),
        'params_m': round(param_cnt/1e6, 3),
        'keys_total': len(sd),
        'sample_layers': {k: tuple(v.shape) for k, v in sample_items},
        'weights_mean': mean_all,
        'weights_std': std_all,
        'weights_min': min_all,
        'weights_max': max_all,
    })
    RESULT.append(entry)

print(json.dumps(RESULT, indent=2))
