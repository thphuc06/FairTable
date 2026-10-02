"""P3-15: the background workers do on a clock what the server does lazily on a request."""

import json

import pytest
from ddb_env import ENDPOINT
from flows import call, day, hold_table
from test_fair_drop import SEED, after_the_draw, drop_id, enter
from world import World

from server.audit_sink import NullAuditSink, S3AuditSink
from server.domain import fairdrop as fd
from server.domain.clock import iso_z
from server.invariants import assert_invariants
from server.workers import allocate_due_drops, due_drop_ids, run_once, sweep_holds

pytestmark = pytest.mark.ddb
LUNA = "luna-trattoria"


class FakeS3:
    def __init__(self, fail: bool = False) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.fail = fail

    def put_object(self, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("s3 is down")
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs


@pytest.fixture
def world(ddb_client, table_name, clock):
    w = World(ddb_client, table_name, ENDPOINT, clock, seeds=fd.FixedSeedProvider(SEED))
    ids = iter(range(1, 100_000))
    w.deps.new_id = lambda: f"id{next(ids):05d}"
    return w


async def watch(world: World, who: str, *, party: int = 5):
    return await call(world.as_(who), "waitlist_watch", restaurant_id=LUNA, date=day(world, 2),
                      idempotency_key="watch-key-0001", time_window="19:00-19:00", party_size=party)


# ---------------------------------------------------------------- the hold sweeper
async def test_the_sweeper_releases_an_expired_hold_and_hands_the_table_to_the_waiting_diner(world):
    held = await hold_table(world, "bob", LUNA, "19:00", party=5, key="bob-hold-0001")
    w = (await watch(world, "alice")).structuredContent["watch_id"]
    assert sweep_holds(world.deps) == 0  # nothing has expired yet
    world.clock.advance(minutes=11)
    assert sweep_holds(world.deps) == 1  # no request touched the restaurant: the clock did the work
    assert world.store.get_hold(held["hold_id"]).status == "expired"
    assert world.store.get_watch(w).status == "matched"
    assert [m["subject"] for m in world.store.list_inbox("dev-alice")] == ["A table opened up"]
    assert sweep_holds(world.deps) == 0  # nothing is released twice
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_the_sweeper_frees_the_user_counter_so_rule_s1_stops_counting_old_holds(world):
    for i, t in enumerate(("17:30", "18:00")):
        await hold_table(world, "alice", LUNA, t, key=f"alice-hold-000{i}")
    world.clock.advance(minutes=11)
    assert sweep_holds(world.deps) == 2
    assert not world.store.holds_of_user("dev-alice") or all(h.status != "held" for h in world.store.holds_of_user("dev-alice"))
    assert_invariants(world.store, iso_z(world.clock.now()))


# ---------------------------------------------------------------- the Fair Drop allocator
async def test_the_allocator_draws_a_due_drop_without_any_request_and_tells_the_winner(world):
    did = drop_id(world)
    for who in ("alice", "bob", "carol"):
        await enter(world, who)
    assert due_drop_ids(world.deps) == []  # not due yet
    after_the_draw(world)
    assert due_drop_ids(world.deps) == [did]
    assert allocate_due_drops(world.deps) == [did]
    assert world.store.get_drop(did).status == "allocated"
    assert due_drop_ids(world.deps) == [] and allocate_due_drops(world.deps) == []  # exactly once
    winner = fd.order_entries(SEED, [fd.entry_id(did, s) for s in ("dev-alice", "dev-bob", "dev-carol")])[0]
    owner = next(s for s in ("dev-alice", "dev-bob", "dev-carol") if fd.entry_id(did, s) == winner)
    assert [m["subject"] for m in world.store.list_inbox(owner)] == ["You won the draw"]
    assert_invariants(world.store, iso_z(world.clock.now()))


async def test_the_audit_is_copied_to_the_audit_sink_when_the_draw_happens(world):
    s3 = FakeS3()
    world.deps.audit_sink = S3AuditSink(s3, "audit-bucket")
    did = drop_id(world)
    await enter(world, "alice")
    after_the_draw(world)
    allocate_due_drops(world.deps)
    (bucket, key), put = next(iter(s3.objects.items()))
    assert (bucket, key) == ("audit-bucket", f"drops/{did}.json") and put["ContentType"] == "application/json"
    published = json.loads(put["Body"])
    assert published == world.store.get_drop(did).audit and fd.verify_audit(published) == []


async def test_a_broken_audit_sink_never_fails_the_draw(world):
    world.deps.audit_sink = S3AuditSink(FakeS3(fail=True), "audit-bucket")
    await enter(world, "alice")
    after_the_draw(world)
    assert allocate_due_drops(world.deps) == [drop_id(world)]
    assert world.store.get_drop(drop_id(world)).status == "allocated"


def test_the_null_sink_writes_nothing():
    assert NullAuditSink().publish("d", {"a": 1}) is None


async def test_run_once_does_both_jobs_and_reports_them(world):
    held = await hold_table(world, "bob", LUNA, "19:00", party=5, key="bob-hold-0001")
    await enter(world, "alice")
    world.clock.advance(minutes=11)
    after_the_draw(world)
    summary = run_once(world.deps)
    assert summary == {"holds_released": 1, "drops_drawn": [drop_id(world)]}
    assert world.store.get_hold(held["hold_id"]).status == "expired"
    assert run_once(world.deps) == {"holds_released": 0, "drops_drawn": []}
