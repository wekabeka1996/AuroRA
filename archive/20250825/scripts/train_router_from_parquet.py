import argparse
import os

import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader

import sys
from pathlib import Path
# Ensure project root on sys.path when running from scripts/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.router import RegimeRouter, expected_calibration_error


def load_xy(path: str, target_col: str = 'log_returns', feature_drop: list = None):
    df = pd.read_parquet(path)
    df = df.copy()
    # Simple regime labels from quantiles of target (placeholder): bear/bull/neutral
    y_src = df[target_col].copy()
    q1 = y_src.quantile(0.33)
    q2 = y_src.quantile(0.66)
    y = (y_src > q2).astype(int)
    y[y_src < q1] = 2  # class 2 for negative returns
    y[y_src.between(q1, q2, inclusive='neither')] = 0

    # Features: drop raw OHLCV and target by default
    drop_cols = set(feature_drop or []) | {target_col}
    X = df.drop(columns=[c for c in df.columns if c in drop_cols])
    # Also drop raw OHLCV to keep engineered features only
    for c in ['open', 'high', 'low', 'close', 'volume']:
        if c in X.columns:
            X = X.drop(columns=[c])

    X = X.astype('float32')
    X = torch.tensor(X.values, dtype=torch.float32)
    y = torch.tensor(y.values, dtype=torch.long)
    return X, y


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', default='data/processed/train.parquet')
    parser.add_argument('--val', default='data/processed/val.parquet')
    parser.add_argument('--epochs', type=int, default=10)
    parser.add_argument('--batch_size', type=int, default=256)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--checkpoint', default='checkpoints/router_best.pt')
    args = parser.parse_args()

    Xtr, ytr = load_xy(args.train)
    Xval, yval = load_xy(args.val)

    d_input = Xtr.shape[1]
    num_regimes = int(ytr.max().item() + 1)

    model = RegimeRouter(d_input=d_input, num_regimes=num_regimes)
    opt = optim.Adam(model.parameters(), lr=args.lr)
    loss_fn = nn.CrossEntropyLoss()

    train_loader = DataLoader(TensorDataset(Xtr, ytr), batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(Xval, yval), batch_size=args.batch_size, shuffle=False)

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        for xb, yb in train_loader:
            opt.zero_grad()
            probs, logits = model(xb)
            loss = loss_fn(logits, yb)
            loss.backward()
            opt.step()
            total_loss += loss.item() * xb.size(0)
        total_loss /= len(train_loader.dataset)

        model.eval()
        with torch.no_grad():
            all_probs = []
            all_y = []
            for xb, yb in val_loader:
                probs, logits = model(xb)
                all_probs.append(probs)
                all_y.append(yb)
            probs_cat = torch.cat(all_probs)
            y_cat = torch.cat(all_y)
            ece = expected_calibration_error(probs_cat, y_cat).item()
        print(f"Epoch {epoch}/{args.epochs} train_loss={total_loss:.4f} val_ECE={ece:.4f}")

    # Temperature calibration
    model.calibrate_temperature(val_loader)

    os.makedirs(os.path.dirname(args.checkpoint), exist_ok=True)
    torch.save(model.state_dict(), args.checkpoint)
    print(f"Saved router checkpoint to {args.checkpoint}")


if __name__ == '__main__':
    main()
