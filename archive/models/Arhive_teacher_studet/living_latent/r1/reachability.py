from living_latent.core.utils.blackbox import blackbox_emit as _emit


def reachability_reject(bridge_id=None, reject_reason: str = 'unreachable'):
    _emit("reachability_reject", {"bridge_id": bridge_id, "why": reject_reason}, severity="WARN")
