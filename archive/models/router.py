# models/router.py
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

# Використовуємо той самий ResBlock
class ResBlock(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.main = nn.Sequential(
            nn.Linear(channels, channels),
            nn.SiLU(),
            nn.Linear(channels, channels)
        )
        self.norm = nn.LayerNorm(channels)

    def forward(self, x):
        return self.norm(x + self.main(x))

# Функція для розрахунку ECE (Expected Calibration Error)
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
            
    return ece

# Модель RegimeRouter згідно з документом
class RegimeRouter(nn.Module):
    def __init__(self, d_input, num_regimes=3):
        super().__init__()
        # Архітектура згідно з концепцією
        self.backbone = nn.Sequential(
            nn.Linear(d_input, 256),
            nn.LayerNorm(256),
            nn.SiLU(),
            ResBlock(256),
            ResBlock(256),
            nn.Dropout(0.2)
        )
        
        self.classifier = nn.Linear(256, num_regimes)
        # Температура для калібрування
        self.temperature = nn.Parameter(torch.ones(1))
        
    def forward(self, x):
        features = self.backbone(x)
        # Ділимо логіти на температуру перед софтмаксом
        logits = self.classifier(features) / self.temperature
        probs = F.softmax(logits, dim=-1)
        return probs, logits
    
    def calibrate_temperature(self, val_loader):
        """Калібрує температуру для мінімізації ECE на валідаційному сеті."""
        print("INFO: [RegimeRouter] Starting temperature calibration...")
        self.eval()
        logits_list = []
        labels_list = []
        
        # Збираємо логіти та мітки з валідаційного датасету
        with torch.no_grad():
            for x, y in val_loader:
                # x, y - це дані та реальні мітки режимів
                features = self.backbone(x)
                logits = self.classifier(features) # Не масштабовані
                logits_list.append(logits)
                labels_list.append(y)
        
        all_logits = torch.cat(logits_list)
        all_labels = torch.cat(labels_list)

        # Початкове значення ECE
        initial_ece = expected_calibration_error(F.softmax(all_logits / self.temperature, dim=1), all_labels)
        print(f"Initial ECE: {initial_ece.item():.4f}")

        # Оптимізуємо параметр температури
        optimizer = optim.LBFGS([self.temperature], lr=0.01, max_iter=50)
        
        def eval_ece():
            optimizer.zero_grad()
            loss = expected_calibration_error(F.softmax(all_logits / self.temperature, dim=1), all_labels)
            loss.backward()
            return loss
        
        optimizer.step(eval_ece)

        final_ece = expected_calibration_error(F.softmax(all_logits / self.temperature, dim=1), all_labels)
        print(f"Optimal temperature: {self.temperature.item():.3f}")
        print(f"Final ECE: {final_ece.item():.4f}")
        print("INFO: [RegimeRouter] Calibration finished.")
        return self.temperature.item()
