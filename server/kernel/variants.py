"""Deliberately weakened kernels, for the evaluation's ablation only (design section 9.3, plan P1-21).

* ``OpenPep1`` / ``OpenPep2``: allow everything (configuration A0, an "open store" with no policy layer).
* ``NoStepUpPep2``: the real PEP-2, except that a ``step_up`` decision is treated as ``allow``
  (configuration A2: the assistant's own "yes" in the conversation is enough, nothing goes to the
  diner's phone). Denials are untouched.

Nothing in the server reads a setting to pick these: ``python -m server`` always loads the real
policies, and only ``eval/configs.py`` builds these kernels. They keep the ``decide`` signatures of
``Pep1`` and ``Pep2`` so the pipeline cannot tell the difference.
"""

from server.domain.models import Identity
from server.domain.tool_names import ToolName
from server.kernel.engine import Decision, DecisionKind
from server.kernel.pep2 import Pep2, PolicyContext, VenueRef

OPEN_RULE = "A0_open_store"


class OpenPep1:
    def decide(self, *, identity: Identity, action: ToolName, party_size: int = 0) -> Decision:
        return Decision(DecisionKind.ALLOW, (OPEN_RULE,), "pep1")


class OpenPep2:
    def decide(self, *, action: ToolName, diner_id: str, venue: VenueRef, ctx: PolicyContext) -> Decision:
        return Decision(DecisionKind.ALLOW, (OPEN_RULE,), "pep2")


class NoStepUpPep2:
    def __init__(self, real: Pep2) -> None:
        self._real = real

    def decide(self, *, action: ToolName, diner_id: str, venue: VenueRef, ctx: PolicyContext) -> Decision:
        decision = self._real.decide(action=action, diner_id=diner_id, venue=venue, ctx=ctx)
        if decision.kind is DecisionKind.STEP_UP:
            return Decision(DecisionKind.ALLOW, decision.rule_ids, decision.source, decision.errors)
        return decision
