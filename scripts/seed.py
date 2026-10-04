"""Create the table (if needed) and load the demo data.

    python scripts/seed.py            # uses TABLE_NAME / DDB_ENDPOINT_URL / AWS_REGION from the env
    python scripts/seed.py --reset    # drop and recreate the table first
    SEED_PROVIDER=kms python scripts/seed.py   # draw the Fair Drop seeds with AWS KMS GenerateRandom (AWS profile)

Local profile: point DDB_ENDPOINT_URL at DynamoDB Local; no AWS account is needed. Nothing here
hard-codes an account, ARN or region.
"""

import argparse
import os
import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from devauth.accounts import USERS_BY_NAME
from server.domain.clock import SystemClock
from server.store import Store, StoreConfig, delete_table, ensure_table, make_client
from server.store.seeding import seed_provider_from_env, seed_store

DINERS = {"alice": "diner-alice", "bob": "diner-bob", "carol": "diner-carol"}
SUBS = {who: USERS_BY_NAME[name].sub for who, name in DINERS.items()}


def subs_for_env(env=None) -> dict[str, str]:
    """The dev issuer's fixed subs, or, with COGNITO_USER_POOL_ID set, the ones Cognito generated."""
    env = os.environ if env is None else env
    pool_id = env.get("COGNITO_USER_POOL_ID")
    if not pool_id:
        return SUBS
    import boto3

    from cognito_users import resolve_subs  # next to this file (python scripts/seed.py puts scripts/ on the path)

    by_name = resolve_subs(boto3.client("cognito-idp"), pool_id, list(DINERS.values()))
    return {who: by_name[name] for who, name in DINERS.items()}


def seed_provider(env=None):
    """Where the secret seed of each Fair Drop comes from: this machine (default) or AWS KMS GenerateRandom
    (`SEED_PROVIDER=kms`, the AWS profile). The rule lives in `server.store.seeding` so the owner console shares it."""
    return seed_provider_from_env(env)


def wait_for_database(client, seconds: int) -> None:
    """Return once the database answers; raise the last error when ``seconds`` have passed."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            client.list_tables()
            return
        except (BotoCoreError, ClientError, OSError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="drop and recreate the table first")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS",
                        help="keep trying for this long while the database is still starting")
    args = parser.parse_args(argv)

    config = StoreConfig.from_env()
    client = make_client(config)
    wait_for_database(client, args.wait)
    if args.reset:
        delete_table(client, config.table_name)
    created = ensure_table(client, config.table_name)
    data = seed_store(Store(client, config.table_name), SystemClock(), subs_for_env(), seed_provider())
    print(
        f"{'created' if created else 'reused'} table {config.table_name}: "
        f"{len(data.venues)} venues, {len(data.slots)} slots, {len(data.drops)} drops"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
