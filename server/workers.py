"""Background work for the AWS profile (D-062, plan task P3-15): the same lazy routines, run on a schedule.

Everything the server does lazily when a request happens to touch it can also be done by a clock:

* **hold sweeper**: release holds whose time has passed (``lifecycle.release_expired``), which offers the freed
  table to the waiting watchers (``deps.slot_released`` = the matcher) and sends their notice;
* **Fair Drop allocator**: run the draw of every drop whose time has come (``dropper.maybe_allocate``), which
  tells the winners and publishes the audit.

Both are idempotent and race-safe (conditional writes), so they can run next to the lazy paths of the server and
twice at once. ``run_once`` is what the Lambda ``workers/handler.py`` calls every minute. Nothing here needs the
Lambda: tests call it with a fake clock.
"""

import logging
from datetime import timedelta

from server.domain.clock import iso_z
from server.dropper import maybe_allocate
from server.lifecycle import release_expired
from server.tools.common import AppDeps

log = logging.getLogger("fairtable.workers")
DAYS_AHEAD = 15  # today and the next two weeks: the window the demo data covers (server/store/seed_data.py)


def _days(deps: AppDeps, days: int) -> list[str]:
    today = deps.clock.now().date()
    return [(today + timedelta(days=i)).isoformat() for i in range(days)]


def sweep_holds(deps: AppDeps, *, days: int = DAYS_AHEAD) -> int:
    """Release every expired hold. Returns how many this call released."""
    now_iso = iso_z(deps.clock.now())
    released = 0
    for venue in deps.store.list_venues():
        for day in _days(deps, days):
            for hold in deps.store.expired_holds_on_day(venue.venue_id, day, now_iso):
                if release_expired(deps.store, hold, now_iso):
                    released += 1
                    deps.slot_released(hold.venue_id, hold.date, hold.time, hold.table_group)
    return released


def due_drop_ids(deps: AppDeps, *, days: int = DAYS_AHEAD) -> list[str]:
    """Drops of the coming days whose draw time has passed and that have not been drawn."""
    now_iso = iso_z(deps.clock.now())
    ids: set[str] = set()
    for venue in deps.store.list_venues():
        for day in _days(deps, days):
            ids.update(s.drop_id for s in deps.store.get_slots(venue.venue_id, day) if s.drop_id)
    due = []
    for drop_id in sorted(ids):
        drop = deps.store.get_drop(drop_id)
        if drop is not None and drop.status in ("open", "allocating") and now_iso >= drop.drop_at:
            due.append(drop_id)
    return due


def allocate_due_drops(deps: AppDeps, *, days: int = DAYS_AHEAD) -> list[str]:
    """Run the draw of every due drop. Returns the ids of the drops that were drawn by this call."""
    done = []
    for drop_id in due_drop_ids(deps, days=days):
        try:
            drop = maybe_allocate(deps, drop_id)
        except Exception:  # noqa: BLE001 - one broken drop must not stop the others; the next run resumes it
            log.exception("drop %s could not be drawn", drop_id)
            continue
        if drop is not None and drop.status == "allocated":
            done.append(drop_id)
    return done


def run_once(deps: AppDeps, *, days: int = DAYS_AHEAD) -> dict:
    """One tick of the schedule."""
    released = sweep_holds(deps, days=days)
    drawn = allocate_due_drops(deps, days=days)
    summary = {"holds_released": released, "drops_drawn": drawn}
    log.info("workers tick: %s", summary)
    return summary
