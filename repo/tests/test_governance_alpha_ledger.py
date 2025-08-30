from repo.core.governance.alpha_ledger import AlphaLedger


def test_alpha_ledger_spend_on_reject_policy():
    L = AlphaLedger(alpha_budget=0.10, spend_on_reject=True)

    # Open reserves but does not spend yet
    t1 = L.open(test_name="sprt", alpha=0.02)
    assert L.spent() == 0.0
    assert L.reserved() >= 0.02
    rem_before = L.remaining()

    # Commit accept (no spend)
    e1 = L.commit(t1, decision="accept", p_value=0.3, test_name="sprt")
    assert L.spent() == 0.0
    assert L.remaining() == rem_before  # accept does not spend under this policy

    # Open and then reject -> spend alpha
    t2 = L.open(test_name="sprt", alpha=0.03)
    e2 = L.commit(t2, decision="reject", p_value=0.01, test_name="sprt")
    assert abs(L.spent() - 0.03) < 1e-12
    assert abs(L.remaining() - (0.10 - 0.03)) < 1e-12

    hist = L.history()
    assert len(hist) == 2 and all(isinstance(h, dict) for h in hist)


def test_alpha_ledger_spend_on_test_policy():
    L = AlphaLedger(alpha_budget=0.05, spend_on_reject=False)

    # Spend immediately on open
    t1 = L.open(test_name="daily", alpha=0.02)
    assert abs(L.spent() - 0.02) < 1e-12
    assert abs(L.remaining() - 0.03) < 1e-12

    # Opening beyond remaining should raise
    t2 = L.open(test_name="daily", alpha=0.02)
    assert abs(L.spent() - 0.04) < 1e-12
    assert abs(L.remaining() - 0.01) < 1e-12

    # Next open with alpha>remaining must fail
    try:
        L.open(test_name="daily", alpha=0.02)
        assert False, "expected RuntimeError for insufficient budget"
    except RuntimeError:
        pass

    # Committing does not change spent in this policy
    L.commit(t1, decision="accept", p_value=0.8, test_name="daily")
    L.commit(t2, decision="reject", p_value=0.01, test_name="daily")
    assert abs(L.spent() - 0.04) < 1e-12