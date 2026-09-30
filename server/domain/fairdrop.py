"""Fair Drop (design section 7.3): a verifiable lottery, pure functions. See D-023.

1. Before entries open, a secret seed is drawn and only ``SHA-256(seed)`` (the *commitment*) is
   published: nobody, including the restaurant, can pick a seed after seeing the entries.
2. Each verified person gets one ticket. The ticket id is a hash, so the public audit shows no ``sub``.
3. After the drop time the seed is revealed. The winning order is ``HMAC-SHA256(seed, entry_id)``
   ascending; anyone can recompute it from the published audit (``verify_audit``).
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

SEED_BYTES = 32
ALGORITHM = "order = HMAC-SHA256(seed, entry_id) ascending; commitment = SHA-256(seed)"

DROP_OPEN = "open"
DROP_ALLOCATING = "allocating"
DROP_ALLOCATED = "allocated"
DROP_CANCELLED = "cancelled"

ENTRY_ENTERED = "entered"
ENTRY_WON = "won"
ENTRY_LOST = "lost"
ENTRY_SKIPPED = "skipped"


# ---------------------------------------------------------------------------- seeds
class SeedProvider(Protocol):
    def new_seed(self) -> bytes: ...


class LocalSeedProvider:
    """Operating-system randomness. The local profile needs nothing else."""

    def new_seed(self) -> bytes:
        return secrets.token_bytes(SEED_BYTES)


class FixedSeedProvider:
    """Deterministic seeds for tests and reproducible demos."""

    def __init__(self, *seeds: bytes) -> None:
        self._seeds = list(seeds) or [bytes(range(SEED_BYTES))]
        self._next = 0

    def new_seed(self) -> bytes:
        seed = self._seeds[self._next % len(self._seeds)]
        self._next += 1
        return seed


class KmsSeedProvider:
    """AWS KMS ``GenerateRandom`` (scaffold only: not used or tested against AWS until the
    developer says "wire AWS", docs/DECISIONS.md D-016). Takes an already configured boto3 client."""

    def __init__(self, kms_client: Any) -> None:
        self._kms = kms_client

    def new_seed(self) -> bytes:
        return self._kms.generate_random(NumberOfBytes=SEED_BYTES)["Plaintext"]


# ---------------------------------------------------------------------------- hashes
def commitment(seed: bytes) -> str:
    return hashlib.sha256(seed).hexdigest()


def entry_hash(drop_id: str, sub: str) -> str:
    return hashlib.sha256(f"{drop_id}|{sub}".encode()).hexdigest()


def entry_id(drop_id: str, sub: str) -> str:
    return f"{drop_id}~{entry_hash(drop_id, sub)}"


def split_entry_id(value: str) -> tuple[str, str] | None:
    drop_id, sep, digest = value.rpartition("~")
    return (drop_id, digest) if sep and drop_id and len(digest) == 64 else None


def draw_key(seed: bytes, entry: str) -> str:
    return hmac.new(seed, entry.encode(), hashlib.sha256).hexdigest()


def order_entries(seed: bytes, entries: list[str]) -> list[str]:
    """The lottery order: independent of who arrived first, fixed by the seed alone."""
    return sorted(entries, key=lambda e: (draw_key(seed, e), e))


# ---------------------------------------------------------------------------- records
@dataclass(frozen=True)
class Drop:
    drop_id: str
    venue_id: str
    date: str
    slot_keys: tuple[str, ...]  # e.g. ("2000#T2",); capacity = len(slot_keys)
    opens_at: str
    drop_at: str
    commitment: str
    status: str = DROP_OPEN
    seed_hex: str | None = None  # secret until the audit is published
    allocating_since: str | None = None
    allocated_at: str | None = None
    audit: dict[str, Any] | None = None

    @property
    def capacity(self) -> int:
        return len(self.slot_keys)


@dataclass(frozen=True)
class DropEntry:
    entry_id: str
    drop_id: str
    sub: str
    username: str | None
    agent_tier: str | None
    agent_id: str | None
    scopes: frozenset[str]
    party_size: int
    created_at: str
    status: str = ENTRY_ENTERED
    hold_id: str | None = None
    reason: str | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------- audit
def build_audit(
    drop: Drop, seed: bytes, entries: list[DropEntry], outcomes: dict[str, tuple[str, str | None]],
    allocated_at: str,
) -> dict[str, Any]:
    """The public record. ``outcomes`` maps entry_id -> (won|lost|skipped, reason)."""
    ordered = order_entries(seed, [e.entry_id for e in entries])
    return {
        "drop_id": drop.drop_id,
        "restaurant_id": drop.venue_id,
        "date": drop.date,
        "slots": list(drop.slot_keys),
        "capacity": drop.capacity,
        "algorithm": ALGORITHM,
        "commitment": drop.commitment,
        "seed": seed.hex(),
        "opens_at": drop.opens_at,
        "drop_at": drop.drop_at,
        "allocated_at": allocated_at,
        "entries": [e.entry_id for e in sorted(entries, key=lambda e: (e.created_at, e.entry_id))],
        "order": [
            {"entry_id": e, "draw_key": draw_key(seed, e), "outcome": outcomes[e][0],
             **({"reason": outcomes[e][1]} if outcomes[e][1] else {})}
            for e in ordered
        ],
        "winners": [e for e in ordered if outcomes[e][0] == ENTRY_WON],
    }


def pending_audit(drop: Drop) -> dict[str, Any]:
    """What may be public before the draw: the commitment and the rules, never the seed."""
    return {
        "drop_id": drop.drop_id, "restaurant_id": drop.venue_id, "date": drop.date,
        "slots": list(drop.slot_keys), "capacity": drop.capacity, "algorithm": ALGORITHM,
        "commitment": drop.commitment, "opens_at": drop.opens_at, "drop_at": drop.drop_at,
        "status": drop.status,
    }


def verify_audit(audit: dict[str, Any]) -> list[str]:
    """Recompute everything from the published data. An empty list means the draw checks out."""
    problems: list[str] = []
    try:
        seed = bytes.fromhex(audit["seed"])
        if commitment(seed) != audit["commitment"]:
            problems.append("the seed does not match the commitment published beforehand")
        entries = list(audit["entries"])
        if len(set(entries)) != len(entries):
            problems.append("an entry appears twice")
        expected = order_entries(seed, entries)
        listed = [row["entry_id"] for row in audit["order"]]
        if listed != expected:
            problems.append("the published order is not HMAC-SHA256(seed, entry_id) ascending")
        for row in audit["order"]:
            if row["draw_key"] != draw_key(seed, row["entry_id"]):
                problems.append(f"wrong draw key for {row['entry_id']}")
        winners = [row["entry_id"] for row in audit["order"] if row["outcome"] == ENTRY_WON]
        if winners != audit["winners"]:
            problems.append("the winners list does not match the outcomes")
        if len(winners) > audit["capacity"]:
            problems.append("more winners than places")
        # A draw never passes over someone for a later person: everyone before the last winner
        # either won or was skipped for a stated reason, and 'lost' only follows a full house.
        won = 0
        for row in audit["order"]:
            if row["outcome"] == ENTRY_WON:
                won += 1
            elif row["outcome"] == ENTRY_LOST and won < audit["capacity"]:
                problems.append(f"{row['entry_id']} lost although places were left")
            elif row["outcome"] == ENTRY_SKIPPED and not row.get("reason"):
                problems.append(f"{row['entry_id']} was skipped without a reason")
    except (KeyError, ValueError, TypeError) as e:
        problems.append(f"the audit is malformed: {e}")
    return problems
