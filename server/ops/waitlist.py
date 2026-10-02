"""Standing watches: create one, and the hold the matcher makes for a watcher (D-023).

Watch creation transaction (plus idempotency record and audit from the pipeline):
  0. watch record          (new)
  1. uniqueness key        (one active watch per person, restaurant and day)
Matched hold: the normal hold transaction (lasting longer, D-054) plus
  +  watch -> matched      (still waiting, so two matchers cannot both win)
  +  uniqueness key removed (the person may watch again once this one has ended)
"""

from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import Identity, Slot
from server.domain.output import success
from server.domain.offers import SlotClaims
from server.domain.tool_names import ToolName
from server.domain.waitlist import (
    RETRY_AFTER_S,
    WATCH_MATCHED,
    WATCH_WAITING,
    Watch,
)
from server.kernel import Decision, PolicyContext, VenueRef
from server.ops.common import NO_READ_BACK, counter_value
from server.ops.hold import HoldOperation
from server.pipeline import WriteFacts, WritePlan
from server.store import Store, TransactionCancelled, TxOp, keys
from server.tools.common import AppDeps
from server.tools.present import say_date, say_time


class WatchOperation:
    tool = ToolName.WAITLIST_WATCH

    def __init__(self, deps: AppDeps, venue_id: str, date: str, window: tuple[str, str], party_size: int):
        self.deps = deps
        self.venue_id = venue_id
        self.date = date
        self.window = window
        self.party_size = party_size

    def params(self) -> dict:
        return {"kind": "standing", "restaurant_id": self.venue_id, "date": self.date,
                "window": f"{self.window[0]}-{self.window[1]}", "party": self.party_size}

    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        venue = store.get_venue(self.venue_id)
        if venue is None:
            raise FairTableError(ErrorCode.NOT_FOUND, "I could not find that restaurant.",
                             hint="Use a restaurant_id from the search results.")
        self.venue = venue
        return WriteFacts(
            VenueRef(venue.venue_id, venue.agent_cover_cap),
            PolicyContext(
                agent_tier=identity.agent_tier or "none",
                active_holds_user_venue=counter_value(store, keys.active_holds_counter(identity.sub, self.venue_id)),
                agent_covers_booked=counter_value(store, keys.agent_covers_counter(self.venue_id, self.date)),
                party_size=self.party_size, slot_is_drop_controlled=False, **NO_READ_BACK,
            ),
        )

    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        watch = Watch(
            watch_id=self.deps.new_id(), sub=identity.sub, username=identity.username,
            agent_tier=identity.agent_tier, agent_id=identity.agent_id, scopes=identity.scopes,
            venue_id=self.venue_id, date=self.date, window_start=self.window[0],
            window_end=self.window[1], party_size=self.party_size, status=WATCH_WAITING,
            created_at=now_iso,
        )
        self.watch = watch
        result = success(
            f"I'll watch for a table for {self.party_size} at {self.venue.name} on {say_date(self.date)} "
            f"between {say_time(self.window[0])} and {say_time(self.window[1])}. "
            "You'll be told when one opens.",
            watch_id=watch.watch_id, status=WATCH_WAITING, retry_after_s=RETRY_AFTER_S,
            next_step={"tool": "waitlist_status",
                       "why": f"Check back about every {RETRY_AFTER_S} seconds; do not poll faster."},
        )
        return WritePlan(store.watch_put_ops(watch), result, {"watch_id": watch.watch_id})

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        existing = self.deps.store.active_watch_id(
            self.watch.sub, self.venue_id, self.date
        ) if hasattr(self, "watch") else None
        return FairTableError(
            ErrorCode.ALREADY_ENTERED, "You already have an active watch for this restaurant and day.",
            details={"watch_id": existing} if existing else None,
        )


class MatchHoldOperation(HoldOperation):
    """A normal hold for a watcher, created by the matcher with the watcher's stored identity.
    Rules P0, S1 and S2 still apply; the watch turns to ``matched`` in the same transaction."""

    def __init__(self, deps: AppDeps, watch: Watch, slot: Slot) -> None:
        claims = SlotClaims(slot.venue_id, slot.date, slot.slot_key, watch.party_size, slot.ver,
                            watch.sub, hot=slot.hot, drop_id=None)
        super().__init__(deps, claims)
        self.watch = watch
        self.ttl_s = deps.settings.match_hold_ttl_s  # the diner is not in a conversation when the table opens

    def params(self) -> dict:
        return {**super().params(), "watch_id": self.watch.watch_id}

    def extra_ops(self, hold_id: str, now_iso: str) -> list[TxOp]:
        w = self.watch
        wk, key = keys.watch(w.watch_id), keys.watch_slot(w.sub, w.venue_id, w.date)
        return [
            TxOp(
                "Update", key={"PK": wk.pk, "SK": wk.sk},
                update="SET #st = :matched, hold_id = :hid, matched_at = :now REMOVE GSI1PK, GSI1SK",
                condition="#st = :waiting", names={"#st": "status"},
                values={":matched": WATCH_MATCHED, ":hid": hold_id, ":now": now_iso, ":waiting": WATCH_WAITING},
            ),
            TxOp("Delete", key={"PK": key.pk, "SK": key.sk}, condition="attribute_exists(PK)"),
        ]

    def decorate(self, result: dict) -> dict:
        return {**result, "watch_id": self.watch.watch_id}

    def explain_extra(self, failed: list[int]) -> FairTableError:
        return FairTableError(ErrorCode.INVALID_INPUT, "The watch is no longer waiting.")
