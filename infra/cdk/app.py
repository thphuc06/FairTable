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
from stacks.runtime_stack import RuntimeStack

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
    runtime = RuntimeStack(
        app,
        "FairTableRuntime",
        table=data.table,
        issuer=identity.pool.user_pool_provider_url,
        client_ids=client_ids,
        package_path=package,
        consent_base_url=os.environ.get("CONSENT_BASE_URL", "http://localhost:8080"),
        allowed_hosts=os.environ.get("MCP_ALLOWED_HOSTS"),
        env=env,
    )
    GatewayStack(
        app,
        "FairTableGateway",
        runtime=runtime.runtime,
        issuer=identity.pool.user_pool_provider_url,
        client_ids=client_ids,
        env=env,
    )

email = os.environ.get("BUDGET_EMAIL")
if email:
    limit = float(os.environ.get("BUDGET_LIMIT_USD", "150"))
    alerts = tuple(float(x) for x in os.environ.get("BUDGET_ALERTS", "50,100,140").split(",") if x.strip())
    BudgetStack(app, "FairTableBudget", email=email, limit_usd=limit, alerts_usd=alerts, env=env)

app.synth()
