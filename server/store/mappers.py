"""Domain objects <-> plain item dicts (numbers are ints, sets are lists in the model)."""

from decimal import Decimal
from typing import Any

from server.domain.models import Mandate, Slot, Venue
from server.store import keys


def plain(value: Any) -> Any:
    """Turn what DynamoDB returns (Decimal, set) into plain Python values."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, set):
        return {plain(v) for v in value}
    return value


def venue_to_item(v: Venue) -> dict[str, Any]:
    k = keys.venue(v.venue_id)
    return {
        "PK": k.pk,
        "SK": k.sk,
        "GSI1PK": keys.VENUE_DIRECTORY,
        "GSI1SK": f"{v.name}#{v.venue_id}",
        "entity": "venue",
        "venue_id": v.venue_id,
        "name": v.name,
        "cuisine": v.cuisine,
        "city": v.city,
        "description": v.description,
        "seats_per_day": v.seats_per_day,
        "agent_share_pct": v.agent_share_pct,
        "cancel_fee_cents": v.cancel_fee_cents,
        "free_cancel_hours": v.free_cancel_hours,
    }


def item_to_venue(item: dict[str, Any]) -> Venue:
    item = plain(item)
    return Venue(
        venue_id=item["venue_id"],
        name=item["name"],
        cuisine=item["cuisine"],
        city=item["city"],
        description=item["description"],
        seats_per_day=item["seats_per_day"],
        agent_share_pct=item["agent_share_pct"],
        cancel_fee_cents=item["cancel_fee_cents"],
        free_cancel_hours=item["free_cancel_hours"],
    )


def slot_to_item(s: Slot) -> dict[str, Any]:
    k = keys.slot(s.venue_id, s.date, s.time, s.table_group)
    item: dict[str, Any] = {
        "PK": k.pk,
        "SK": k.sk,
        "entity": "slot",
        "venue_id": s.venue_id,
        "date": s.date,
        "time": s.time,
        "table_group": s.table_group,
        "seats": s.seats,
        "status": s.status,
        "ver": s.ver,
        "hot": s.hot,
    }
    if s.drop_id is not None:
        item["drop_id"] = s.drop_id
    if s.held_until is not None:
        item["held_until"] = s.held_until
    return item


def item_to_slot(item: dict[str, Any]) -> Slot:
    item = plain(item)
    return Slot(
        venue_id=item["venue_id"],
        date=item["date"],
        time=item["time"],
        table_group=item["table_group"],
        seats=item["seats"],
        status=item["status"],
        ver=item["ver"],
        hot=item.get("hot", False),
        drop_id=item.get("drop_id"),
        held_until=item.get("held_until"),
    )


def mandate_to_item(m: Mandate) -> dict[str, Any]:
    k = keys.mandate(m.sub, m.venue_id)
    return {
        "PK": k.pk,
        "SK": k.sk,
        "entity": "mandate",
        "sub": m.sub,
        "venue_id": m.venue_id,
        "status": m.status,
        "version": m.version,
        "party_size_max": m.party_size_max,
        "days_ahead_max": m.days_ahead_max,
        "window_start": m.window_start,
        "window_end": m.window_end,
        "max_cancel_fee_cents": m.max_cancel_fee_cents,
        "allow_auto_confirm": m.allow_auto_confirm,
        "actions": sorted(m.actions),
        "agent_ids": sorted(m.agent_ids),
        "approved_at": m.approved_at,
        "expires_at": m.expires_at,
    }


def item_to_mandate(item: dict[str, Any]) -> Mandate:
    item = plain(item)
    return Mandate(
        sub=item["sub"],
        venue_id=item["venue_id"],
        status=item["status"],
        version=item["version"],
        party_size_max=item["party_size_max"],
        days_ahead_max=item["days_ahead_max"],
        window_start=item["window_start"],
        window_end=item["window_end"],
        max_cancel_fee_cents=item["max_cancel_fee_cents"],
        allow_auto_confirm=item["allow_auto_confirm"],
        actions=frozenset(item["actions"]),
        agent_ids=frozenset(item["agent_ids"]),
        approved_at=item["approved_at"],
        expires_at=item["expires_at"],
    )
