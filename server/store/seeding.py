"""Load the demo data into a table. Used by ``scripts/seed.py`` and by tests."""

from collections.abc import Mapping

from server.domain.clock import Clock
from server.domain.fairdrop import Drop, LocalSeedProvider, SeedProvider, commitment
from server.store.repository import Store
from server.store.seed_data import DropSpec, SeedData, build_seed


def create_drop(store: Store, provider: SeedProvider, spec: DropSpec) -> Drop:
    """Draw the secret seed and store the drop with only its commitment made public."""
    seed = provider.new_seed()
    drop = Drop(spec.drop_id, spec.venue_id, spec.date, spec.slot_keys, spec.opens_at, spec.drop_at,
                commitment(seed), seed_hex=seed.hex())
    store.put_drop(drop)
    return drop


def seed_store(store: Store, clock: Clock, subs: Mapping[str, str],
               seeds: SeedProvider | None = None) -> SeedData:
    now = clock.now()
    data = build_seed(now.date(), now, subs)
    for venue in data.venues:
        store.put_venue(venue)
    store.put_slots(list(data.slots))
    provider = seeds or LocalSeedProvider()
    for spec in data.drops:
        create_drop(store, provider, spec)
    return data
