#!/usr/bin/env python3
"""FairTable AWS profile (Phase 2). Nothing account-specific lives here.

Account and region come from the CLI credentials (`AWS_PROFILE`, `AWS_REGION`), the table name
from `TABLE_NAME`, the alert address from `BUDGET_EMAIL`, the limit and the alert levels from `BUDGET_LIMIT_USD` (default 150) and `BUDGET_ALERTS` (default `50,100,140`). Without `BUDGET_EMAIL` the budget
stack is not created.
"""

import os
from pathlib import Path

import aws_cdk as cdk

from stacks.budget_stack import BudgetStack
from stacks.data_stack import DataStack
from stacks.gateway_stack import GatewayStack
from stacks.identity_stack import IdentityStack
from stacks.notify_stack import NotifyStack
from stacks.observability_stack import ObservabilityStack
from stacks.owner_web_stack import OwnerWebStack
from stacks.runtime_stack import RuntimeStack
from stacks.workers_stack import WorkersStack

app = cdk.App()
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("AWS_REGION") or os.environ.get("CDK_DEFAULT_REGION"),
)

data = DataStack(app, "FairTableData", table_name=os.environ.get("TABLE_NAME", "fairtable"), env=env)

identity = IdentityStack(app, "FairTableIdentity", domain_prefix=os.environ.get("COGNITO_DOMAIN_PREFIX"), env=env)

# The runtime package is built first: python infra/runtime/build_zip.py (see infra/runtime/README.md).
package = Path(os.environ.get("RUNTIME_ZIP") or Path(__file__).resolve().parents[2] / "dist" / "fairtable-runtime.zip")
if package.exists():
    client_ids = [c.user_pool_client_id for c in identity.clients.values()]
    notify = None
    if os.environ.get("NOTIFY_EMAIL"):  # the one address that gets the notices (D-054); never written to the repo
        notify = NotifyStack(app, "FairTableNotify", email=os.environ["NOTIFY_EMAIL"], env=env)
    runtime = RuntimeStack(
        app,
        "FairTableRuntime",
        table=data.table,
        issuer=identity.pool.user_pool_provider_url,
        client_ids=client_ids,
        package_path=package,
        allowed_hosts=os.environ.get("MCP_ALLOWED_HOSTS"),
        stateless=os.environ.get("RUNTIME_STATELESS", "true").lower() != "false",
        notify_topic=notify.topic if notify else None,
        audit_bucket=data.audit_bucket,
        env=env,
    )
    if os.environ.get("WORKERS", "true").lower() != "false":  # the hold sweeper and the Fair Drop allocator (D-062)
        WorkersStack(
            app,
            "FairTableWorkers",
            table=data.table,
            environment=runtime.worker_environment,
            package_path=package,
            notify_topic=notify.topic if notify else None,
            audit_bucket=data.audit_bucket,
            every_minutes=int(os.environ.get("WORKERS_EVERY_MINUTES", "1")),
            env=env,
        )
    if os.environ.get("OWNER_WEB", "").lower() == "true":  # opt-in: the owner console on Lambda and an HTTP API (D-068)
        OwnerWebStack(
            app,
            "FairTableOwnerWeb",
            table=data.table,
            issuer=identity.pool.user_pool_provider_url,
            sign_in_client=identity.clients["alexa-plus-sim"],
            package_path=package,
            env=env,
        )
    gateway = GatewayStack(
        app,
        "FairTableGateway",
        runtime=runtime.runtime,
        issuer=identity.pool.user_pool_provider_url,
        client_ids=client_ids,
        sessions=os.environ.get("GATEWAY_SESSIONS", "false").lower() == "true",
        streaming=os.environ.get("GATEWAY_STREAMING", "false").lower() == "true",
        policy_mode=os.environ.get("GATEWAY_POLICY") or None,  # LOG_ONLY | ENFORCE; unset = no policy engine
        permits_only=os.environ.get("GATEWAY_POLICY_STAGE") == "permits",  # first of two deploys (D-049)
        env=env,
    )
    if os.environ.get("OBSERVABILITY", "").lower() == "true":  # opt-in (P2-9, D-050)
        ObservabilityStack(
            app,
            "FairTableObservability",
            gateway=gateway.gateway,
            # tracing for the Runtime is an experiment (no documented API): its own switch
            runtime=runtime.runtime if os.environ.get("OBSERVABILITY_RUNTIME", "").lower() == "true" else None,
            env=env,
        )

email =os.environ.get("BUDGET_EMAIL")
if email:
    limit = float(os.environ.get("BUDGET_LIMIT_USD", "150"))
    alerts = tuple(float(x) for x in os.environ.get("BUDGET_ALERTS", "50,100,140").split(",") if x.strip())
    BudgetStack(app, "FairTableBudget", email=email, limit_usd=limit, alerts_usd=alerts, env=env)

app.synth()
