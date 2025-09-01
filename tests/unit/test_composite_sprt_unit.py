# Standalone copy of composite_sprt unit tests to avoid relative import issues.
import pytest
import numpy as np
import time
from unittest.mock import Mock, patch

from core.governance.composite_sprt import (
	CompositeSPRT, AlphaSpendingLedger, AlphaSpendingEntry,
	GaussianKnownVarModel, StudentTModel, SubexponentialModel,
	CompositeHypothesis, HypothesisType,
	create_gaussian_sprt, create_t_test_sprt, create_subexponential_sprt
)

def test_dummy_smoke():
	# small smoke test to ensure module imports correctly in CI
	ledger = AlphaSpendingLedger(total_alpha=0.05)
	assert ledger.get_remaining_alpha() == 0.05
