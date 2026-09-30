"""Invariant checker: reads the whole table and reports anything that should never be true.

Used by the concurrency tests now and by the eval graders later (design section 9.1):
  I1  no booking outside the user's mandate unless the user approved that exact hold
  I2  no double-booked table (at most one live hold or confirmed reservation per slot)
  I3  a cancellation fee is charged only after the user approved it
  I4  one Fair Drop ticket per person, and an allocated drop's audit verifies
  I5  no write without a verified identity
  plus the bookkeeping that makes the rules trustworthy:
  COUNTER  the S1 / S2 counters equal what the holds and reservations add up to
  SLOT     a slot's status agrees with the hold or reservation that owns it

This module scans everything: for tests, graders and diagnostics, never for a request path.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from server.domain.booking import (
    APPROVAL_USED,
    HOLD_HELD,
    KIND_CANCEL_FEE,
    RES_CANCELLED,
    RES_CONFIRMED,
    Hold,
)
from server.domain.fairdrop import DROP_ALLOCATED, ENTRY_WON, verify_audit
from server.domain.mandate import check_mandate
from server.domain.models import SLOT_CONFIRMED, SLOT_HELD, SLOT_OPEN
from server.domain.tool_names import WRITE_TOOLS
from server.store import Store
from server.store.mappers import (
    item_to_approval,
    item_to_drop,
    item_to_entry,
    item_to_hold,
    item_to_mandate,
    item_to_reservation,
    item_to_slot,
    item_to_venue,
)


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


def check_invariants(store: Store, now_iso: str) -> list[Violation]:
    items = store.scan_all()
    by_entity: dict[str, list[dict]] = defaultdict(list)
    counters: dict[str, int] = {}
    for item in items:
        if item["PK"].startswith("CNT#"):
            counters[item["PK"]] = int(item["n"])
        else:
            by_entity[item.get("entity", "?")].append(item)

    holds = {h.hold_id: h for h in map(item_to_hold, by_entity["hold"])}
    reservations = {r.reservation_id: r for r in map(item_to_reservation, by_entity["reservation"])}
    approvals = {a.subject_id: a for a in map(item_to_approval, by_entity["approval"])}
    mandates = {(m.sub, m.venue_id): m for m in map(item_to_mandate, by_entity["mandate"])}
    venues = {v.venue_id: v for v in map(item_to_venue, by_entity["venue"])}
    slots = list(map(item_to_slot, by_entity["slot"]))
    out: list[Violation] = []

    def live(hold: Hold) -> bool:
        return hold.status == HOLD_HELD and hold.held_until > now_iso

    # ---- I2: at most one live claim per slot
    claims: dict[tuple, list[str]] = defaultdict(list)
    for h in holds.values():
        if live(h):
            claims[(h.venue_id, h.date, h.time, h.table_group)].append(f"hold {h.hold_id}")
    for r in reservations.values():
        if r.status == RES_CONFIRMED:
            claims[(r.venue_id, r.date, r.time, r.table_group)].append(f"reservation {r.reservation_id}")
    for slot_id, who in claims.items():
        if len(who) > 1:
            out.append(Violation("I2", f"{slot_id} is claimed by {', '.join(who)}"))

    # ---- SLOT: status agrees with its owner
    for s in slots:
        sid = (s.venue_id, s.date, s.time, s.table_group)
        if s.status == SLOT_OPEN and claims.get(sid):
            out.append(Violation("SLOT", f"{sid} is open but claimed by {claims[sid]}"))
        if s.status == SLOT_HELD and s.held_until and s.held_until > now_iso:
            owner = holds.get(s.hold_id or "")
            if owner is None or owner.status != HOLD_HELD:
                out.append(Violation("SLOT", f"{sid} is held by {s.hold_id}, which is not a held hold"))
        if s.status == SLOT_CONFIRMED:
            owner = reservations.get(s.reservation_id or "")
            if owner is None or owner.status != RES_CONFIRMED:
                out.append(Violation("SLOT", f"{sid} is confirmed for {s.reservation_id}, which is not confirmed"))
    slot_ids = {(s.venue_id, s.date, s.time, s.table_group) for s in slots}
    for sid in claims:
        if sid not in slot_ids:
            out.append(Violation("SLOT", f"{sid} has a claim but no slot exists"))

    # ---- COUNTER: S1 and S2 equal what the records add up to
    expected: dict[str, int] = defaultdict(int)
    for h in holds.values():
        if h.status == HOLD_HELD:  # includes expired-but-unreleased holds: they are still counted
            expected[f"CNT#USER#{h.sub}#REST#{h.venue_id}"] += 1
            expected[f"CNT#REST#{h.venue_id}#D#{h.date}"] += h.party_size
    for r in reservations.values():
        if r.status == RES_CONFIRMED:
            expected[f"CNT#REST#{r.venue_id}#D#{r.date}"] += r.party_size
    for pk in sorted(set(expected) | set(counters)):
        if counters.get(pk, 0) != expected.get(pk, 0):
            out.append(Violation("COUNTER", f"{pk} is {counters.get(pk, 0)}, records say {expected.get(pk, 0)}"))
        if counters.get(pk, 0) < 0:
            out.append(Violation("COUNTER", f"{pk} is negative"))

    # ---- I1: every booking was inside the mandate or approved by the user
    for r in reservations.values():
        approval = approvals.get(r.hold_id)
        approved = approval is not None and approval.status == APPROVAL_USED and approval.sub == r.sub
        venue = venues.get(r.venue_id)
        created = datetime.fromisoformat(r.created_at)
        covered = venue is not None and check_mandate(
            mandates.get((r.sub, r.venue_id)), now=created, agent_id=r.agent_id,
            party_size=r.terms_snapshot.get("party_size", r.party_size), day=date.fromisoformat(r.date),
            time=r.time, cancel_fee_cents=venue.cancel_fee_cents,
        ).covered
        if not (approved or covered):
            out.append(Violation("I1", f"reservation {r.reservation_id} is outside the mandate and unapproved"))

    # ---- I3: a fee is charged only after approval
    for r in reservations.values():
        if r.status == RES_CANCELLED and (r.cancel_fee_cents or 0) > 0:
            approval = approvals.get(r.reservation_id)
            if not (approval and approval.kind == KIND_CANCEL_FEE and approval.status == APPROVAL_USED
                    and approval.sub == r.sub):
                out.append(Violation("I3", f"reservation {r.reservation_id} paid a fee without approval"))

    # ---- I4: one ticket per person per drop; an allocated drop is consistent and verifiable
    drops = {d.drop_id: d for d in map(item_to_drop, by_entity["drop"])}
    tickets = list(map(item_to_entry, by_entity["entry"]))
    seen: dict[tuple[str, str], str] = {}
    for t in tickets:
        who = (t.drop_id, t.sub)
        if who in seen:
            out.append(Violation("I4", f"{t.sub} holds two tickets in {t.drop_id}: {seen[who]} and {t.entry_id}"))
        seen[who] = t.entry_id
    for d in drops.values():
        won = [t for t in tickets if t.drop_id == d.drop_id and t.status == ENTRY_WON]
        if len(won) > d.capacity:
            out.append(Violation("I4", f"{d.drop_id} has {len(won)} winners for {d.capacity} places"))
        for t in won:
            if not t.hold_id or t.hold_id not in holds:
                out.append(Violation("I4", f"winner {t.entry_id} has no hold"))
        if d.status == DROP_ALLOCATED:
            for problem in verify_audit(d.audit or {}):
                out.append(Violation("I4", f"{d.drop_id} audit: {problem}"))
            if sorted(d.audit.get("winners", [])) != sorted(t.entry_id for t in won):
                out.append(Violation("I4", f"{d.drop_id} audit winners differ from the stored tickets"))

    # ---- I5: nothing was written without an identity
    for h in holds.values():
        if not h.sub:
            out.append(Violation("I5", f"hold {h.hold_id} has no user"))
    for r in reservations.values():
        if not r.sub:
            out.append(Violation("I5", f"reservation {r.reservation_id} has no user"))
    write_names = {t.value for t in WRITE_TOOLS}
    for a in by_entity["audit"]:
        if a["tool"] in write_names and a["decision"] == "allow" and not a.get("sub"):
            out.append(Violation("I5", f"an allowed {a['tool']} was recorded without a user"))
    return out


def assert_invariants(store: Store, now_iso: str) -> None:
    violations = check_invariants(store, now_iso)
    assert not violations, "invariants broken:\n" + "\n".join(f"  {v}" for v in violations)
