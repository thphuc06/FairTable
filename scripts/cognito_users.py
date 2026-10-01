"""Create the demo users in the Cognito user pool (same accounts as the dev issuer) and look up their `sub`.

    python scripts/cognito_users.py            # needs COGNITO_USER_POOL_ID (and AWS credentials / AWS_REGION)

Safe to run twice. The passwords are the public dev values of `devauth/accounts.py` and the README, so
this is for the demo pool only, which is torn down after the demo. No self sign-up exists on the pool.
Cognito generates the `sub`, so the seed script asks it for the subs (`resolve_subs`) instead of using
the dev issuer's fixed ones.
"""

import os
import sys
from typing import Any

from devauth.accounts import USERS, DevUser


def _sub_of(user: dict[str, Any]) -> str:
    return next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")


def ensure_user(client: Any, pool_id: str, user: DevUser) -> str:
    """Create (if missing) and set the permanent password, group and venue. Returns the `sub`."""
    attributes = [{"Name": "custom:venue_id", "Value": user.venue_id}] if user.venue_id else []
    try:
        client.admin_create_user(
            UserPoolId=pool_id, Username=user.username, UserAttributes=attributes, MessageAction="SUPPRESS"
        )
    except client.exceptions.UsernameExistsException:
        if attributes:
            client.admin_update_user_attributes(UserPoolId=pool_id, Username=user.username, UserAttributes=attributes)
    client.admin_set_user_password(
        UserPoolId=pool_id, Username=user.username, Password=user.password, Permanent=True
    )
    for group in user.groups:
        client.admin_add_user_to_group(UserPoolId=pool_id, Username=user.username, GroupName=group)
    return _sub_of(client.admin_get_user(UserPoolId=pool_id, Username=user.username))


def ensure_users(client: Any, pool_id: str) -> dict[str, str]:
    return {u.username: ensure_user(client, pool_id, u) for u in USERS}


def resolve_subs(client: Any, pool_id: str, usernames: list[str]) -> dict[str, str]:
    """`sub` by username, for the seed data (mandates are keyed by the diner's sub)."""
    return {n: _sub_of(client.admin_get_user(UserPoolId=pool_id, Username=n)) for n in usernames}


def main() -> int:
    pool_id = os.environ.get("COGNITO_USER_POOL_ID")
    if not pool_id:
        print("COGNITO_USER_POOL_ID is not set", file=sys.stderr)
        return 2
    import boto3

    subs = ensure_users(boto3.client("cognito-idp"), pool_id)
    print(f"ready: {len(subs)} users in the pool ({', '.join(sorted(subs))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
