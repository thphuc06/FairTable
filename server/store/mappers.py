"""Domain objects <-> plain item dicts (numbers are ints, sets are lists in the model)."""

from decimal import Decimal
from typing import Any

from server.domain.booking import HOLD_HELD, Approval, Hold, Reservation
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
    for name in ("held_until", "hold_id", "reservation_id"):
        if getattr(s, name) is not None:
            item[name] = getattr(s, name)
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
        hold_id=item.get("hold_id"),
        reservation_id=item.get("reservation_id"),
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


def hold_to_item(h: Hold) -> dict[str, Any]:
    k = keys.hold(h.hold_id)
    item: dict[str, Any] = {
        "PK": k.pk, "SK": k.sk, "entity": "hold", "hold_id": h.hold_id, "sub": h.sub,
        "agent_id": h.agent_id, "venue_id": h.venue_id, "date": h.date, "time": h.time,
        "table_group": h.table_group, "party_size": h.party_size, "status": h.status,
        "held_until": h.held_until, "created_at": h.created_at, "within_mandate": h.within_mandate,
        "terms": h.terms, "hold_extended": h.extended,
        "GSI2PK": keys.user_partition(h.sub), "GSI2SK": f"HOLD#{h.created_at}#{h.hold_id}",
    }
    if h.status == HOLD_HELD:  # listed by expiry only while it can still expire
        item["GSI1PK"] = keys.hold_day_partition(h.venue_id, h.date)
        item["GSI1SK"] = f"{h.held_until}#{h.hold_id}"
    return item


def item_to_hold(item: dict[str, Any]) -> Hold:
    item = plain(item)
    return Hold(
        hold_id=item["hold_id"], sub=item["sub"], agent_id=item.get("agent_id"),
        venue_id=item["venue_id"], date=item["date"], time=item["time"],
        table_group=item["table_group"], party_size=item["party_size"], status=item["status"],
        held_until=item["held_until"], created_at=item["created_at"],
        within_mandate=item["within_mandate"], terms=item.get("terms", {}),
        extended=item.get("hold_extended", False),
    )


def reservation_to_item(r: Reservation) -> dict[str, Any]:
    k = keys.reservation(r.reservation_id)
    item: dict[str, Any] = {
        "PK": k.pk, "SK": k.sk, "entity": "reservation", "reservation_id": r.reservation_id,
        "code": r.code, "hold_id": r.hold_id, "sub": r.sub, "agent_id": r.agent_id,
        "venue_id": r.venue_id, "date": r.date, "time": r.time, "table_group": r.table_group,
        "party_size": r.party_size, "status": r.status, "terms_snapshot": r.terms_snapshot,
        "created_at": r.created_at,
        "GSI2PK": keys.user_partition(r.sub), "GSI2SK": f"RES#{r.date}#{r.time}#{r.reservation_id}",
    }
    if r.cancelled_at is not None:
        item["cancelled_at"] = r.cancelled_at
    if r.cancel_fee_cents is not None:
        item["cancel_fee_cents"] = r.cancel_fee_cents
    return item


def item_to_reservation(item: dict[str, Any]) -> Reservation:
    item = plain(item)
    return Reservation(
        reservation_id=item["reservation_id"], code=item["code"], hold_id=item["hold_id"],
        sub=item["sub"], agent_id=item.get("agent_id"), venue_id=item["venue_id"],
        date=item["date"], time=item["time"], table_group=item["table_group"],
        party_size=item["party_size"], status=item["status"],
        terms_snapshot=item["terms_snapshot"], created_at=item["created_at"],
        cancelled_at=item.get("cancelled_at"), cancel_fee_cents=item.get("cancel_fee_cents"),
    )


def approval_to_item(a: Approval) -> dict[str, Any]:
    k = keys.approval(a.subject_id)
    item: dict[str, Any] = {
        "PK": k.pk, "SK": k.sk, "entity": "approval", "subject_id": a.subject_id, "kind": a.kind,
        "sub": a.sub, "venue_id": a.venue_id, "terms_hash": a.terms_hash, "terms": a.terms,
        "status": a.status, "created_at": a.created_at, "expires_at": a.expires_at,
    }
    if a.decided_at is not None:
        item["decided_at"] = a.decided_at
    return item


def item_to_approval(item: dict[str, Any]) -> Approval:
    item = plain(item)
    return Approval(
        subject_id=item["subject_id"], kind=item["kind"], sub=item["sub"],
        venue_id=item["venue_id"], terms_hash=item["terms_hash"], terms=item["terms"],
        status=item["status"], created_at=item["created_at"], expires_at=item["expires_at"],
        decided_at=item.get("decided_at"),
    )
