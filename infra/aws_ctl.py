"""One command to deploy, inspect and remove everything FairTable puts on an AWS account (plan task P2-8).

    python infra/aws_ctl.py status                  # what exists now, and what still costs money
    python infra/aws_ctl.py up [--runtime]          # deploy the stacks (CDK) and create the demo users
    python infra/aws_ctl.py seed                    # write the demo data into the table (needs the Cognito pool)
    python infra/aws_ctl.py down                    # dry run: the plan only
    python infra/aws_ctl.py down --yes --account 1905   # destroy the stacks and what they leave behind
    python infra/aws_ctl.py down --yes --account 1905 --include-budget --include-bootstrap   # at the very end

Nothing account-specific is stored here: the account comes from the credentials, the region from
`AWS_REGION` (default us-east-1), the table from `TABLE_NAME`. `down` only ever touches resources whose
names belong to this project (see ``OWNED``); the budget and the CDK bootstrap stack stay unless asked for.
Credentials: anything boto3 and the CDK CLI accept (for `aws login` without `awscrt` use
`scripts/aws_credential_process.py`, see infra/cdk/README.md).
"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CDK_DIR = ROOT / "infra" / "cdk"

# Destroy order: what depends on another stack goes first.
STACKS = ("FairTableObservability", "FairTableGateway", "FairTableRuntime", "FairTableNotify", "FairTableIdentity",
          "FairTableData")
BUDGET_STACK = "FairTableBudget"
BOOTSTRAP_STACK = "CDKToolkit"

# Names that belong to this project. Anything else on the account is never touched.
OWNED = {
    "table_prefixes": ("ft-test-", "ft-race-", "ft-seedscript-", "ft-spike-", "ft-seedcheck-"),
    "pool_name": "fairtable-users",
    "function_prefix": "FairTable",
    "runtime_prefix": "fairtable_mcp",
    "gateway_prefix": "fairtable-gw",
    "policy_engine_prefix": "fairtable_engine",
    "log_prefixes": ("/aws/bedrock-agentcore/runtimes/fairtable_mcp-", "/aws/lambda/FairTable"),
    "secret_marker": "SlotTokenSecret",
    "span_log_groups": ("aws/spans", "/aws/application-signals/data"),  # made by CloudWatch Transaction Search
    "budget_prefix": "fairtable-cap-",  # the stack names its budget like this; the developer's own budgets differ
}


@dataclass(frozen=True)
class Item:
    kind: str  # stack | table | pool | function | secret | runtime | gateway | policy-engine | log-group | budget | bootstrap
    name: str
    billable: bool  # costs money (or could) while it exists
    by: str  # what removes it: "stack:<name>" or "direct"

    def line(self) -> str:
        return f"  {self.kind:<10} {self.name}  [{'costs money' if self.billable else 'free'}; removed by {self.by}]"


# ----------------------------------------------------------------------------- pure logic
def table_is_ours(name: str, table_name: str) -> bool:
    return name == table_name or name.startswith(OWNED["table_prefixes"])


def log_group_is_ours(name: str) -> bool:
    return name.startswith(OWNED["log_prefixes"])


def stack_order(existing: set[str], *, include_budget: bool, include_bootstrap: bool) -> list[str]:
    order = [s for s in STACKS if s in existing]
    if include_budget and BUDGET_STACK in existing:
        order.append(BUDGET_STACK)
    if include_bootstrap and BOOTSTRAP_STACK in existing:
        order.append(BOOTSTRAP_STACK)
    return order


def billable_leftovers(items: list[Item], *, include_budget: bool, include_bootstrap: bool) -> list[Item]:
    """What still exists and costs money, leaving out what this `down` was not asked to remove."""
    kept: set[str] = set()
    if not include_budget:
        kept.add(BUDGET_STACK)
    if not include_bootstrap:
        kept.add(BOOTSTRAP_STACK)
    return [i for i in items if i.billable and i.name not in kept]


def strays(items: list[Item], existing_stacks: set[str]) -> list[Item]:
    """Tables and log groups that no stack will remove: test tables, the service's own log groups, or a
    table whose stack is already gone."""
    def owned_by_live_stack(item: Item) -> bool:
        return item.by.startswith("stack:") and item.by.split(":", 1)[1] in existing_stacks

    return [i for i in items if i.kind in ("table", "log-group") and not owned_by_live_stack(i)]


# ----------------------------------------------------------------------------- inspection (boto3)
class Account:
    def __init__(self, region: str, table_name: str, session=None) -> None:
        import boto3

        self.region, self.table_name = region, table_name
        s = session or boto3.Session(region_name=region)
        self.cfn = s.client("cloudformation")
        self.ddb = s.client("dynamodb")
        self.idp = s.client("cognito-idp")
        self.fn = s.client("lambda")
        self.logs = s.client("logs")
        self.sm = s.client("secretsmanager")
        self.ac = s.client("bedrock-agentcore-control")
        self.s3 = s.client("s3")
        self.budgets = s.client("budgets")
        self.sts = s.client("sts")
        self.xray = s.client("xray")

    def account_id(self) -> str:
        return self.sts.get_caller_identity()["Account"]

    def who(self) -> tuple[str, str]:
        """(last four digits of the account id, kind of identity: root | user | role)."""
        ident = self.sts.get_caller_identity()
        arn = ident["Arn"]
        kind = "root" if arn.endswith(":root") else "role" if ":assumed-role/" in arn else "user"
        return ident["Account"][-4:], kind

    def inventory(self) -> list[Item]:
        items: list[Item] = []
        live = ("CREATE_COMPLETE", "UPDATE_COMPLETE", "ROLLBACK_COMPLETE", "CREATE_FAILED", "UPDATE_ROLLBACK_COMPLETE",
                "DELETE_FAILED", "UPDATE_ROLLBACK_FAILED")
        for page in self.cfn.get_paginator("list_stacks").paginate(StackStatusFilter=list(live)):
            for s in page["StackSummaries"]:
                name = s["StackName"]
                if name in STACKS or name in (BUDGET_STACK, BOOTSTRAP_STACK):
                    kind = "bootstrap" if name == BOOTSTRAP_STACK else "stack"
                    items.append(Item(kind, name, billable=kind == "bootstrap", by="direct"))
        for page in self.ddb.get_paginator("list_tables").paginate():
            items += [Item("table", n, True, "stack:FairTableData" if n == self.table_name else "direct")
                      for n in page["TableNames"] if table_is_ours(n, self.table_name)]
        for page in self.idp.get_paginator("list_user_pools").paginate(MaxResults=60):
            items += [Item("pool", p["Id"] + " (" + p["Name"] + ")", True, "stack:FairTableIdentity")
                      for p in page["UserPools"] if p["Name"] == OWNED["pool_name"]]
        for page in self.fn.get_paginator("list_functions").paginate():
            items += [Item("function", f["FunctionName"], False, "stack:FairTableIdentity")
                      for f in page["Functions"] if f["FunctionName"].startswith(OWNED["function_prefix"])]
        for page in self.sm.get_paginator("list_secrets").paginate():
            items += [Item("secret", s["Name"], True, "stack:FairTableRuntime")
                      for s in page["SecretList"] if OWNED["secret_marker"] in s["Name"] and not s.get("DeletedDate")]
        for page in self.ac.get_paginator("list_agent_runtimes").paginate():
            items += [Item("runtime", r["agentRuntimeName"] + " " + r["agentRuntimeId"], True, "stack:FairTableRuntime")
                      for r in page["agentRuntimes"] if r["agentRuntimeName"].startswith(OWNED["runtime_prefix"])]
        for page in self.ac.get_paginator("list_gateways").paginate():
            items += [Item("gateway", g["name"] + " " + g["gatewayId"], True, "stack:FairTableGateway")
                      for g in page["items"] if g["name"].startswith(OWNED["gateway_prefix"])]
        for page in self.ac.get_paginator("list_policy_engines").paginate():
            items += [Item("policy-engine", e["name"] + " " + e["policyEngineId"], True, "stack:FairTableGateway")
                      for e in page["policyEngines"] if e["name"].startswith(OWNED["policy_engine_prefix"])]
        for prefix in OWNED["log_prefixes"]:
            for page in self.logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix):
                items += [Item("log-group", g["logGroupName"], True, "direct") for g in page["logGroups"]]
        if self.trace_destination() != "XRay":  # Transaction Search switches the whole account (P2-9, D-050)
            items.append(Item("setting", "X-Ray trace destination is CloudWatchLogs", True, "direct"))
            for name in OWNED["span_log_groups"]:
                items += [Item("log-group", g["logGroupName"], True, "direct")
                          for g in self.logs.describe_log_groups(logGroupNamePrefix=name)["logGroups"]
                          if g["logGroupName"] == name]
        for page in self.budgets.get_paginator("describe_budgets").paginate(AccountId=self.account_id()):
            items += [Item("budget", b["BudgetName"], False, "stack:FairTableBudget")
                      for b in page["Budgets"] if b["BudgetName"].startswith(OWNED["budget_prefix"])]
        return items

    def trace_destination(self) -> str:
        return self.xray.get_trace_segment_destination().get("Destination", "XRay")

    # ------------------------------------------------------------------------- removal of what stacks leave
    def restore_trace_destination(self) -> None:
        """Give the account's spans back to X-Ray (the default) after Transaction Search has been used."""
        self.xray.update_trace_segment_destination(Destination="XRay")

    def delete_table(self, name: str) -> None:
        self.ddb.delete_table(TableName=name)
        self.ddb.get_waiter("table_not_exists").wait(TableName=name)

    def delete_log_group(self, name: str) -> None:
        self.logs.delete_log_group(logGroupName=name)

    def empty_and_delete_bucket(self, bucket: str) -> None:
        """Every object, version and delete marker, then the bucket (the bootstrap bucket is versioned)."""
        for page in self.s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
            batch = [{"Key": v["Key"], "VersionId": v["VersionId"]}
                     for v in page.get("Versions", []) + page.get("DeleteMarkers", [])]
            for start in range(0, len(batch), 1000):
                self.s3.delete_objects(Bucket=bucket, Delete={"Objects": batch[start : start + 1000], "Quiet": True})
        self.s3.delete_bucket(Bucket=bucket)

    def bootstrap_bucket(self) -> str | None:
        try:
            resources = self.cfn.describe_stack_resources(StackName=BOOTSTRAP_STACK)["StackResources"]
        except self.cfn.exceptions.ClientError:
            return None
        return next((r["PhysicalResourceId"] for r in resources if r["ResourceType"] == "AWS::S3::Bucket"), None)


# ----------------------------------------------------------------------------- CDK
def cdk(args: list[str], env_extra: dict[str, str] | None = None) -> int:
    venv_bin = CDK_DIR / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    env = {**os.environ, "PATH": f"{venv_bin}{os.pathsep}{os.environ['PATH']}", **(env_extra or {})}
    env.setdefault("AWS_REGION", "us-east-1")
    npx = shutil.which("npx") or "npx"
    return subprocess.run([npx, "cdk", *args], cwd=CDK_DIR, env=env, check=False).returncode


def region() -> str:
    return os.environ.get("AWS_REGION") or "us-east-1"


# ----------------------------------------------------------------------------- commands
def cmd_status(account: Account) -> list[Item]:
    items = account.inventory()
    print(f"Account resources of this project in {account.region}:")
    print("\n".join(i.line() for i in items) if items else "  none")
    costing = [i for i in items if i.billable]
    print(f"\n{len(costing)} item(s) can cost money." if costing else "\nNothing that costs money is left.")
    return items


def cmd_up(account: Account, with_runtime: bool) -> int:
    if with_runtime:
        rc = subprocess.run([sys.executable, str(ROOT / "infra" / "runtime" / "build_zip.py")], check=False).returncode
        if rc:
            return rc
    stacks = ["FairTableData", "FairTableIdentity"] + (["FairTableRuntime", "FairTableGateway"] if with_runtime else [])
    if with_runtime and os.environ.get("NOTIFY_EMAIL"):
        stacks.insert(2, "FairTableNotify")  # the topic first: the Runtime reads its ARN
    if os.environ.get("BUDGET_EMAIL"):
        stacks.append(BUDGET_STACK)
    if with_runtime and os.environ.get("GATEWAY_POLICY"):
        # Two deploys (D-049): the permits first, so each forbid is validated against permits that are active.
        rc = cdk(["deploy", *stacks, "--require-approval", "never"], {"GATEWAY_POLICY_STAGE": "permits"})
        if rc:
            return rc
    rc = cdk(["deploy", *stacks, "--require-approval", "never"])
    if rc:
        return rc
    pool = next((i.name.split(" ")[0] for i in account.inventory() if i.kind == "pool"), None)
    if pool:
        rc = subprocess.run([sys.executable, str(ROOT / "scripts" / "cognito_users.py")],
                            env={**os.environ, "COGNITO_USER_POOL_ID": pool, "PYTHONPATH": str(ROOT)}, check=False).returncode
    return rc


def cmd_seed(account: Account) -> int:
    pool = next((i.name.split(" ")[0] for i in account.inventory() if i.kind == "pool"), None)
    if not pool:
        print("No Cognito pool: run `up` first (the demo data is keyed by Cognito's subs).", file=sys.stderr)
        return 2
    env = {**os.environ, "COGNITO_USER_POOL_ID": pool, "TABLE_NAME": account.table_name, "AWS_REGION": account.region,
           "DDB_ENDPOINT_URL": "", "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "seed.py")], env=env, check=False).returncode


def check_account(account: Account, confirm: str | None) -> bool:
    """With more than one account on the machine, a destructive run must name the account it means."""
    last4, _ = account.who()
    if confirm != last4:
        print(f"Refusing: this would run in the account ending {last4}. Add --account {last4} to confirm it is "
              "the right one.", file=sys.stderr)
        return False
    return True


def cmd_down(account: Account, *, yes: bool, include_budget: bool, include_bootstrap: bool,
             confirm: str | None = None) -> int:
    if yes and not check_account(account, confirm):
        return 2
    items = account.inventory()
    existing = {i.name for i in items if i.kind in ("stack", "bootstrap")}
    order = stack_order(existing, include_budget=include_budget, include_bootstrap=include_bootstrap)
    loose = strays(items, existing)
    print("Plan" + ("" if yes else " (dry run; add --yes to do it)") + ":")
    for s in order:
        print(f"  destroy stack {s}")
    for i in loose:
        print(f"  delete {i.kind} {i.name}")
    if any(i.kind == "setting" for i in items):
        print("  give the account's trace destination back to X-Ray")
    if include_bootstrap and BOOTSTRAP_STACK in existing:
        print("  empty and delete the CDK asset bucket, then the bootstrap stack")
    if not order and not loose and not any(i.kind == "setting" for i in items):
        print("  nothing to do")
    if not yes:
        return 0
    for s in order:
        if s == BOOTSTRAP_STACK:
            bucket = account.bootstrap_bucket()
            if bucket:
                account.empty_and_delete_bucket(bucket)
            account.cfn.delete_stack(StackName=s)
            account.cfn.get_waiter("stack_delete_complete").wait(StackName=s)
        elif cdk(["destroy", s, "--force"]):
            print(f"cdk destroy {s} failed", file=sys.stderr)
            return 1
    if any(i.kind == "setting" for i in items):  # before the span log groups go, so nothing refills them
        account.restore_trace_destination()
    for i in loose:  # leftovers that no stack owns (test tables, the service's own log groups)
        if i.kind == "table":
            account.delete_table(i.name)
        else:
            account.delete_log_group(i.name)
    left = billable_leftovers(account.inventory(), include_budget=include_budget, include_bootstrap=include_bootstrap)
    print("\nAfter teardown:")
    print("\n".join(i.line() for i in left) if left else "  nothing that costs money is left")
    return 1 if left else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    up = sub.add_parser("up")
    up.add_argument("--runtime", action="store_true", help="also build the package and deploy the Runtime stack")
    sub.add_parser("seed")
    down = sub.add_parser("down")
    down.add_argument("--yes", action="store_true", help="really do it (without it: a dry run)")
    down.add_argument("--include-budget", action="store_true")
    down.add_argument("--include-bootstrap", action="store_true")
    down.add_argument("--account", metavar="LAST4", help="last four digits of the account id; required with --yes")
    args = parser.parse_args(argv)

    account = Account(region(), os.environ.get("TABLE_NAME", "fairtable"))
    last4, kind = account.who()
    print(f"Account ending {last4} ({kind}), region {account.region}"
          + ("  <- the root user: prefer an IAM user" if kind == "root" else ""), file=sys.stderr)
    if args.command == "status":
        cmd_status(account)
        return 0
    if args.command == "up":
        return cmd_up(account, args.runtime)
    if args.command == "seed":
        return cmd_seed(account)
    return cmd_down(account, yes=args.yes, include_budget=args.include_budget,
                    include_bootstrap=args.include_bootstrap, confirm=args.account)


if __name__ == "__main__":
    sys.exit(main())
