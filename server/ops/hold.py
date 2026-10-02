"""reservation_hold: take a slot for ten minutes (design section 5.4, "one hold = one transaction").

Transaction (the pipeline adds the idempotency record and the audit entry):
  0. slot -> held           (condition: open, or held with an already-expired hold, and unchanged)
  1. S1 counter + 1         (condition: below the maximum)
  2. S2 counter + party     (condition: still within the restaurant's agent cap)
  3. hold record            (condition: new)
"""

from datetime import timedelta

from server.domain.availability import MAX_SLOTS_RETURNED  # noqa: F401  (documented limit)
from server.domain.booking import (
    HOLD_HELD,
    MAX_ACTIVE_HOLDS,
    Hold,
    starts_at,
    terms_for,
)
from server.domain.readback import KIND_CONFIRM, min_pause_s
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import SLOT_HELD, SLOT_OPEN, Identity, Venue
from server.domain.output import success
from server.domain.offers import SlotClaims
from server.domain.tool_names import ToolName
from server.kernel import Decision, PolicyContext, VenueRef
from server.lifecycle import release_expired_for
from server.ops.common import (
    NO_READ_BACK,
    alternatives,
    capacity_condition,
    counter_value,
    parse_iso,
    parse_slot_key,
)
from server.pipeline import WriteFacts, WritePlan
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import read_back_confirm


class HoldOperation:
    tool = ToolName.RESERVATION_HOLD

    def __init__(self, deps: AppDeps, claims: SlotClaims, *, from_agent: bool = False) -> None:
        self.deps = deps
        self.claims = claims
        self.from_agent = from_agent  # True for a hold the assistant asked for; False for the server's own (waitlist, drop)
        self.venue_id = claims.restaurant_id
        self.party_size = claims.party_size
        self.time, self.group = parse_slot_key(claims.slot_key)
        self.drop_exempt = False  # True only for a Fair Drop winner (the win is the authorisation)
        self.ttl_s: int | None = None  # how long the hold lasts; None = the normal ten minutes
        self.extra_start: int | None = None

    def params(self) -> dict:
        c = self.claims
        return {"restaurant_id": c.restaurant_id, "date": c.date, "slot": c.slot_key, "party": c.party_size}

    def replay_is_stale(self, store: Store, record, now_iso: str) -> bool:
        """A repeat of a call the assistant made returns the stored hold, but only while that hold is still live.
        A new conversation that reuses an old key (a speech model likes "hold-luna-1") must not be told that a hold
        which has long expired or been cancelled is held (D-059)."""
        if not self.from_agent:
            return False
        hold = store.get_hold(record.result.get("hold_id", ""))
        return hold is None or hold.status != HOLD_HELD or hold.held_until <= now_iso

    # ------------------------------------------------------------------ facts (before PEP-2)
    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        c = self.claims
        now = parse_iso(now_iso)
        for freed in release_expired_for(
            store, venue_id=c.restaurant_id, date=c.date, sub=identity.sub, now_iso=now_iso
        ):
            self.deps.slot_released(freed.venue_id, freed.date, freed.time, freed.table_group)

        venue = store.get_venue(c.restaurant_id)
        slot = store.get_slot(c.restaurant_id, c.date, self.time, self.group)
        if venue is None or slot is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "That slot no longer exists.")
        if starts_at(c.date, self.time) <= now:
            raise FairTableError(ErrorCode.INVALID_INPUT, "That time has already passed.")
        if slot.effective_status(now_iso) != SLOT_OPEN:
            raise self._taken(store, slot, now)

        self.venue: Venue = venue
        self.slot = slot
        return WriteFacts(
            VenueRef(venue.venue_id, venue.agent_cover_cap),
            PolicyContext(
                agent_tier=identity.agent_tier or "none",
                active_holds_user_venue=counter_value(store, keys.active_holds_counter(identity.sub, c.restaurant_id)),
                agent_covers_booked=counter_value(store, keys.agent_covers_counter(c.restaurant_id, c.date)),
                party_size=c.party_size,
                slot_is_drop_controlled=slot.drop_controlled and not self.drop_exempt,
                **NO_READ_BACK,
            ),
        )

    # ------------------------------------------------------------------ the transaction
    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        c, venue, slot = self.claims, self.venue, self.slot
        now = parse_iso(now_iso)
        hold_id = self.deps.new_id()
        ttl_s = self.ttl_s or self.deps.settings.hold_ttl_s
        held_until = iso_z(now + timedelta(seconds=ttl_s))
        self.hold = Hold(
            hold_id=hold_id, sub=identity.sub, agent_id=identity.agent_id, venue_id=c.restaurant_id,
            date=c.date, time=self.time, table_group=self.group, party_size=c.party_size,
            status=HOLD_HELD, held_until=held_until, created_at=now_iso,
            terms=terms_for(venue, c.date, self.time, c.party_size),
        )
        slot_key = keys.slot(c.restaurant_id, c.date, self.time, self.group)
        s1 = keys.active_holds_counter(identity.sub, c.restaurant_id)
        s2 = keys.agent_covers_counter(c.restaurant_id, c.date)
        ops = [
            TxOp(
                "Update", key={"PK": slot_key.pk, "SK": slot_key.sk},
                update="SET #st = :held, ver = ver + :one, held_until = :until, hold_id = :hid",
                condition="ver = :v AND (#st = :open OR (#st = :held AND held_until <= :now))",
                names={"#st": "status"},
                values={":held": SLOT_HELD, ":open": SLOT_OPEN, ":one": 1, ":v": slot.ver,
                        ":until": held_until, ":hid": hold_id, ":now": now_iso},
            ),
            TxOp(
                "Update", key={"PK": s1.pk, "SK": s1.sk}, update="ADD n :one",
                condition="attribute_not_exists(n) OR n < :max",
                values={":one": 1, ":max": MAX_ACTIVE_HOLDS},
            ),
            TxOp(
                "Update", key={"PK": s2.pk, "SK": s2.sk}, update="ADD n :party",
                condition=capacity_condition(venue.agent_cover_cap - c.party_size),
                values={":party": c.party_size, ":limit": venue.agent_cover_cap - c.party_size},
            ),
            self.deps.store.hold_put_op(self.hold),
        ]
        self.extra_start = len(ops)
        ops.extend(self.extra_ops(hold_id, now_iso))
        token = self.deps.readback_codec.issue(
            kind=KIND_CONFIRM, subject_id=hold_id, sub=identity.sub, terms=self.hold.terms)
        pause = min_pause_s(self.hold.terms["cancel_fee_cents"])
        read_back = read_back_confirm(self.hold.terms)
        minutes = ttl_s // 60
        hours, rest = divmod(minutes, 60)
        how_long = f"{hours} hour{'s' if hours != 1 else ''}" if hours and not rest else f"{minutes} minutes"
        result = success(
            f"I've held that table for {how_long}. {read_back}",
            hold_id=hold_id, restaurant=venue.name, restaurant_id=venue.venue_id, date=c.date,
            time=self.time, party_size=c.party_size, expires_at=held_until, terms=self.hold.terms,
            read_back=read_back, read_back_token=token, min_pause_s=pause,
            next_step={"tool": "reservation_confirm",
                       "why": "Read the details to the user and ask whether to book. Wait for their answer "
                              f"(at least {pause} seconds after reading). If they say yes, confirm "
                              "with this hold_id, the read_back_token and user_confirmed set "
                              "to true. If they say no, do nothing: the hold ends by itself."},
        )
        return WritePlan(ops, self.decorate(result), {"hold_id": hold_id, "slot": c.slot_key, "party": c.party_size})

    # ------------------------------------------------------------------ hooks for subclasses
    def extra_ops(self, hold_id: str, now_iso: str) -> list[TxOp]:
        """More conditional writes that must succeed or fail together with the hold."""
        return []

    def decorate(self, result: dict) -> dict:
        return result

    def explain_extra(self, failed: list[int]) -> FairTableError:
        return FairTableError(ErrorCode.SLOT_TAKEN, "The request could not be completed; try again.")

    # ------------------------------------------------------------------ mapping a lost race
    def _taken(self, store: Store, slot, now) -> FairTableError:
        return FairTableError(
            ErrorCode.SLOT_TAKEN, "That slot was just taken.",
            details={"alternatives": alternatives(store, self.venue_id, self.claims.date,
                                                  self.claims.party_size, now, exclude=slot)},
        )

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        if self.extra_start is not None and any(i >= self.extra_start for i in failed):
            return self.explain_extra([i - self.extra_start for i in failed if i >= self.extra_start])
        if 1 in failed:
            return FairTableError(ErrorCode.POLICY_DENIED, "The request is not allowed by the restaurant's booking rules.",
                                  rule_id="S1_max_active_holds",
                                  hint="The user already holds the maximum number of active holds at this restaurant.")
        if 2 in failed:
            return FairTableError(ErrorCode.POLICY_DENIED, "The request is not allowed by the restaurant's booking rules.",
                                  rule_id="S2_agent_share_of_covers",
                                  hint="Agent bookings for that day are full.")
        return self._taken(self.deps.store, self.slot, parse_iso(iso_z(self.deps.clock.now())))
