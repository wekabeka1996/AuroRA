
import torch
import torch.optim as optim
import torch.nn.functional as F
import yaml
import argparse
import os
import numpy as np
import pandas as pd

from models.nfsde import NFSDE
from models.dssm import DSSM
from data_pipeline.ingester import DataIngester
from data_pipeline.dataset import ParquetSequenceDataset, FeaturesSequenceDataset

# --- Placeholder Functions (аналогічно до train_teacher) ---

def signature_transform(path_tensor):
    return torch.mean(path_tensor, dim=1)

def mmd_loss(x: torch.Tensor, y: torch.Tensor, bandwidth: float = 1.0) -> torch.Tensor:
    xx, yy, xy = torch.mm(x, x.t()), torch.mm(y, y.t()), torch.mm(x, y.t())
    rx = xx.diag().unsqueeze(0).expand_as(xx)
    ry = yy.diag().unsqueeze(0).expand_as(yy)
    dxx = rx.t() + rx - 2.0 * xx
    dyy = ry.t() + ry - 2.0 * yy
    dxy = rx.t()[:, : xy.size(0)] + ry[:, : xy.size(1)] - 2.0 * xy
    XX = torch.exp(-0.5 * dxx / bandwidth)
    YY = torch.exp(-0.5 * dyy / bandwidth)
    XY = torch.exp(-0.5 * dxy / bandwidth)
    return (XX.mean() + YY.mean() - 2.0 * XY.mean())

def tail_matching_loss(student_outputs, teacher_outputs):
    """
    ЗАГЛУШКА: Втрати на узгодження хвостів розподілів.
    Штрафує за розбіжність у екстремальних значеннях (квантилях).
    """
    # Порівнюємо 95% квантилі як проксі
    q_student = torch.quantile(student_outputs, 0.95)
    q_teacher = torch.quantile(teacher_outputs, 0.95)
    return F.mse_loss(q_student, q_teacher)

# --- Основний скрипт ---

def train(config, dataset_parquet: str = None, seq_len_override: int = None, batch_size_override: int = None):
    """Головна функція для тренування моделі студента."""
    print("--- Starting DSSM Student Training (Distillation) ---")

    # 1. Налаштування
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    cfg_model = config['model']
    cfg_train = config['training']
    cfg_data = config['data']
    cfg_teacher = config['teacher']

    # 2. Завантаження даних та фіч
    print("Loading and processing data...")
    if dataset_parquet:
        seq_len = seq_len_override or cfg_data['sequence_length']
        batch_size = batch_size_override or cfg_train['batch_size']
        # Для студента используем engineered features из processed parquet
        ds = FeaturesSequenceDataset(dataset_parquet, seq_len=seq_len)
        data_loader = torch.utils.data.DataLoader(ds, batch_size=batch_size, shuffle=True)
        feature_data = None
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
        feature_data = ingester.calculate_features(raw_data)
        effective_seq_len = cfg_data['sequence_length']
        sequences = [torch.tensor(feature_data.iloc[i:i+effective_seq_len].values, dtype=torch.float32) 
                     for i in range(len(feature_data) - effective_seq_len)]
        data_loader = torch.utils.data.DataLoader(sequences, batch_size=cfg_train['batch_size'], shuffle=True)

    # 3. Ініціалізація моделей
    print("Initializing models...")
    # Завантажуємо навченого вчителя
    teacher_model = NFSDE(
        d_state=cfg_teacher['d_state'],
        d_latent=cfg_teacher['d_latent']
    ).to(device)
    teacher_model.load_state_dict(torch.load(cfg_teacher['checkpoint_path'], map_location=device))
    teacher_model.eval()
    print(f"Teacher model loaded from {cfg_teacher['checkpoint_path']}")

    # Ініціалізуємо студента
    student_model = DSSM(
        d_obs=cfg_model['d_obs'],
        d_latent=cfg_model['d_latent'],
        d_hidden=cfg_model['d_hidden']
    ).to(device)
    
    optimizer = optim.Adam(student_model.parameters(), lr=cfg_train['learning_rate'])

    # 4. Тренувальний цикл (дистиляція)
    print("Starting training loop...")
    for epoch in range(cfg_train['epochs']):
        total_loss = 0
        for i, real_features_batch in enumerate(data_loader):
            optimizer.zero_grad()
            
            real_features_batch = real_features_batch.to(device)
            batch_size = real_features_batch.shape[0]
            seq_len = real_features_batch.shape[1]

            # --- Дистиляція: отримуємо таргет від вчителя ---
            with torch.no_grad():
                # Використовуємо реальні дані (ціну) як основу для симуляції вчителя
                # Беремо 'close' price, яка є однією з фіч
                if feature_data is not None:
                    close_price_idx = list(feature_data.columns).index('close')
                    x0 = real_features_batch[:, 0, close_price_idx].unsqueeze(1)
                else:
                    # Если тренируемся с ParquetSequenceDataset (price-only windows), первый канал — close
                    x0 = real_features_batch[:, 0, 0].unsqueeze(1)
                
                # Генеруємо латентну траєкторію для вчителя
                teacher_z_trajectory = torch.randn(seq_len, cfg_teacher['d_latent'], device=device).unsqueeze(0).repeat(batch_size, 1, 1)
                
                # Симулюємо траєкторії та отримуємо "ідеальні" латентні змінні від вчителя
                # У повній реалізації, z вчителя буде отримано з його власного енкодера
                # Тут ми використовуємо згенеровану траєкторію як проксі
                teacher_z_target = teacher_z_trajectory

            # --- Навчання студента ---
            # Втрати студента обчислюються всередині моделі DSSM
            # `teacher_z_target` використовується для KL-дивергенції у латентному просторі
            elbo_loss, student_z, losses = student_model(real_features_batch, teacher_z=teacher_z_target, lambda_kd=cfg_train['lambda_kd'])
            
            # --- Обчислення додаткових втрат згідно з концепцією (розділ 3.2) ---
            # Тут ми додаємо інші компоненти, що не увійшли в базовий ELBO
            
            # MMD Loss (заглушка)
            # sig_mmd_loss = mmd_loss(signature_transform(student_z), signature_transform(teacher_z_target))
            
            # Tail-matching loss (заглушка)
            # tail_loss = tail_matching_loss(student_z, teacher_z_target)
            
            # Повна loss-функція
            # loss = elbo_loss + cfg_train['lambda_sig'] * sig_mmd_loss + cfg_train['lambda_tail'] * tail_loss
            loss = elbo_loss # Наразі використовуємо лише ELBO + KD loss з моделі

            loss.backward()
            torch.nn.utils.clip_grad_norm_(student_model.parameters(), cfg_train['clip_grad_norm'])
            optimizer.step()
            
            total_loss += loss.item()
            
            if (i + 1) % 10 == 0:
                print(f"Epoch [{epoch+1}/{cfg_train['epochs']}], Step [{i+1}/{len(data_loader)}], Loss: {loss.item():.4f} (ELBO: {losses['elbo'].item():.4f}, Distill: {losses.get('distill', torch.tensor(0)).item():.4f})")

        avg_loss = total_loss / len(data_loader)
        print(f"--- Epoch {epoch+1} Summary ---")
        print(f"Average Loss: {avg_loss:.4f}")
        print("-------------------------")

    # 5. Збереження моделі
    print("Training finished. Saving model...")
    os.makedirs(os.path.dirname(cfg_train['save_checkpoint_path']), exist_ok=True)
    torch.save(student_model.state_dict(), cfg_train['save_checkpoint_path'])
    print(f"Model saved to {cfg_train['save_checkpoint_path']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Train DSSM Student Model")
    parser.add_argument('--config', type=str, required=True, help="Path to the config file (e.g., configs/dssm.yaml)")
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
''