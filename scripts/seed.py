"""Create the table (if needed) and load the demo data.

    python scripts/seed.py            # uses TABLE_NAME / DDB_ENDPOINT_URL / AWS_REGION from the env
    python scripts/seed.py --reset    # drop and recreate the table first

Local profile: point DDB_ENDPOINT_URL at DynamoDB Local; no AWS account is needed. Nothing here
hard-codes an account, ARN or region.
"""

import argparse
import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from devauth.accounts import USERS_BY_NAME
from server.domain.clock import SystemClock
from server.store import Store, StoreConfig, delete_table, ensure_table, make_client
from server.store.seeding import seed_store

SUBS = {
    "alice": USERS_BY_NAME["diner-alice"].sub,
    "bob": USERS_BY_NAME["diner-bob"].sub,
    "carol": USERS_BY_NAME["diner-carol"].sub,
}


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
    data = seed_store(Store(client, config.table_name), SystemClock(), SUBS)
    print(
        f"{'created' if created else 'reused'} table {config.table_name}: "
        f"{len(data.venues)} venues, {len(data.slots)} slots, {len(data.mandates)} mandates, {len(data.drops)} drops"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
