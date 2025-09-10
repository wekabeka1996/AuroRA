# Standalone copy of composite_sprt unit tests to avoid relative import issues.

from core.governance.composite_sprt import AlphaSpendingLedger


def test_dummy_smoke():
	# small smoke test to ensure module imports correctly in CI
	ledger = AlphaSpendingLedger(total_alpha=0.05)
	assert ledger.get_remaining_alpha() == 0.05
