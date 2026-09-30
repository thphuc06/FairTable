"""Standing watches (design section 7.2), pure rules. See docs/DECISIONS.md D-023."""

from dataclasses import dataclass, field

from server.domain.models import Identity, Slot

WATCH_WAITING = "waiting"
WATCH_MATCHED = "matched"
WATCH_CANCELLED = "cancelled"
WATCH_EXPIRED = "expired"

RETRY_AFTER_S = 60  # how long an agent should wait between waitlist_status calls


@dataclass(frozen=True)
class Watch:
    """A request for a table, with a snapshot of the caller's verified identity so the matcher can
    create a hold for them later (rules P0, S1, S2 still run at that moment)."""

    watch_id: str
    sub: str
    username: str | None
    agent_tier: str | None
    agent_id: str | None
    scopes: frozenset[str]
    venue_id: str
    date: str
    window_start: str
    window_end: str
    party_size: int
    status: str
    created_at: str
    hold_id: str | None = None
    matched_at: str | None = None
    cancelled_at: str | None = None
    extra: dict = field(default_factory=dict)

    def identity(self) -> Identity:
        return Identity(
            sub=self.sub, username=self.username, agent_tier=self.agent_tier,
            agent_id=self.agent_id, scopes=self.scopes,
        )


def effective_status(watch: Watch, today: str) -> str:
    """A waiting watch for a past date has expired (checked on read; no worker)."""
    if watch.status == WATCH_WAITING and watch.date < today:
        return WATCH_EXPIRED
    return watch.status


def watch_fits(watch: Watch, slot: Slot, today: str) -> bool:
    """Would this freed slot suit this watcher? Drop-controlled slots never go to a standing watch."""
    return (
        effective_status(watch, today) == WATCH_WAITING
        and watch.venue_id == slot.venue_id
        and watch.date == slot.date
        and watch.window_start <= slot.time <= watch.window_end
        and slot.seats >= watch.party_size
        and not slot.drop_controlled
    )


def in_arrival_order(watches: list[Watch]) -> list[Watch]:
    """First come, first served; the id breaks ties so the order is the same everywhere."""
    return sorted(watches, key=lambda w: (w.created_at, w.watch_id))
