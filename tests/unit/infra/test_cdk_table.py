"""P2-1: the table the CDK app deploys must match the one `server/store/table.py` creates locally.

The CDK app is synthesised with the interpreter of `infra/cdk/.venv` (aws-cdk-lib is not a runtime
dependency of the server). The test is skipped when that venv is not set up."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from server.store.table import create_table

CDK_DIR = Path(__file__).resolve().parents[3] / "infra" / "cdk"
VENV_PYTHON = next(
    (p for p in (CDK_DIR / ".venv" / "Scripts" / "python.exe", CDK_DIR / ".venv" / "bin" / "python") if p.exists()),
    None,
)
pytestmark = pytest.mark.skipif(VENV_PYTHON is None, reason="infra/cdk/.venv is not set up")


class CaptureClient:
    def __init__(self):
        self.kwargs = None

    def create_table(self, **kwargs):
        self.kwargs = kwargs

    def get_waiter(self, _name):
        return type("W", (), {"wait": staticmethod(lambda **_: None)})


@pytest.fixture(scope="module")
def templates(tmp_path_factory):
    out = tmp_path_factory.mktemp("cdk.out")
    env = {
        **os.environ,
        "CDK_OUTDIR": str(out),
        "CDK_DEFAULT_ACCOUNT": "123456789012",  # dummy, only so that synthesis has an environment
        "AWS_REGION": "us-east-1",
        "BUDGET_EMAIL": "alerts@example.com",
        "TABLE_NAME": "fairtable",
    }
    subprocess.run([str(VENV_PYTHON), "app.py"], cwd=CDK_DIR, env=env, check=True, capture_output=True, timeout=180)
    return {
        name: json.loads((out / f"{name}.template.json").read_text())
        for name in ("FairTableData", "FairTableBudget")
    }


def resources(template, kind):
    return [r for r in template["Resources"].values() if r["Type"] == kind]


def test_the_cdk_table_has_the_same_keys_and_indexes_as_the_local_table(templates):
    local = CaptureClient()
    create_table(local, "fairtable")
    (table,) = resources(templates["FairTableData"], "AWS::DynamoDB::Table")
    props = table["Properties"]

    def by_name(items):
        return {i["AttributeName"]: i["AttributeType"] for i in items}

    assert props["BillingMode"] == local.kwargs["BillingMode"]
    assert props["KeySchema"] == local.kwargs["KeySchema"]
    assert by_name(props["AttributeDefinitions"]) == by_name(local.kwargs["AttributeDefinitions"])
    assert sorted(props["GlobalSecondaryIndexes"], key=lambda g: g["IndexName"]) == sorted(
        local.kwargs["GlobalSecondaryIndexes"], key=lambda g: g["IndexName"]
    )


def test_the_table_is_tagged_and_removed_with_the_stack(templates):
    (table,) = resources(templates["FairTableData"], "AWS::DynamoDB::Table")
    assert {"Key": "project", "Value": "fairtable"} in table["Properties"]["Tags"]
    assert table["DeletionPolicy"] == "Delete"
    assert table["Properties"]["DeletionProtectionEnabled"] is False


def test_the_budget_alerts_at_50_100_140_on_gross_usage_not_net_of_credit(templates):
    (budget,) = resources(templates["FairTableBudget"], "AWS::Budgets::Budget")
    props = budget["Properties"]
    assert props["Budget"]["CostTypes"]["IncludeCredit"] is False  # the default (true) hides the spend
    assert props["Budget"]["BudgetLimit"] == {"Amount": 150, "Unit": "USD"}
    alerts = [n["Notification"] for n in props["NotificationsWithSubscribers"]]
    assert sorted(a["Threshold"] for a in alerts) == [50, 100, 140]
    assert {(a["NotificationType"], a["ThresholdType"], a["ComparisonOperator"]) for a in alerts} == {
        ("ACTUAL", "ABSOLUTE_VALUE", "GREATER_THAN")
    }
    assert props["NotificationsWithSubscribers"][0]["Subscribers"][0]["SubscriptionType"] == "EMAIL"


def test_the_budget_stack_is_only_created_when_an_address_is_given(tmp_path):
    env = {**os.environ, "CDK_OUTDIR": str(tmp_path), "CDK_DEFAULT_ACCOUNT": "123456789012", "AWS_REGION": "us-east-1"}
    env.pop("BUDGET_EMAIL", None)
    subprocess.run([str(VENV_PYTHON), "app.py"], cwd=CDK_DIR, env=env, check=True, capture_output=True, timeout=180)
    assert (tmp_path / "FairTableData.template.json").exists()
    assert not (tmp_path / "FairTableBudget.template.json").exists()


def test_no_account_id_is_stored_in_the_app():
    sources = [CDK_DIR / "app.py", *(CDK_DIR / "stacks").glob("*.py")]
    text = "".join(p.read_text() for p in sources)
    assert "123456789012" not in text and "448161422673" not in text
