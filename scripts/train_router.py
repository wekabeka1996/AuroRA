import argparse
import torch
import torch.nn as nn
import torch.optim as optim
from models.router import RegimeRouter


def synthetic_dataset(n=1000, d=20, num_classes=3):
    X = torch.randn(n, d)
    y = torch.randint(0, num_classes, (n,))
    return X, y


def expected_calibration_error(probs, labels, n_bins=15):
    bin_boundaries = torch.linspace(0, 1, n_bins + 1)
    bin_lowers = bin_boundaries[:-1]
    bin_uppers = bin_boundaries[1:]
    confidences, predictions = torch.max(probs, 1)
    accuracies = predictions.eq(labels)
    ece = torch.zeros(1, device=probs.device)
    for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
        in_bin = (confidences > bin_lower) & (confidences <= bin_upper)
        prop_in_bin = in_bin.float().mean()
        if prop_in_bin.item() > 0:
            accuracy_in_bin = accuracies[in_bin].float().mean()
            avg_confidence_in_bin = confidences[in_bin].mean()
            ece += torch.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin
    return ece.item()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--d_input', type=int, default=20)
    parser.add_argument('--num_regimes', type=int, default=3)
    parser.add_argument('--epochs', type=int, default=5)
    parser.add_argument('--checkpoint', type=str, default='checkpoints/router_best.pt')
    args = parser.parse_args()

    X, y = synthetic_dataset(n=2000, d=args.d_input, num_classes=args.num_regimes)
    model = RegimeRouter(d_input=args.d_input, num_regimes=args.num_regimes)
    opt = optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss()

    for epoch in range(args.epochs):
        model.train()
        opt.zero_grad()
        probs, logits = model(X)
        loss = loss_fn(logits, y)
        loss.backward()
        opt.step()
        with torch.no_grad():
            ece = expected_calibration_error(probs, y)
        print(f"Epoch {epoch+1}/{args.epochs} loss={loss.item():.4f} ECE={ece:.4f}")

    # save checkpoint
    import os
    os.makedirs('checkpoints', exist_ok=True)
    torch.save(model.state_dict(), args.checkpoint)
    print(f"Saved router to {args.checkpoint}")


if __name__ == '__main__':
    main()
