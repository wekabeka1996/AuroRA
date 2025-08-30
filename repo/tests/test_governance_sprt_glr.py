from repo.core.governance.sprt_glr import SPRT, gaussian_llr
from repo.core.governance.alpha_ledger import AlphaLedger


def test_sprt_accepts_H1_with_positive_signal_and_spends_alpha():
    L = AlphaLedger(alpha_budget=0.10, spend_on_reject=True)
    sprt = SPRT(alpha=0.05, beta=0.1, reset_on_decision=False)
    sprt.start(ledger=L, test_name="sprt_gauss")

    # Gaussian LLR with mu0=0, mu1=1, sigma2=1 -> llr(x)=x-0.5
    # Feed x≈1 so llr~+0.5; A≈log(18)≈2.89, so 6 samples should cross
    res = None
    for _ in range(6):
        res = sprt.update_llr(gaussian_llr(1.0, mu0=0.0, mu1=1.0, sigma2=1.0))
    assert res is not None
    assert res.final is True and res.decision == "accept_H1"

    # Alpha spent-on-reject policy -> budget decreased by alpha
    assert L.spent() >= 0.05 - 1e-12
    assert L.remaining() <= 0.05 + 1e-12


def test_sprt_accepts_H0_with_negative_signal():
    sprt = SPRT(alpha=0.05, beta=0.1, reset_on_decision=False)
    sprt.start()
    # x≈0 so llr~-0.5; B≈log(0.1/0.95)≈-2.25; 5 samples should cross
    res = None
    for _ in range(5):
        res = sprt.update_llr(gaussian_llr(0.0, mu0=0.0, mu1=1.0, sigma2=1.0))
    assert res is not None
    assert res.final is True and res.decision == "accept_H0"