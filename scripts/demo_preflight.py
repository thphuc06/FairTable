"""Is the AWS side ready for the demo video? One read-only look at the account, one line per thing, and the command
that fixes what is missing.

    AWS_PROFILE=<profile> python scripts/demo_preflight.py [--table fairtable] [--region us-east-1]

It only reads (stacks, table, Cognito, SNS, the Gateway target, the schedule, the budget). Nothing is created or
changed, and nothing account-specific is stored: the account comes from the credentials.
"""

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

UP = ("NOTIFY_EMAIL=<address> MCP_ALLOWED_HOSTS='*.lambda-microvm.*.on.aws' GATEWAY_POLICY=ENFORCE "
      "OBSERVABILITY=true OBSERVABILITY_RUNTIME=true python infra/aws_ctl.py up --runtime")
SEED = "SEED_PROVIDER=kms python infra/aws_ctl.py seed"
STACKS = ("FairTableData", "FairTableIdentity", "FairTableNotify", "FairTableRuntime", "FairTableGateway",
          "FairTableWorkers")


@dataclass(frozen=True)
class Facts:
    today: str  # ISO date
    stacks: dict[str, str]  # name -> status
    users: int  # Cognito users in the pool
    venues: int
    first_slot_day: str | None  # earliest day that has slots
    open_drops: list[str]  # drops that are open, with the day of their draw time
    sns_confirmed: bool
    gateway_target: str | None  # READY | ...
    schedule_state: str | None  # ENABLED | DISABLED
    spend: float | None
    cap: float | None


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""


def judge(f: Facts) -> list[Check]:
    """Pure: the facts in, one verdict per requirement of the demo out."""
    out = [Check(f"stack {name}", f.stacks.get(name, "").endswith("_COMPLETE"), f.stacks.get(name, "missing"), UP)
           for name in STACKS]
    out.append(Check("demo users in Cognito", f.users >= 4, f"{f.users} of 4", UP))
    out.append(Check("restaurants seeded", f.venues >= 3, f"{f.venues} of 3", SEED))
    fresh = f.first_slot_day is not None and f.first_slot_day >= f.today
    out.append(Check("slots start today or later", fresh, f.first_slot_day or "no slots", SEED))
    out.append(Check("a Fair Drop is open for entries", bool(f.open_drops),
                     ", ".join(f.open_drops) or "none (draw days shown)", SEED))
    out.append(Check("SNS e-mail confirmed", f.sns_confirmed, "yes" if f.sns_confirmed else "pending or missing",
                     "click the confirmation link in the e-mail AWS sent when FairTableNotify was deployed"))
    out.append(Check("Gateway target READY", f.gateway_target == "READY", f.gateway_target or "missing",
                     "re-sync the target (synchronize_gateway_targets) or deploy again"))
    out.append(Check("workers schedule ENABLED", f.schedule_state == "ENABLED", f.schedule_state or "missing", UP))
    if f.spend is not None and f.cap:
        out.append(Check("budget has room", f.spend < 0.6 * f.cap, f"${f.spend:.2f} of ${f.cap:.2f}",
                         "check Cost Explorer; remove what is left running"))
    return out


def collect(session, table_name: str) -> Facts:
    cfn, ddb, idp = session.client("cloudformation"), session.client("dynamodb"), session.client("cognito-idp")
    stacks = {}
    for page in cfn.get_paginator("list_stacks").paginate():
        for s in page["StackSummaries"]:
            if s["StackName"] in STACKS and s["StackStatus"] != "DELETE_COMPLETE":
                stacks[s["StackName"]] = s["StackStatus"]
    users = 0
    pool = next((p["Id"] for p in idp.list_user_pools(MaxResults=60)["UserPools"] if p["Name"] == "fairtable-users"), None)
    if pool:
        users = len(idp.list_users(UserPoolId=pool).get("Users", []))
    items = _scan(ddb, table_name)
    venues = sum(1 for i in items if i.get("entity", {}).get("S") == "venue")
    slot_days = sorted({i["date"]["S"] for i in items if i.get("entity", {}).get("S") == "slot" and "date" in i})
    drops = sorted(i["drop_at"]["S"][:10] for i in items
                   if i.get("entity", {}).get("S") == "drop" and i.get("status", {}).get("S") == "open")
    sns = session.client("sns")
    topic = next((t["TopicArn"] for t in sns.list_topics()["Topics"] if t["TopicArn"].endswith(":fairtable-notices")), None)
    confirmed = bool(topic) and any(
        s["SubscriptionArn"].startswith("arn:") for s in sns.list_subscriptions_by_topic(TopicArn=topic)["Subscriptions"])
    return Facts(
        today=datetime.now(UTC).date().isoformat(), stacks=stacks, users=users, venues=venues,
        first_slot_day=(slot_days or [None])[0], open_drops=drops, sns_confirmed=confirmed,
        gateway_target=_gateway_target(session), schedule_state=_schedule(session), **_budget(session),
    )


def _scan(ddb, table: str) -> list[dict]:
    items, kwargs = [], {"TableName": table}
    while True:
        page = ddb.scan(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _gateway_target(session) -> str | None:
    ctl = session.client("bedrock-agentcore-control")
    gateways = [g for g in ctl.list_gateways().get("items", []) if g["name"].startswith("fairtable-gw")]
    if not gateways:
        return None
    targets = ctl.list_gateway_targets(gatewayIdentifier=gateways[0]["gatewayId"]).get("items", [])
    return targets[0]["status"] if targets else None


def _schedule(session) -> str | None:
    try:
        return session.client("scheduler").get_schedule(Name="FairTableWorkersEveryMinute")["State"]
    except Exception:  # noqa: BLE001 - a missing schedule is a verdict, not a crash
        return None


def _budget(session) -> dict:
    account = session.client("sts").get_caller_identity()["Account"]
    for b in session.client("budgets").describe_budgets(AccountId=account).get("Budgets", []):
        if b["BudgetName"].startswith("fairtable-cap-"):
            return {"spend": float(b["CalculatedSpend"]["ActualSpend"]["Amount"]), "cap": float(b["BudgetLimit"]["Amount"])}
    return {"spend": None, "cap": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", default="fairtable")
    parser.add_argument("--region", default=None)
    args = parser.parse_args(argv)
    import boto3

    session = boto3.Session(region_name=args.region)
    checks = judge(collect(session, args.table))
    for c in checks:
        print(f"{'OK     ' if c.ok else 'MISSING'}  {c.name}: {c.detail}")
    missing = [c for c in checks if not c.ok and c.fix]
    if missing:
        print("\nTo fix:")
        for fix in dict.fromkeys(c.fix for c in missing):
            print(f"  {fix}")
    return 0 if all(c.ok for c in checks if c.fix) else 1


if __name__ == "__main__":
    sys.exit(main())
