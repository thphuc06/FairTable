"""Lazy waitlist matching (design section 7.2 without workers, D-023).

When a table is freed (a cancel, or an expired hold released by the lazy sweep) it is offered to the
waiting watchers in arrival order. The first watcher it suits and who passes the rules gets a hold
(30 minutes, D-054); a watcher the rules refuse (S1, S2, P0) is skipped. Pure choice in
``domain/waitlist.py``; this module only does the I/O and can be wrapped by a Lambda later.
"""

import logging

from server.domain.clock import iso_z
from server.domain.errors import FairTableError
from server.domain.waitlist import in_arrival_order, watch_fits
from server.ops.waitlist import MatchHoldOperation
from server.pipeline import run_write
from server.tools.common import AppDeps
from server.tools.present import say_date, say_time

log = logging.getLogger("fairtable.matcher")


def offer_freed_slot(deps: AppDeps, venue_id: str, date: str, time: str, table_group: str) -> str | None:
    """Offer one freed table to the waiting watchers. Returns the id of the watch that got it."""
    slot = deps.store.get_slot(venue_id, date, time, table_group)
    now = deps.clock.now()
    if slot is None or slot.effective_status(iso_z(now)) != "open" or slot.drop_controlled:
        return None
    today = now.date().isoformat()
    for watch in in_arrival_order(deps.store.waiting_watches(venue_id, date)):
        if not watch_fits(watch, slot, today):
            continue
        try:
            run_write(deps, watch.identity(), MatchHoldOperation(deps, watch, slot), f"match-{watch.watch_id}")
        except FairTableError as e:
            log.info("watch %s skipped for %s %s: %s", watch.watch_id, date, time, e)
            continue
        venue = deps.store.get_venue(venue_id)
        deps.notifier.notify(
            watch.sub, subject="A table opened up",
            body=f"{venue.name if venue else venue_id} has a table on {say_date(date)} at "
                 f"{say_time(time)}. It is held for you for half an hour: ask your assistant about your waitlist.",
        )
        return watch.watch_id
    return None


def safe_offer(deps: AppDeps, venue_id: str, date: str, time: str, table_group: str) -> None:
    """Matching happens inside somebody else's request: it must never break that request."""
    try:
        offer_freed_slot(deps, venue_id, date, time, table_group)
    except Exception:
        log.exception("waitlist matching failed for %s %s %s", venue_id, date, time)
