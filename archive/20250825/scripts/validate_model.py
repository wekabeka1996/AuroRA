
import torch
import yaml
import argparse
import os

from models.dssm import DSSM
from models.nfsde import NFSDE

def validate_dssm(config, checkpoint_path):
    """Валідація моделі DSSM."""
    print("--- Validating DSSM Model ---")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    # 1. Перевірка існування чекпоінта
    if not os.path.exists(checkpoint_path):
        print(f"[FAIL] Checkpoint not found at: {checkpoint_path}")
        return False
    print(f"[PASS] Checkpoint found.")

    # 2. Завантаження моделі
    try:
        cfg_model = config['model']
        model = DSSM(
            d_obs=cfg_model['d_obs'],
            d_latent=cfg_model['d_latent'],
            d_hidden=cfg_model['d_hidden']
        ).to(device)
        model.load_state_dict(torch.load(checkpoint_path, map_location=device))
        model.eval()
        print("[PASS] Model loaded successfully.")
    except Exception as e:
        print(f"[FAIL] Model loading failed: {e}")
        return False

    # 3. Перевірка інференсу (forward pass)
    try:
        batch_size = 4
        seq_len = config['data']['sequence_length']
        d_obs = cfg_model['d_obs']
        dummy_input = torch.randn(batch_size, seq_len, d_obs).to(device)
        
        loss, z, _ = model(dummy_input)
        print("[PASS] Inference check successful.")
        
        # 4. Перевірка форми виходу
        assert z.shape == (batch_size, seq_len, cfg_model['d_latent']), "Incorrect output shape for z"
        print("[PASS] Output shape validation successful.")

        # 5. Перевірка розрахунку loss
        assert loss.item() > 0, "Loss must be a positive value"
        print(f"[PASS] Loss calculation check successful (Loss: {loss.item()}).")

    except Exception as e:
        print(f"[FAIL] Inference or shape validation failed: {e}")
        return False
        
    print("--- DSSM Validation PASSED ---")
    return True

def validate_nfsde(config, checkpoint_path):
    """Валідація моделі NFSDE."""
    # Аналогічні перевірки для NFSDE
    print("--- Validating NFSDE Model ---")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if not os.path.exists(checkpoint_path):
        print(f"[FAIL] Checkpoint not found at: {checkpoint_path}")
        return False
    print(f"[PASS] Checkpoint found.")

    try:
        cfg_model = config['model']
        model = NFSDE(
            d_state=1, # Hardcoded for now as in training script
            d_latent=cfg_model['d_latent']
        ).to(device)
        model.load_state_dict(torch.load(checkpoint_path, map_location=device))
        model.eval()
        print("[PASS] Model loaded successfully.")
    except Exception as e:
        print(f"[FAIL] Model loading failed: {e}")
        return False

    try:
        batch_size = 2
        seq_len = config['data']['sequence_length']
        d_latent = cfg_model['d_latent']

        x0 = torch.randn(batch_size, 1).to(device)
        z_trajectory = torch.randn(batch_size, seq_len, d_latent).to(device)
        
        trajectory = model.simulate(x0, z_trajectory, steps=seq_len)
        print("[PASS] Simulation check successful.")

        assert trajectory.shape == (batch_size, seq_len + 1, 1), "Incorrect output shape"
        print("[PASS] Output shape validation successful.")

    except Exception as e:
        print(f"[FAIL] Simulation or shape validation failed: {e}")
        return False

    print("--- NFSDE Validation PASSED ---")
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Validate a trained model checkpoint.")
    parser.add_argument('--model', type=str, required=True, choices=['dssm', 'nfsde'], help="Model to validate.")
    parser.add_argument('--checkpoint', type=str, help="Path to the model checkpoint. Defaults to path from config.")
    args = parser.parse_args()

    if args.model == 'dssm':
        config_path = 'configs/dssm.yaml'
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        checkpoint_path = args.checkpoint or config['training']['save_checkpoint_path']
        success = validate_dssm(config, checkpoint_path)
    elif args.model == 'nfsde':
        config_path = 'configs/nfsde.yaml'
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        checkpoint_path = args.checkpoint or config['training']['save_checkpoint_path']
        success = validate_nfsde(config, checkpoint_path)
    else:
        print(f"Unknown model type: {args.model}")
        success = False

    if not success:
        exit(1) # Повертаємо ненульовий код виходу для CI/CD
''