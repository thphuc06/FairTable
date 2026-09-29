"""PEP-1: stateless rules G1-G4 over the verified token claims and the request shape."""

from pathlib import Path

from server.domain.models import Identity
from server.domain.tool_names import ToolName
from server.kernel.engine import Decision, PolicyBundle

SCHEMA_FILE = "pep1.cedarschema"
FILE_PATTERNS = ("g*.cedar",)


class Pep1:
    def __init__(self, bundle: PolicyBundle) -> None:
        self.bundle = bundle

    @classmethod
    def from_dir(cls, directory: Path) -> "Pep1":
        return cls(PolicyBundle.from_dir("pep1", directory, FILE_PATTERNS, SCHEMA_FILE))

    def decide(self, *, identity: Identity, action: ToolName, party_size: int = 0) -> Decision:
        """``party_size`` is 0 for tools that carry none."""
        if isinstance(party_size, bool) or not isinstance(party_size, int) or party_size < 0:
            raise ValueError("party_size must be a non-negative integer")
        attrs: dict[str, object] = {"scopes": sorted(identity.scopes)}
        # Optional claims are omitted when absent so that `principal has <claim>` is false.
        for name in ("username", "agent_tier", "agent_id"):
            value = getattr(identity, name)
            if value is not None:
                attrs[name] = value
        entities = [
            {"uid": {"type": "Client", "id": identity.sub}, "attrs": attrs, "parents": []},
            {"uid": {"type": "Service", "id": "fairtable"}, "attrs": {}, "parents": []},
        ]
        request = {
            "principal": {"type": "Client", "id": identity.sub},
            "action": {"type": "Action", "id": action.value},
            "resource": {"type": "Service", "id": "fairtable"},
            "context": {"party_size": party_size},
        }
        return self.bundle.evaluate(request, entities)
