import torch
from models.dssm import DSSM
from models.nfsde import NFSDE


def test_dssm_shapes():
    model = DSSM(d_obs=20, d_latent=16, d_hidden=64)
    x = torch.randn(2, 3, 20)
    loss, z, meta = model(x)
    assert z.shape == (2, 3, 16)
    mu, sigma = model.decode(z[:, -1, :])
    assert mu.shape[-1] == 20
    assert sigma.shape[-1] == 20


def test_nfsde_simulate():
    model = NFSDE(d_state=1, d_latent=8)
    x0 = torch.zeros(1)
    z_traj = torch.randn(1, 10, 8)
    traj = model.simulate(x0, z_traj[0], dt=1e-3, steps=10)
    assert traj.shape[0] == 11
