
import torch
import torch.optim as optim
import torch.nn.functional as F
import yaml
import argparse
import os
import numpy as np
import pandas as pd

from models.nfsde import NFSDE
from data_pipeline.ingester import DataIngester
from data_pipeline.dataset import ParquetSequenceDataset

# --- Placeholder Functions (згідно з концепцією) ---
# У реальній системі тут будуть складні реалізації, що вимагають спец. бібліотек

def signature_transform(path_tensor):
    """
    ЗАГЛУШКА: Перетворення сигнатури.
    Реальна імплементація потребує бібліотек як `signatory` або `iisignature`.
    Повертає простий момент як замінник.
    """
    return torch.mean(path_tensor, dim=1)

def mmd_loss(x: torch.Tensor, y: torch.Tensor, kernel: str = 'rbf', bandwidth: float = 1.0) -> torch.Tensor:
    """
    Simple MMD^2 with RBF kernel for 2D inputs (batch, dim).
    """
    assert x.dim() == 2 and y.dim() == 2, "mmd_loss expects 2D tensors (batch, dim)"
    xx = torch.mm(x, x.t())  # (n, n)
    yy = torch.mm(y, y.t())  # (m, m)
    xy = torch.mm(x, y.t())  # (n, m)

    rx = xx.diag().unsqueeze(0).expand_as(xx)
    ry = yy.diag().unsqueeze(0).expand_as(yy)

    dxx = rx.t() + rx - 2.0 * xx
    dyy = ry.t() + ry - 2.0 * yy
    dxy = rx.t()[:, : xy.size(0)] + ry[:, : xy.size(1)] - 2.0 * xy  # align shapes

    if kernel == 'rbf':
        k_xx = torch.exp(-0.5 * dxx / bandwidth)
        k_yy = torch.exp(-0.5 * dyy / bandwidth)
        k_xy = torch.exp(-0.5 * dxy / bandwidth)
    else:
        raise ValueError("Unsupported kernel: %s" % kernel)

    mmd2 = k_xx.mean() + k_yy.mean() - 2.0 * k_xy.mean()
    return mmd2

def separation_loss(model: NFSDE):
    """
    ЗАГЛУШКА: Regularization loss (lambda_sep).
    Штрафує за складність моделі.
    """
    # L1 на інтенсивності стрибків + гладкість дифузії
    jump_norm = sum(p.abs().sum() for p in model.jump_net.parameters())
    diff_norm = sum(p.abs().sum() for p in model.diffusion_net.parameters())
    return 1e-5 * (jump_norm + diff_norm)

# --- Основний скрипт ---

def train(config, dataset_parquet: str = None, seq_len_override: int = None, batch_size_override: int = None):
    """Головна функція для тренування моделі вчителя."""
    
    print("--- Starting NFSDE Teacher Training ---")
    
    # 1. Налаштування
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    cfg_model = config['model']
    cfg_train = config['training']
    cfg_data = config['data']

    # 2. Завантаження даних
    print("Loading data...")
    if dataset_parquet:
        seq_len = seq_len_override or cfg_data['sequence_length']
        batch_size = batch_size_override or cfg_train['batch_size']
        ds = ParquetSequenceDataset(dataset_parquet, seq_len=seq_len, target_col='close')
        data_loader = torch.utils.data.DataLoader(ds, batch_size=batch_size, shuffle=True)
        effective_seq_len = seq_len
    else:
        ingester = DataIngester()
        raw_data = ingester.fetch_ohlcv(
            source=cfg_data['source'],
            symbol=cfg_data['symbol'],
            timeframe=cfg_data['timeframe'],
            start=cfg_data['start_date'],
            end=cfg_data['end_date']
        )
        # Використовуємо лише ціну закриття для простоти
        price_data = torch.tensor(raw_data['close'].values, dtype=torch.float32).to(device)
        # Створюємо батчі з послідовностей
        effective_seq_len = cfg_data['sequence_length']
        num_sequences = len(price_data) - effective_seq_len
        sequences = [price_data[i:i+effective_seq_len].unsqueeze(1) for i in range(num_sequences)]
        data_loader = torch.utils.data.DataLoader(sequences, batch_size=cfg_train['batch_size'], shuffle=True)

    # 3. Ініціалізація моделі та оптимізатора
    print("Initializing model...")
    model = NFSDE(
        d_state=1, # Лише ціна
        d_latent=cfg_model['d_latent'],
        h_blocks=cfg_model['h_blocks']
    ).to(device)
    
    optimizer = optim.Adam(model.parameters(), lr=cfg_train['learning_rate'])

    # 4. Тренувальний цикл
    print("Starting training loop...")
    for epoch in range(cfg_train['epochs']):
        total_loss = 0
        for i, real_paths in enumerate(data_loader):
            optimizer.zero_grad()
            
            batch_size = real_paths.shape[0]
            
            # Початкова точка для симуляції
            x0 = real_paths[:, 0, :]
            
            # Для сумісності з NFSDE.simulate (яка працює з 1 зразком за виклик)
            # симулюємо кожен елемент батчу окремо, з індивідуальною z-траєкторією.
            z_all = torch.randn(batch_size, effective_seq_len, cfg_model['d_latent'], device=device)
            sim_list = []
            for b in range(batch_size):
                sim = model.simulate(
                    x0=x0[b].view(-1),
                    z_trajectory=z_all[b],
                    steps=effective_seq_len,
                    dt=config['simulation']['dt']
                )  # shape: (steps+1, d_state)
                # Вирівнюємо довжину з real_paths (seq_len): відкидаємо початкову точку x0
                sim = sim[1:]  # (seq_len, d_state)
                sim_list.append(sim)
            generated_paths = torch.stack(sim_list, dim=0)  # (batch, seq_len, d_state)
            
            # --- Обчислення Loss-функції (J_T з концепції) ---
            
            # 1. -log p(X) - Негативний лог-лайкліхуд
            #    Апроксимуємо через MSE між реальними та генерованими даними
            nll_loss = F.mse_loss(generated_paths, real_paths)
            
            # 2. MMD Loss на сигнатурах
            real_signatures = signature_transform(real_paths)
            gen_signatures = signature_transform(generated_paths)
            sig_mmd_loss = mmd_loss(real_signatures, gen_signatures)
            
            # 3. Separation Loss (регуляризація)
            sep_loss = separation_loss(model)
            
            # Загальна loss-функція
            loss = nll_loss + cfg_train['lambda_sig'] * sig_mmd_loss + cfg_train['lambda_sep'] * sep_loss
            
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg_train['clip_grad_norm'])
            optimizer.step()
            
            total_loss += loss.item()
            
            if (i + 1) % 10 == 0:
                print(f"Epoch [{epoch+1}/{cfg_train['epochs']}], Step [{i+1}/{len(data_loader)}], Loss: {loss.item():.4f} (NLL: {nll_loss.item():.4f}, MMD: {sig_mmd_loss.item():.4f})")

        avg_loss = total_loss / len(data_loader)
        print(f"--- Epoch {epoch+1} Summary ---")
        print(f"Average Loss: {avg_loss:.4f}")
        print("-------------------------")

    # 5. Збереження моделі
    print("Training finished. Saving model...")
    os.makedirs(os.path.dirname(cfg_train['save_checkpoint_path']), exist_ok=True)
    torch.save(model.state_dict(), cfg_train['save_checkpoint_path'])
    print(f"Model saved to {cfg_train['save_checkpoint_path']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Train NFSDE Teacher Model")
    parser.add_argument('--config', type=str, required=True, help="Path to the config file (e.g., configs/nfsde.yaml)")
    parser.add_argument('--dataset_parquet', type=str, default=None, help="Optional Parquet file to train from prebuilt sequences source")
    parser.add_argument('--seq_len', type=int, default=None, help="Override sequence length when using parquet dataset")
    parser.add_argument('--batch_size', type=int, default=None, help="Override batch size when using parquet dataset")
    args = parser.parse_args()

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    train(
        config,
        dataset_parquet=args.dataset_parquet,
        seq_len_override=args.seq_len,
        batch_size_override=args.batch_size,
    )
