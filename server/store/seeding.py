"""Load the demo data into a table. Used by ``scripts/seed.py`` and by tests."""

from collections.abc import Mapping

from server.domain.clock import Clock
from server.store.repository import Store
from server.store.seed_data import SeedData, build_seed


def seed_store(store: Store, clock: Clock, subs: Mapping[str, str]) -> SeedData:
    now = clock.now()
    data = build_seed(now.date(), now, subs)
    for venue in data.venues:
        store.put_venue(venue)
    store.put_slots(list(data.slots))
    for mandate in data.mandates:
        store.put_mandate(mandate)
    return data
