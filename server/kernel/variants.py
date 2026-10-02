"""Deliberately weakened kernels, for the evaluation's ablation only (design section 9.3, plan P1-21).

* ``OpenPep1`` / ``OpenPep2``: allow everything (configuration A0, an "open store" with no policy layer).
* ``NoVoiceGuardsPep2``: the real PEP-2 judged as if the spoken-confirmation facts were all satisfied (a read-back
  token that fits, the pause passed, an explicit yes), so S5a-c can never refuse (configuration A2: whatever the
  assistant sends is taken as the diner's yes). Every other rule judges the real facts. (Re-judging is needed:
  a ``forbid`` hides a missing ``permit``, so turning an S5 refusal into an allow would also let in an agent
  that P0 would refuse.)

Nothing in the server reads a setting to pick these: ``python -m server`` always loads the real
policies, and only ``eval/configs.py`` builds these kernels. They keep the ``decide`` signatures of
``Pep1`` and ``Pep2`` so the pipeline cannot tell the difference.
"""

from dataclasses import replace

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


class NoVoiceGuardsPep2:
    def __init__(self, real: Pep2) -> None:
        self._real = real

    def decide(self, *, action: ToolName, diner_id: str, venue: VenueRef, ctx: PolicyContext) -> Decision:
        satisfied = replace(ctx, read_back_matches=True, pause_elapsed=True, user_confirmed=True)
        return self._real.decide(action=action, diner_id=diner_id, venue=venue, ctx=satisfied)
