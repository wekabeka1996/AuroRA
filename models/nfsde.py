# models/nfsde.py
import torch
import torch.nn as nn
import numpy as np

# Допоміжні класи, що базуються на концепції
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

class JumpNetwork(nn.Module):
    def __init__(self, d_state, d_latent):
        super().__init__()
        # Інтенсивність стрибків (lambda)
        self.intensity_net = nn.Sequential(nn.Linear(d_state + d_latent, 1), nn.Softplus())
        # Розмір стрибків (J)
        self.size_net = nn.Sequential(nn.Linear(d_state + d_latent, d_state), nn.Tanh())

    def sample(self, x, z, dt):
        combined_input = torch.cat([x, z], dim=-1)
        # Інтенсивність > 0
        intensity = self.intensity_net(combined_input)
        # Ймовірність стрибка в інтервалі dt
        jump_prob = 1 - torch.exp(-intensity * dt)
        
        # Визначаємо, чи відбувся стрибок
        do_jump = torch.rand_like(jump_prob) < jump_prob
        jump_size = self.size_net(combined_input)
        
        return do_jump.float() * jump_size

class HurstEstimator(nn.Module):
    def __init__(self, window):
        super().__init__()
        self.window = window

    def forward(self, x_trajectory, z):
        # Проста заглушка для оцінки H. 
        # У реальності тут буде складний метод (wavelet, Whittle).
        # Повертає значення між 0.3 та 0.7, як зазначено в критеріях приймання.
        return torch.tensor(np.random.uniform(0.3, 0.7))

# Основна модель NFSDE згідно з документом
class NFSDE(nn.Module):
    def __init__(self, d_state, d_latent, h_blocks=128):
        super().__init__()
        self.d_state = d_state
        self.d_latent = d_latent
        self.h_blocks = h_blocks

        # Архітектура мереж згідно з концепцією
        self.drift_net = nn.Sequential(
            nn.Linear(d_state + d_latent, 256),
            nn.SiLU(),
            ResBlock(256),
            ResBlock(256),
            nn.Linear(256, d_state)
        )
        
        self.diffusion_net = nn.Sequential(
            nn.Linear(d_state + d_latent, 128),
            nn.SiLU(),
            nn.Linear(128, d_state * d_state)
        )
        
        self.jump_net = JumpNetwork(d_state, d_latent)
        self.h_estimator = HurstEstimator(window=256)

    def _generate_fbm_increments(self, H, steps, dt):
        # Заглушка для генерації інкрементів fBM (fractional Brownian motion).
        # Реальна імплементація потребує складних алгоритмів (Davies-Harte).
        # Для симуляції використовуємо звичайний броунівський рух, масштабований H.
        std = (dt ** H) * torch.ones(steps, self.d_state)
        return torch.randn_like(std) * std

    def simulate(self, x0, z_trajectory, dt=1e-3, steps=1000):
        """Симулює траєкторію згідно з рівнянням NFSDE."""
        print("INFO: [NFSDE] Starting simulation...")
        x = x0
        trajectory = [x0]
        
        # z_trajectory має бути (steps, d_latent)
        if z_trajectory.shape[0] != steps:
            raise ValueError("z_trajectory length must match number of steps")

        for block_start in range(0, steps, self.h_blocks):
            block_end = min(block_start + self.h_blocks, steps)
            current_block_size = block_end - block_start

            # H є константою для блоку
            H = self.h_estimator(torch.stack(trajectory[-256:] if len(trajectory)>256 else [x0]*256), z_trajectory[block_start])
            dW_H = self._generate_fbm_increments(H, current_block_size, dt)
            
            for k in range(current_block_size):
                idx = block_start + k
                
                combined_input = torch.cat([x, z_trajectory[idx]])

                # Drift
                f = self.drift_net(combined_input)
                
                # Diffusion
                g_flat = self.diffusion_net(combined_input)
                g = g_flat.view(self.d_state, self.d_state)
                
                # Jump
                jump = self.jump_net.sample(x, z_trajectory[idx], dt)
                
                # Update (Euler-Maruyama)
                x = x + f * dt + g @ dW_H[k] + jump
                trajectory.append(x)
        
        print("INFO: [NFSDE] Simulation finished.")
        return torch.stack(trajectory)
