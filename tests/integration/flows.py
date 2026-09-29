"""Reusable booking flows for integration tests (hold, confirm, approve, count)."""

from dataclasses import replace
from datetime import timedelta

from world import World

from server.domain.clock import iso_z


def day(world: World, offset: int = 2) -> str:
    return (world.clock.now().date() + timedelta(days=offset)).isoformat()


async def call(world: World, tool: str, **args):
    async with world.client() as c:
        return await c.call_tool_mcp(tool, args)


async def hold_table(world: World, who: str, venue: str, time: str, *, party: int = 2, offset: int = 2,
                     key: str = "key-hold-0001") -> dict:
    world.as_(who)
    r = await call(world, "availability_check", restaurant_id=venue, date=day(world, offset),
                   time_window=f"{time}-{time}", party_size=party)
    slots = r.structuredContent["slots"]
    assert slots, r.structuredContent
    out = await call(world, "reservation_hold", slot_token=slots[0]["slot_token"], idempotency_key=key)
    assert not out.isError, out.structuredContent
    return out.structuredContent


def set_approval(world: World, subject_id: str, status: str = "approved", **changes) -> None:
    """What the consent page does when the user answers."""
    approval = world.store.get_approval(subject_id)
    world.store.replace_approval(replace(approval, status=status, decided_at=iso_z(world.clock.now()), **changes))


async def book(world: World, who: str, venue: str, time: str, *, party: int = 2, offset: int = 2,
               tag: str = "1") -> dict:
    """A confirmed reservation for ``who``; approves the step-up on the way when it is needed."""
    h = await hold_table(world, who, venue, time, party=party, offset=offset, key=f"key-hold-{tag}0001")
    key = f"key-conf-{tag}0001"
    r = await call(world.as_(who), "reservation_confirm", hold_id=h["hold_id"], idempotency_key=key)
    if r.isError and r.structuredContent["error"] == "CONSENT_REQUIRED":
        set_approval(world, h["hold_id"])
        r = await call(world, "reservation_confirm", hold_id=h["hold_id"], idempotency_key=key)
    assert not r.isError, r.structuredContent
    return r.structuredContent


def counter(world: World, key) -> int:
    item = world.store.get_item(key)
    return int(item["n"]) if item else 0


def error_of(result, code: str) -> dict:
    assert result.isError, result.structuredContent
    assert result.structuredContent["error"] == code, result.structuredContent
    return result.structuredContent
