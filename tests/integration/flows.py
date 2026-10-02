"""Reusable booking flows for integration tests (hold, read back, confirm, count)."""

from datetime import timedelta

from world import World


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
    out = await call(world, "reservation_hold", offer_id=slots[0]["offer_id"], idempotency_key=key)
    assert not out.isError, out.structuredContent
    return out.structuredContent


ANSWER_AFTER_S = 8  # the diner hears the details and answers; longer than the 3 s and 6 s pauses


async def confirm_after_read_back(world: World, who: str, hold: dict, *, key: str, answer_after: float = ANSWER_AFTER_S,
                                  **over):
    """What the assistant does once the diner has said yes: wait for the answer, then confirm with the read-back token
    of the hold. ``over`` replaces or adds arguments (a wrong token, ``user_confirmed=False``...)."""
    world.clock.advance(answer_after)
    args = {"hold_id": hold["hold_id"], "idempotency_key": key, "read_back_token": hold["read_back_token"],
            "user_confirmed": True, **over}
    return await call(world.as_(who), "reservation_confirm", **{k: v for k, v in args.items() if v is not None})


async def book(world: World, who: str, venue: str, time: str, *, party: int = 2, offset: int = 2,
               tag: str = "1") -> dict:
    """A confirmed reservation for ``who``: hold, read back, a pause for the diner's yes, confirm."""
    h = await hold_table(world, who, venue, time, party=party, offset=offset, key=f"key-hold-{tag}0001")
    r = await confirm_after_read_back(world, who, h, key=f"key-conf-{tag}0001")
    assert not r.isError, r.structuredContent
    return r.structuredContent


def counter(world: World, key) -> int:
    item = world.store.get_item(key)
    return int(item["n"]) if item else 0


def error_of(result, code: str) -> dict:
    assert result.isError, result.structuredContent
    assert result.structuredContent["error"] == code, result.structuredContent
    return result.structuredContent
