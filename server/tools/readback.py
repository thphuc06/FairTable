"""Tool-layer helper: when a confirm (or a cancel with a fee) is refused because the terms were not read back,
hand the assistant a fresh read-back so it can recover in the next call (D-051).

Only S5a gets a new token. After S5b (too soon) or S5c (no yes) the assistant still holds a good token, and a new
one would restart the pause and trap it in a loop of too-early calls.
"""

from server.domain.errors import FairTableError
from server.domain.models import Identity

MISSING_READ_BACK = "S5a_confirm_needs_read_back"


def offer_read_back(error: FairTableError, op, identity: Identity) -> FairTableError:
    if error.rule_id == MISSING_READ_BACK and hasattr(op, "read_back_offer"):
        offer = op.read_back_offer(identity)
        if offer:
            error.details = {**(error.details or {}), **offer}
    return error
