"""Load the demo data into a table. Used by ``scripts/seed.py`` and by tests."""

import os
from collections.abc import Mapping

from server.domain.clock import Clock
from server.domain.fairdrop import Drop, KmsSeedProvider, LocalSeedProvider, SeedProvider, commitment
from server.store import keys
from server.store.repository import Store, TxOp
from server.store.seed_data import DropSpec, SeedData, build_seed


def seed_provider_from_env(env: Mapping[str, str] | None = None) -> SeedProvider:
    """Where the secret seed of a Fair Drop comes from: this machine (default) or AWS KMS ``GenerateRandom``
    (``SEED_PROVIDER=kms``, the AWS profile: no key to create or manage, the bytes come from the KMS hardware)."""
    env = os.environ if env is None else env
    if env.get("SEED_PROVIDER", "local").lower() == "kms":
        import boto3

        return KmsSeedProvider(boto3.client("kms"))
    return LocalSeedProvider()


def clear_drop_entries(store: Store, drop_id: str) -> int:
    """Remove the tickets of a drop. A drop that is created again gets a new seed and a new commitment, so a ticket
    from before it was entered under another commitment and must not survive (a reseed of a table that is reused)."""
    items = store.query(keys.drop_partition(drop_id), sk_prefix="ENTRY#", consistent=True)
    for start in range(0, len(items), 25):
        store.transact([TxOp("Delete", key={"PK": i["PK"], "SK": i["SK"]}) for i in items[start:start + 25]])
    return len(items)


def create_drop(store: Store, provider: SeedProvider, spec: DropSpec) -> Drop:
    """Draw the secret seed and store the drop with only its commitment made public."""
    clear_drop_entries(store, spec.drop_id)
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
