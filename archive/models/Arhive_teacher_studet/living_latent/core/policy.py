from typing import Callable
from living_latent.core.utils.blackbox import blackbox_emit as _emit


def policy_block_two_signals():
    _emit("policy_block_two_signals", {"reason": "two_signals"}, severity="WARN")


def policy_block_mi_guard():
    _emit("policy_block_mi_guard", {"reason": "mi_guard"}, severity="WARN")
