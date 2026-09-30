#!/usr/bin/env python3
"""FairTable AWS profile (Phase 2). Nothing account-specific lives here.

Account and region come from the CLI credentials (`AWS_PROFILE`, `AWS_REGION`), the table name
from `TABLE_NAME`, the alert address from `BUDGET_EMAIL`. Without `BUDGET_EMAIL` the budget
stack is not created.
"""

import os

import aws_cdk as cdk

from stacks.budget_stack import BudgetStack
from stacks.data_stack import DataStack

app = cdk.App()
env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("AWS_REGION") or os.environ.get("CDK_DEFAULT_REGION"),
)

DataStack(app, "FairTableData", table_name=os.environ.get("TABLE_NAME", "fairtable"), env=env)

email = os.environ.get("BUDGET_EMAIL")
if email:
    BudgetStack(app, "FairTableBudget", email=email, env=env)

app.synth()
