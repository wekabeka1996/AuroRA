# models/dssm.py
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Normal, StudentT, kl_divergence

# Використовуємо той самий ResBlock, що і в NFSDE
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

# Модель DSSM згідно з документом
class DSSM(nn.Module):
    def __init__(self, d_obs, d_latent, d_hidden=512):
        super().__init__()
        self.d_obs = d_obs
        self.d_latent = d_latent

        # Encoder (q_psi)
        # Використовує LSTM згідно з документом
        self.encoder = nn.LSTM(
            d_obs, d_hidden, 
            num_layers=3, 
            dropout=0.1,
            batch_first=True
        )
        
        self.mu_net = nn.Linear(d_hidden, d_latent)
        self.logvar_net = nn.Linear(d_hidden, d_latent)
        
        # Prior (p_phi)
        # Використовує GRUCell для авторегресійного пріора
        self.prior_net = nn.GRUCell(d_latent, d_latent)
        
        # Decoder (p_theta)
        # Використовує Student-t розподіл для емісії, як зазначено в документі
        self.decoder = nn.Sequential(
            nn.Linear(d_latent, d_hidden),
            nn.SiLU(),
            ResBlock(d_hidden),
            nn.Linear(d_hidden, d_obs * 3)  # mean, scale, df for Student-t
        )
        # Streaming state placeholders (ініціалізація стрімінгових станів)
        self._enc_state = None  # (h, c) for LSTM
        self._prior_state = None  # hidden state for GRUCell

    def _get_posterior_dist(self, x):
        # Пропускаємо дані через енкодер для отримання параметрів q(z|x)
        h, _ = self.encoder(x)
        mu_q = self.mu_net(h)
        logvar_q = self.logvar_net(h)
        std_q = torch.exp(0.5 * logvar_q)
        return Normal(mu_q, std_q)

    def forward(self, x, teacher_z=None, lambda_kd=0.1):
        """Повний forward pass для обчислення ELBO та опціональної дистиляції."""
        # x має розмір (batch, sequence_len, d_obs)
        
        # 1. Отримуємо апостеріорний розподіл q(z|x)
        posterior_dist = self._get_posterior_dist(x)
        # 2. Семплуємо z з апостеріорного розподілу (reparameterization trick)
        z = posterior_dist.rsample()
        
        # 3. Розраховуємо пріорний розподіл p(z)
        # Для першого кроку використовуємо нульовий прихований стан
        h_prior = torch.zeros(z.shape[0], self.d_latent, device=z.device)
        z_prior_list = []
        for t in range(z.shape[1]):
            h_prior = self.prior_net(z[:, t, :], h_prior)
            z_prior_list.append(h_prior)
        z_prior = torch.stack(z_prior_list, dim=1)
        prior_dist = Normal(z_prior, torch.ones_like(z_prior))

        # 4. Декодуємо z для отримання параметрів емісії p(x|z)
        decoder_params = self.decoder(z)
        mu_x, scale_x, df_x = decoder_params.chunk(3, dim=-1)
        scale_x = F.softplus(scale_x) + 1e-4 # scale > 0
        df_x = F.softplus(df_x) + 2 # df > 2
        emission_dist = StudentT(df_x, mu_x, scale_x)

        # 5. Розраховуємо компоненти ELBO
        # а) Втрати реконструкції (log-likelihood)
        recon_loss = -emission_dist.log_prob(x).sum(dim=[1, 2]).mean()
        
        # б) KL-дивергенція між апостеріорним та пріорним розподілами
        kl_loss = kl_divergence(posterior_dist, prior_dist).sum(dim=[1, 2]).mean()
        
        # Загальний ELBO loss
        elbo_loss = recon_loss + kl_loss
        
        # 6. Дистиляція від вчителя (якщо надано teacher_z)
        # Це одна з частин L_distill з концепції (KL у латенті)
        if teacher_z is not None:
            # Переконуємось, що розміри співпадають
            if teacher_z.shape == z.shape:
                distill_loss = F.mse_loss(z, teacher_z)
                loss = elbo_loss + lambda_kd * distill_loss
                return loss, z, {'elbo': elbo_loss, 'distill': distill_loss}
            else:
                print(f"Warning: teacher_z shape {teacher_z.shape} mismatch with student_z shape {z.shape}. Skipping distillation.")

        return elbo_loss, z, {'elbo': elbo_loss}

    def decode(self, z):
        """Окремий метод для генерації прогнозу з латентного простору."""
        params = self.decoder(z)
        mu_x, scale_x, df_x = params.chunk(3, dim=-1)
        scale_x = F.softplus(scale_x) + 1e-4
        # Повертаємо середнє як прогноз, і масштаб як невизначеність
        return mu_x, scale_x

    # ---------------- Streaming / Incremental API ---------------- #
    @torch.no_grad()
    def infer_step(self, x_t: torch.Tensor):
        """Incremental inference for a single timestep.

        Parameters
        ----------
        x_t : torch.Tensor shape (batch, d_obs)
            Current observation/features.

        Returns
        -------
        dict with keys:
            z_t: latent sample (batch, d_latent)
            mu_x: emission mean (batch, d_obs)
            scale_x: emission scale (batch, d_obs)
            prior_mean: prior mean used
        """
        if x_t.dim() != 2 or x_t.size(-1) != self.d_obs:
            raise ValueError("x_t must have shape (batch, d_obs)")
        batch = x_t.size(0)
        device = x_t.device
        # Initialize encoder hidden state if first call
        if self._enc_state is None:
            h0 = torch.zeros(3, batch, self.encoder.hidden_size, device=device)
            c0 = torch.zeros(3, batch, self.encoder.hidden_size, device=device)
            self._enc_state = (h0, c0)
        h, c = self._enc_state
        # LSTM expects (batch, seq=1, feat)
        out, (h_new, c_new) = self.encoder(x_t.unsqueeze(1), (h, c))
        self._enc_state = (h_new, c_new)
        enc_last = out[:, -1, :]  # (batch, d_hidden)
        mu_q = self.mu_net(enc_last)
        logvar_q = self.logvar_net(enc_last)
        std_q = torch.exp(0.5 * logvar_q)
        z_t = mu_q + std_q * torch.randn_like(std_q)
        # Prior state
        if self._prior_state is None:
            self._prior_state = torch.zeros(batch, self.d_latent, device=device)
        self._prior_state = self.prior_net(z_t, self._prior_state)
        prior_mean = self._prior_state
        # Decode
        params = self.decoder(z_t)
        mu_x, scale_x, df_x = params.chunk(3, dim=-1)
        scale_x = F.softplus(scale_x) + 1e-4
        return {
            'z_t': z_t,
            'mu_x': mu_x,
            'scale_x': scale_x,
            'prior_mean': prior_mean
        }

    def reset_stream_state(self):
        """Clear internal streaming states (encoder/prior)."""
        self._enc_state = None
        self._prior_state = None

    # ---------------- Persistence Helpers ---------------- #
    def save(self, path: str):
        torch.save({'model_state': self.state_dict()}, path)

    @classmethod
    def load(cls, path: str, d_obs: int, d_latent: int, d_hidden: int = 512, map_location=None):
        model = cls(d_obs=d_obs, d_latent=d_latent, d_hidden=d_hidden)
        payload = torch.load(path, map_location=map_location or 'cpu')
        state = payload.get('model_state', payload)
        model.load_state_dict(state, strict=False)
        return model
