
import torch
import yaml
import argparse
import os
import time
import numpy as np

from models.dssm import DSSM

def check_latency(config, checkpoint_path, target_ms, num_runs=200, warmup_runs=50):
    """Перевірка часу інференсу (latency) моделі DSSM."""
    print("--- Checking DSSM Model Latency ---")
    # Для перевірки latency використовуємо CPU, оскільки це може бути 
    # більш реалістичним сценарієм для деяких deployment-ів, або 'cuda' якщо є GPU.
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    if not os.path.exists(checkpoint_path):
        print(f"[FAIL] Checkpoint not found at: {checkpoint_path}")
        return False

    # 1. Завантаження моделі
    try:
        cfg_model = config['model']
        model = DSSM(
            d_obs=cfg_model['d_obs'],
            d_latent=cfg_model['d_latent'],
            d_hidden=cfg_model['d_hidden']
        ).to(device)
        model.load_state_dict(torch.load(checkpoint_path, map_location=device))
        model.eval()
        print("[INFO] Model loaded successfully.")
    except Exception as e:
        print(f"[FAIL] Model loading failed: {e}")
        return False

    # 2. Підготовка вхідних даних
    # Для DSSM інференс - це один крок, тому seq_len=1
    dummy_input = torch.randn(1, 1, cfg_model['d_obs']).to(device)

    # 3. Прогрів моделі
    print(f"[INFO] Running {warmup_runs} warmup inferences...")
    for _ in range(warmup_runs):
        with torch.no_grad():
            _ = model(dummy_input)

    # 4. Вимірювання latency
    print(f"[INFO] Running {num_runs} timed inferences...")
    latencies = []
    for _ in range(num_runs):
        start_time = time.perf_counter()
        with torch.no_grad():
            # Симулюємо виклик, який буде в реальному часі
            _, z, _ = model(dummy_input)
            # У реальному часі ми б викликали `model.decode(z)`
            # Для чистоти виміру, ми вимірюємо повний forward pass
        end_time = time.perf_counter()
        latencies.append((end_time - start_time) * 1000) # в мілісекундах
    
    latencies = np.array(latencies)

    # 5. Аналіз результатів
    avg_latency = np.mean(latencies)
    p95_latency = np.percentile(latencies, 95)
    p99_latency = np.percentile(latencies, 99)
    max_latency = np.max(latencies)

    print("--- Latency Results ---")
    print(f"Average: {avg_latency:.2f} ms")
    print(f"p95:     {p95_latency:.2f} ms")
    print(f"p99:     {p99_latency:.2f} ms")
    print(f"Max:     {max_latency:.2f} ms")
    print("-----------------------")

    # 6. Перевірка відповідності SLO
    if p99_latency <= target_ms:
        print(f"[PASS] Latency SLO met (p99 {p99_latency:.2f}ms <= {target_ms}ms)")
        return True
    else:
        print(f"[FAIL] Latency SLO NOT met (p99 {p99_latency:.2f}ms > {target_ms}ms)")
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Check inference latency for a trained DSSM model.")
    parser.add_argument('--checkpoint', type=str, help="Path to the DSSM model checkpoint.")
    parser.add_argument('--target', type=int, default=100, help="Target latency in milliseconds (SLO).")
    args = parser.parse_args()

    config_path = 'configs/dssm.yaml'
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    checkpoint_path = args.checkpoint or config['training']['save_checkpoint_path']

    # Запускаємо перевірку лише для DSSM, оскільки це онлайн-модель
    success = check_latency(config, checkpoint_path, args.target)

    if not success:
        exit(1) # Повертаємо ненульовий код виходу для CI/CD
''