"""Trust Kernel: PEP-1 (stateless G1-G4) then PEP-2 (stateful P0, S1-S4, S3b), both Cedar."""

import os
from dataclasses import dataclass
from pathlib import Path

from server.kernel.engine import Decision, DecisionKind, PolicyLoadError
from server.kernel.guidance import deny_to_error
from server.kernel.pep1 import Pep1
from server.kernel.pep2 import Pep2, PolicyContext, VenueRef

__all__ = [
    "Decision",
    "DecisionKind",
    "Pep1",
    "Pep2",
    "PolicyContext",
    "PolicyLoadError",
    "TrustKernel",
    "VenueRef",
    "default_policy_dir",
    "deny_to_error",
]


def default_policy_dir() -> Path:
    """``POLICY_DIR`` if set, otherwise the repo's ``policies/`` folder."""
    env = os.environ.get("POLICY_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2] / "policies"


@dataclass(frozen=True)
class TrustKernel:
    pep1: Pep1
    pep2: Pep2

    @classmethod
    def load(cls, directory: Path | None = None) -> "TrustKernel":
        directory = directory or default_policy_dir()
        return cls(Pep1.from_dir(directory), Pep2.from_dir(directory))
