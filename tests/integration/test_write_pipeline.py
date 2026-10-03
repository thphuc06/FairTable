"""P1-8: the write pipeline and idempotency, against DynamoDB Local.

A small stand-in operation (``FakeHold``) plays the role of the real tools that arrive in batch C:
it holds a slot, bumps the user's active-hold counter, and writes a hold record, all conditional.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from ddb_env import ENDPOINT
from world import World

from server.domain.errors import ErrorCode, FairTableError
from server.domain.models import Identity
from server.domain.output import success
from server.domain.tool_names import ToolName
from server.kernel import Decision, PolicyContext, VenueRef
from server.pipeline import WriteFacts, WritePlan, run_write
from server.store import Store, TransactionCancelled, TxOp, keys

pytestmark = pytest.mark.ddb

KEY = "key-0000-0001"


@dataclass
class FakeHold:
    venue_id: str
    date: str
    time: str
    group: str
    party_size: int
    hold_id: str
    tool: ToolName = ToolName.RESERVATION_HOLD
    read_back_ok: bool = True  # for a confirm: the terms were read back, the pause passed, the diner said yes

    def params(self) -> dict[str, Any]:
        return {"venue": self.venue_id, "date": self.date, "time": self.time, "group": self.group,
                "party": self.party_size}

    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts:
        counter = store.get_item(keys.active_holds_counter(identity.sub, self.venue_id))
        slot = store.get_slot(self.venue_id, self.date, self.time, self.group)
        venue = store.get_venue(self.venue_id)
        return WriteFacts(
            VenueRef(self.venue_id, venue.agent_cover_cap),
            PolicyContext(
                agent_tier=identity.agent_tier or "none",
                active_holds_user_venue=int(counter["n"]) if counter else 0,
                agent_covers_booked=0, party_size=self.party_size,
                slot_is_drop_controlled=slot.drop_controlled, booked_same_day=False,
                read_back_required=self.tool is ToolName.RESERVATION_CONFIRM,
                read_back_matches=self.read_back_ok, pause_elapsed=self.read_back_ok, user_confirmed=self.read_back_ok,
            ),
        )

    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        slot = store.get_slot(self.venue_id, self.date, self.time, self.group)
        slot_key = keys.slot(self.venue_id, self.date, self.time, self.group)
        counter = keys.active_holds_counter(identity.sub, self.venue_id)
        hold = keys.hold(self.hold_id)
        ops = [
            TxOp("Update", key={"PK": slot_key.pk, "SK": slot_key.sk},
                 update="SET #s = :held, ver = ver + :one",
                 condition="#s = :open AND ver = :v", names={"#s": "status"},
                 values={":held": "held", ":open": "open", ":v": slot.ver, ":one": 1}),
            TxOp("Update", key={"PK": counter.pk, "SK": counter.sk}, update="ADD n :one",
                 condition="attribute_not_exists(n) OR n < :max", values={":one": 1, ":max": 2}),
            TxOp("Put", item={"PK": hold.pk, "SK": hold.sk, "sub": identity.sub, "slot": slot.slot_key},
                 condition="attribute_not_exists(PK)"),
        ]
        return WritePlan(ops, success("Held it.", hold_id=self.hold_id, time=self.time),
                         {"hold_id": self.hold_id})

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        if 1 in failed:
            return FairTableError(ErrorCode.POLICY_DENIED, "Too many holds.", rule_id="S1_max_active_holds")
        return FairTableError(ErrorCode.SLOT_TAKEN, "That slot was just taken.")


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock)
    ids = iter(range(10_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


def who(world: World, name: str = "alice") -> Identity:
    return world.deps.verifier.verify(world.token(name))


def hold(world: World, time: str = "19:00", group: str = "T4", hold_id: str = "h1", party: int = 2,
         **kw) -> FakeHold:
    day = world.clock.now().date().isoformat()
    return FakeHold("luna-trattoria", day, time, group, party, hold_id, **kw)


def slot_of(world: World, time="19:00", group="T4"):
    return world.store.get_slot("luna-trattoria", world.clock.now().date().isoformat(), time, group)


def counter_of(world: World, sub: str = "dev-alice") -> int:
    item = world.store.get_item(keys.active_holds_counter(sub, "luna-trattoria"))
    return int(item["n"]) if item else 0


def audit_of(world: World) -> list[dict]:
    return world.store.list_audit("luna-trattoria", world.clock.now().date().isoformat())


# ---------------------------------------------------------------- happy path
def test_a_successful_write_changes_everything_in_one_go(world):
    result = run_write(world.deps, who(world), hold(world), KEY)
    assert result == {"spoken_summary": "Held it.", "hold_id": "h1", "time": "19:00"}
    assert (slot_of(world).status, slot_of(world).ver) == ("held", 2)
    assert counter_of(world) == 1
    assert world.store.get_item(keys.hold("h1"))["sub"] == "dev-alice"
    record = world.store.get_idempotency("dev-alice", KEY)
    assert record.result == result and record.tool == "reservation_hold"
    [entry] = audit_of(world)
    assert (entry["decision"], entry["rule_ids"], entry["tool"]) == ("allow", ["P0_base"], "reservation_hold")


# ---------------------------------------------------------------- idempotency
def test_repeating_the_same_request_returns_the_stored_result_and_writes_nothing(world):
    first = run_write(world.deps, who(world), hold(world), KEY)
    again = run_write(world.deps, who(world), hold(world), KEY)
    assert again == {**first, "idempotent_replay": True}
    assert counter_of(world) == 1 and slot_of(world).ver == 2 and len(audit_of(world)) == 1


def test_the_same_key_with_different_parameters_is_a_conflict(world):
    run_write(world.deps, who(world), hold(world), KEY)
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), hold(world, time="19:30", hold_id="h2"), KEY)
    assert exc.value.code is ErrorCode.IDEMPOTENCY_CONFLICT
    assert slot_of(world, "19:30").status == "open" and counter_of(world) == 1


def test_the_same_key_on_another_tool_is_a_conflict(world):
    run_write(world.deps, who(world), hold(world), KEY)
    other = hold(world, tool=ToolName.RESERVATION_CONFIRM)
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), other, KEY)
    assert exc.value.code is ErrorCode.IDEMPOTENCY_CONFLICT


def test_keys_are_per_user(world):
    run_write(world.deps, who(world, "alice"), hold(world), KEY)
    other = run_write(world.deps, who(world, "bob"), hold(world, "19:30", hold_id="h2"), KEY)
    assert "idempotent_replay" not in other  # Bob's key is not Alice's key


@pytest.mark.parametrize("bad", ["", "short", "spaces are bad", None])
def test_a_bad_key_is_invalid_input_and_writes_nothing(world, bad):
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), hold(world), bad)
    assert exc.value.code is ErrorCode.INVALID_INPUT and slot_of(world).status == "open"


# ---------------------------------------------------------------- refusals store nothing
def test_pep1_refusal_stores_no_key_but_is_audited(world):
    bot = who(world, "bot")
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, bot, hold(world), KEY)
    assert exc.value.rule_id == "G4_verified_agent_only"
    assert slot_of(world).status == "open" and world.store.get_idempotency(bot.sub, KEY) is None
    assert [e["decision"] for e in audit_of(world)] == ["deny"]


def test_pep2_refusal_stores_no_key_so_it_can_be_retried(world):
    world.store.put_item({**keys_item(keys.active_holds_counter("dev-alice", "luna-trattoria")), "n": 2})
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), hold(world), KEY)
    assert exc.value.rule_id == "S1_max_active_holds"
    assert world.store.get_idempotency("dev-alice", KEY) is None
    # After a hold is released the very same key works: nothing was remembered.
    world.store.put_item({**keys_item(keys.active_holds_counter("dev-alice", "luna-trattoria")), "n": 1})
    assert run_write(world.deps, who(world), hold(world), KEY)["hold_id"] == "h1"


def test_drop_controlled_slots_cannot_be_held_directly(world):
    day = next_friday(world)
    op = FakeHold("sakura-counter", day, "20:00", "T2", 2, "h9")
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), op, KEY)
    assert exc.value.code is ErrorCode.DROP_CONTROLLED and exc.value.rule_id == "S4_drop_slots_via_waitlist"


def test_a_voice_guard_refusal_stores_no_key_and_is_audited(world):
    op = hold(world, tool=ToolName.RESERVATION_CONFIRM, read_back_ok=False)
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), op, KEY)
    assert exc.value.code is ErrorCode.CONFIRMATION_REQUIRED and exc.value.rule_id == "S5a_confirm_needs_read_back"
    assert world.store.get_idempotency("dev-alice", KEY) is None and slot_of(world).status == "open"
    assert [e["decision"] for e in audit_of(world)] == ["deny"]


def test_a_lost_race_for_the_slot_is_slot_taken_and_leaves_no_trace(world):
    # Someone else takes the slot between our read (facts) and our write (transaction).
    class Sneaky(FakeHold):
        def plan(self, store, identity, now_iso, decision):
            plan = super().plan(store, identity, now_iso, decision)
            slot_key = keys.slot(self.venue_id, self.date, self.time, self.group)
            store.put_item({"PK": slot_key.pk, "SK": slot_key.sk, "status": "held", "ver": 99,
                            "entity": "slot"})
            return plan

    day = world.clock.now().date().isoformat()
    op = Sneaky("luna-trattoria", day, "19:00", "T4", 2, "h1")
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), op, KEY)
    assert exc.value.code is ErrorCode.SLOT_TAKEN
    assert counter_of(world) == 0 and world.store.get_item(keys.hold("h1")) is None
    assert world.store.get_idempotency("dev-alice", KEY) is None
    assert [e["decision"] for e in audit_of(world)] == ["failed"]


# ---------------------------------------------------------------- concurrency
def test_duplicate_deliveries_of_one_request_create_exactly_one_hold(world):
    barrier = threading.Barrier(20)
    alice = who(world)

    def deliver(_):
        barrier.wait()
        return run_write(world.deps, alice, hold(world), KEY)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(deliver, range(20)))
    assert {r["hold_id"] for r in results} == {"h1"}
    assert sum("idempotent_replay" not in r for r in results) == 1  # one real write, 19 replays
    assert counter_of(world) == 1 and slot_of(world).ver == 2
    assert len([e for e in audit_of(world) if e["decision"] == "allow"]) == 1


def test_twenty_different_users_racing_for_one_slot_get_one_winner(world):
    barrier = threading.Barrier(20)

    def attempt(i: int):
        user = Identity(sub=f"racer-{i:02d}", username=f"racer{i}", agent_tier="verified",
                        agent_id="alexa-plus-sim", scopes=frozenset({"fairtable/book"}))
        barrier.wait()
        try:
            run_write(world.deps, user, hold(world, hold_id=f"h{i:02d}"), f"race-key-{i:04d}")
            return "won"
        except FairTableError as e:
            return e.code.value

    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(attempt, range(20)))
    assert outcomes.count("won") == 1
    assert outcomes.count("SLOT_TAKEN") == 19
    counters = [counter_of(world, f"racer-{i:02d}") for i in range(20)]
    assert sum(counters) == 1  # losers' counters were rolled back with the rest of their transaction
    assert slot_of(world).ver == 2
    holds = [i for i in range(20) if world.store.get_item(keys.hold(f"h{i:02d}"))]
    assert len(holds) == 1  # no orphan holds


def keys_item(k: keys.Key) -> dict:
    return {"PK": k.pk, "SK": k.sk}


def next_friday(world: World) -> str:
    day = world.clock.now().date()
    while day.weekday() != 4:
        day += timedelta(days=1)
    return day.isoformat()


# ---------------------------------------------------------------- the "stored in between" branch
def _interleaved(world: World, inner_op: FakeHold):
    """An operation that, right before its own write, lets ``inner_op`` finish with the same key:
    exactly what a duplicate delivery landing between lookup and write looks like."""

    class Interleaved(FakeHold):
        def plan(self, store, identity, now_iso, decision):
            plan = super().plan(store, identity, now_iso, decision)
            run_write(world.deps, identity, inner_op, KEY)
            return plan

    return Interleaved("luna-trattoria", inner_op.date, inner_op.time, inner_op.group,
                       inner_op.party_size, inner_op.hold_id)


def test_a_duplicate_stored_between_lookup_and_write_is_replayed(world):
    inner = hold(world)
    outer = _interleaved(world, inner)  # same parameters as the inner one
    result = run_write(world.deps, who(world), outer, KEY)
    assert result["idempotent_replay"] is True and result["hold_id"] == "h1"
    assert counter_of(world) == 1 and slot_of(world).ver == 2  # only the inner write happened


def test_a_conflicting_key_stored_between_lookup_and_write_is_a_conflict(world):
    class Different(FakeHold):
        def params(self):
            return {**super().params(), "note": "different"}

    outer = _interleaved(world, hold(world))
    outer.__class__ = type("Both", (Different, outer.__class__), {})  # same slot, other parameters
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), outer, KEY)
    assert exc.value.code is ErrorCode.IDEMPOTENCY_CONFLICT
    assert counter_of(world) == 1 and slot_of(world, "19:00").ver == 2


# ---------------------------------------------------------------- the copy that fails only because the original just won
def test_a_copy_refused_for_a_reason_the_original_created_is_replayed_not_refused(world):
    """The original commits between the copy's lookup and its checks, so the copy finds the slot
    taken. The right answer is the stored result, not SLOT_TAKEN / HOLD_EXPIRED."""
    inner = hold(world)

    class Late(FakeHold):
        def load_facts(self, store, identity, now_iso):
            run_write(world.deps, identity, inner, KEY)  # the original finishes first
            raise FairTableError(ErrorCode.SLOT_TAKEN, "That slot was just taken.")

    day = world.clock.now().date().isoformat()
    copy = Late("luna-trattoria", day, "19:00", "T4", 2, "h1")
    result = run_write(world.deps, who(world), copy, KEY)
    assert result["idempotent_replay"] is True and result["hold_id"] == "h1"
    assert counter_of(world) == 1 and slot_of(world).ver == 2


def test_the_same_window_with_different_parameters_is_a_conflict_not_a_refusal(world):
    inner = hold(world)

    class Late(FakeHold):
        def params(self):
            return {**super().params(), "note": "different"}

        def load_facts(self, store, identity, now_iso):
            run_write(world.deps, identity, inner, KEY)
            raise FairTableError(ErrorCode.SLOT_TAKEN, "That slot was just taken.")

    day = world.clock.now().date().isoformat()
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), Late("luna-trattoria", day, "19:00", "T4", 2, "h1"), KEY)
    assert exc.value.code is ErrorCode.IDEMPOTENCY_CONFLICT


def test_a_genuine_refusal_with_no_stored_key_is_still_a_refusal(world):
    class Refused(FakeHold):
        def load_facts(self, store, identity, now_iso):
            raise FairTableError(ErrorCode.SLOT_TAKEN, "That slot was just taken.")

    day = world.clock.now().date().isoformat()
    with pytest.raises(FairTableError) as exc:
        run_write(world.deps, who(world), Refused("luna-trattoria", day, "19:00", "T4", 2, "h1"), KEY)
    assert exc.value.code is ErrorCode.SLOT_TAKEN
