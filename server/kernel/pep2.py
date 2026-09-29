"""PEP-2: stateful rules P0, S1-S4, S3b. Counters and mandate facts are read from the store by the
caller and passed in; Cedar only compares numbers and booleans."""

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from server.domain.tool_names import WRITE_TOOLS, ToolName
from server.kernel.engine import Decision, PolicyBundle

SCHEMA_FILE = "pep2.cedarschema"
FILE_PATTERNS = ("p*.cedar", "s*.cedar")


@dataclass(frozen=True)
class PolicyContext:
    """Every field is required and has no default: a missing fact must be a bug, not a silent pass.

    Facts that do not apply to an action are passed as neutral values (0 / False) by the caller.
    """

    agent_tier: str
    active_holds_user_venue: int
    agent_covers_booked: int
    party_size: int
    mandate_covers_booking: bool
    slot_is_drop_controlled: bool
    cancel_fee_cents: int
    cancel_fee_acknowledged: bool

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if f.type is int and (isinstance(value, bool) or not isinstance(value, int)):
                raise TypeError(f"{f.name} must be an int")
            if f.type is int and value < 0:
                raise ValueError(f"{f.name} must not be negative")
            if f.type is bool and not isinstance(value, bool):
                raise TypeError(f"{f.name} must be a bool")
            if f.type is str and not isinstance(value, str):
                raise TypeError(f"{f.name} must be a str")

    def to_cedar(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VenueRef:
    venue_id: str
    agent_cover_cap: int  # covers per day that agents may book (owner-set)


class Pep2:
    def __init__(self, bundle: PolicyBundle) -> None:
        self.bundle = bundle

    @classmethod
    def from_dir(cls, directory: Path) -> "Pep2":
        return cls(PolicyBundle.from_dir("pep2", directory, FILE_PATTERNS, SCHEMA_FILE))

    def decide(
        self, *, action: ToolName, diner_id: str, venue: VenueRef, ctx: PolicyContext
    ) -> Decision:
        if action not in WRITE_TOOLS:
            raise ValueError(f"PEP-2 only covers write tools, got {action!r}")
        entities = [
            {"uid": {"type": "Diner", "id": diner_id}, "attrs": {}, "parents": []},
            {
                "uid": {"type": "Venue", "id": venue.venue_id},
                "attrs": {"agent_cover_cap": venue.agent_cover_cap},
                "parents": [],
            },
        ]
        request = {
            "principal": {"type": "Diner", "id": diner_id},
            "action": {"type": "Action", "id": action.value},
            "resource": {"type": "Venue", "id": venue.venue_id},
            "context": ctx.to_cedar(),
        }
        return self.bundle.evaluate(request, entities)
