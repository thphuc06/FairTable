"""P2-1: the table the CDK app deploys must match the one `server/store/table.py` creates locally.

The CDK app is synthesised with the interpreter of `infra/cdk/.venv` (aws-cdk-lib is not a runtime
dependency of the server). The test is skipped when that venv is not set up."""

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from devauth.accounts import CLIENTS, CLIENTS_BY_ID, SCOPE_BOOK
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
    package = tmp_path_factory.mktemp("pkg") / "fairtable-runtime.zip"
    with zipfile.ZipFile(package, "w") as z:
        z.writestr("runtime_entry.py", "print('stand-in for the real package')")
    env = {
        **os.environ,
        "RUNTIME_ZIP": str(package),
        "CDK_OUTDIR": str(out),
        "CDK_DEFAULT_ACCOUNT": "123456789012",  # dummy, only so that synthesis has an environment
        "AWS_REGION": "us-east-1",
        "BUDGET_EMAIL": "alerts@example.com",
        "TABLE_NAME": "fairtable",
    }
    subprocess.run([str(VENV_PYTHON), "app.py"], cwd=CDK_DIR, env=env, check=True, capture_output=True, timeout=180)
    return {
        name: json.loads((out / f"{name}.template.json").read_text())
        for name in ("FairTableData", "FairTableBudget", "FairTableIdentity", "FairTableRuntime")
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
    assert props["Budget"]["BudgetName"] == "fairtable-cap-150usd"  # never the name of a budget made by hand
    alerts = [n["Notification"] for n in props["NotificationsWithSubscribers"]]
    assert sorted(a["Threshold"] for a in alerts) == [50, 100, 140]
    assert {(a["NotificationType"], a["ThresholdType"], a["ComparisonOperator"]) for a in alerts} == {
        ("ACTUAL", "ABSOLUTE_VALUE", "GREATER_THAN")
    }
    assert props["NotificationsWithSubscribers"][0]["Subscribers"][0]["SubscriptionType"] == "EMAIL"


def test_the_budget_stack_is_only_created_when_an_address_is_given(tmp_path):
    env = {**os.environ, "CDK_OUTDIR": str(tmp_path), "CDK_DEFAULT_ACCOUNT": "123456789012", "AWS_REGION": "us-east-1",
           "RUNTIME_ZIP": str(tmp_path / "missing.zip")}
    env.pop("BUDGET_EMAIL", None)
    subprocess.run([str(VENV_PYTHON), "app.py"], cwd=CDK_DIR, env=env, check=True, capture_output=True, timeout=180)
    assert (tmp_path / "FairTableData.template.json").exists()
    assert not (tmp_path / "FairTableBudget.template.json").exists()


def test_no_account_id_is_stored_in_the_app():
    sources = [CDK_DIR / "app.py", *(CDK_DIR / "stacks").glob("*.py")]
    text = "".join(p.read_text() for p in sources)
    assert "123456789012" not in text and "448161422673" not in text


def by_name(template, kind, field):
    return {r["Properties"][field]: r["Properties"] for r in resources(template, kind)}


def test_the_user_pool_is_essentials_with_the_v3_pre_token_trigger_and_no_self_sign_up(templates):
    (pool,) = resources(templates["FairTableIdentity"], "AWS::Cognito::UserPool")
    props = pool["Properties"]
    assert props["UserPoolTier"] == "ESSENTIALS"  # V3_0 events (machine tokens) need Essentials or Plus
    assert props["LambdaConfig"]["PreTokenGenerationConfig"]["LambdaVersion"] == "V3_0"
    assert props["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True
    assert props["DeletionProtection"] == "INACTIVE" and pool["DeletionPolicy"] == "Delete"
    assert [a["Name"] for a in props["Schema"]] == ["venue_id"]  # becomes `custom:venue_id`


def test_the_app_clients_are_the_dev_issuers_clients(templates):
    clients = by_name(templates["FairTableIdentity"], "AWS::Cognito::UserPoolClient", "ClientName")
    assert set(clients) == set(CLIENTS_BY_ID)
    for c in CLIENTS:
        props = clients[c.client_id]
        assert bool(props.get("GenerateSecret")) == (c.secret is not None)
        user_flow = "ALLOW_USER_PASSWORD_AUTH" in props.get("ExplicitAuthFlows", [])
        assert user_flow == ("password" in c.grants)
        assert ("client_credentials" in (props.get("AllowedOAuthFlows") or [])) == ("client_credentials" in c.grants)


def test_the_machine_only_client_has_no_user_sign_in_flow_and_the_agent_has_no_oauth_sign_in(templates):
    clients = by_name(templates["FairTableIdentity"], "AWS::Cognito::UserPoolClient", "ClientName")
    assert clients["bot-m2m"]["ExplicitAuthFlows"] == ["ALLOW_REFRESH_TOKEN_AUTH"]
    assert clients["shady-agent"]["AllowedOAuthFlowsUserPoolClient"] is False


def test_the_booking_scope_is_fairtable_book(templates):
    (server,) = resources(templates["FairTableIdentity"], "AWS::Cognito::UserPoolResourceServer")
    assert f"{server['Properties']['Identifier']}/{server['Properties']['Scopes'][0]['ScopeName']}" == SCOPE_BOOK


def test_the_trigger_function_may_only_describe_user_pool_clients(templates):
    identity = templates["FairTableIdentity"]
    statements = [s for p in resources(identity, "AWS::IAM::Policy") for s in p["Properties"]["PolicyDocument"]["Statement"]]
    assert [s["Action"] for s in statements] == ["cognito-idp:DescribeUserPoolClient"]
    (fn,) = resources(identity, "AWS::Lambda::Function")
    assert fn["Properties"]["Runtime"] == "python3.12" and fn["Properties"]["Handler"] == "handler.lambda_handler"


def test_the_owners_group_exists(templates):
    (group,) = resources(templates["FairTableIdentity"], "AWS::Cognito::UserPoolGroup")
    assert group["Properties"]["GroupName"] == "owners"


def runtime_of(templates):
    (runtime,) = resources(templates["FairTableRuntime"], "AWS::BedrockAgentCore::Runtime")
    return runtime["Properties"]


def test_the_runtime_is_an_mcp_server_from_a_python_zip_on_v2_with_a_public_network(templates):
    props = runtime_of(templates)
    assert props["AgentRuntimeName"] == "fairtable_mcp"  # the name pattern allows no hyphen
    assert props["ProtocolConfiguration"] == "MCP"
    assert props["PlatformVersion"] == "V2"
    assert props["NetworkConfiguration"] == {"NetworkMode": "PUBLIC"}
    code = props["AgentRuntimeArtifact"]["CodeConfiguration"]
    assert (code["Runtime"], code["EntryPoint"]) == ("PYTHON_3_12", ["runtime_entry.py"])
    assert "ContainerConfiguration" not in props["AgentRuntimeArtifact"]  # no Docker, no ECR
    assert "AuthorizerConfiguration" not in props  # IAM (SigV4) callers only; the Gateway is one (P2-5)


def test_only_the_user_token_header_reaches_the_server_and_idle_sessions_end_quickly(templates):
    props = runtime_of(templates)
    assert props["RequestHeaderConfiguration"] == {"RequestHeaderAllowlist": ["x-ft-user-token"]}
    life = props["LifecycleConfiguration"]
    assert 60 <= life["IdleRuntimeSessionTimeout"] <= 120  # idle time is billed (D-035)
    assert life["MaxLifetime"] >= life["IdleRuntimeSessionTimeout"]


def test_the_runtime_is_configured_like_the_aws_profile_expects(templates):
    env = runtime_of(templates)["EnvironmentVariables"]
    assert env["AUTH_AUDIENCE_CLAIM"] == "client_id" and env["AUTH_TOKEN_USE"] == "access"
    assert set(env) >= {"TABLE_NAME", "AUTH_ISSUER", "AUTH_JWKS_URL", "AUTH_AUDIENCE", "SLOT_TOKEN_SECRET", "CONSENT_BASE_URL"}
    assert "MCP_ALLOWED_HOSTS" not in env  # only set on request
    assert "resolve:secretsmanager" in json.dumps(env["SLOT_TOKEN_SECRET"])  # the secret is never a literal


def test_the_slot_secret_is_generated_not_written_down(templates):
    (secret,) = resources(templates["FairTableRuntime"], "AWS::SecretsManager::Secret")
    assert secret["Properties"]["GenerateSecretString"]["PasswordLength"] >= 32


def test_the_execution_role_is_assumed_only_by_agentcore_of_this_account(templates):
    (role,) = resources(templates["FairTableRuntime"], "AWS::IAM::Role")
    (statement,) = role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert set(statement["Condition"]) == {"StringEquals", "ArnLike"}


def test_the_execution_role_can_do_what_the_store_does_and_nothing_more(templates):
    statements = [s for p in resources(templates["FairTableRuntime"], "AWS::IAM::Policy")
                  for s in p["Properties"]["PolicyDocument"]["Statement"]]
    actions = {a for s in statements for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])}
    assert "dynamodb:Scan" not in actions and "dynamodb:BatchWriteItem" not in actions
    assert not {a for a in actions if a.startswith(("bedrock:", "s3:", "ecr:", "iam:", "secretsmanager:"))}
    assert not {a for a in actions if a.endswith("*")}  # no wildcard actions
    (ddb,) = [s for s in statements if "dynamodb:GetItem" in s["Action"]]
    assert "dynamodb:ConditionCheckItem" in ddb["Action"]  # conditions inside TransactWriteItems need it


def test_the_runtime_waits_for_its_role_and_policy(templates):
    (runtime,) = resources(templates["FairTableRuntime"], "AWS::BedrockAgentCore::Runtime")
    assert any("ExecutionRoleDefaultPolicy" in d for d in runtime["DependsOn"])


def test_the_runtime_stack_needs_a_built_package(tmp_path):
    env = {**os.environ, "CDK_OUTDIR": str(tmp_path), "CDK_DEFAULT_ACCOUNT": "123456789012", "AWS_REGION": "us-east-1",
           "RUNTIME_ZIP": str(tmp_path / "missing.zip")}
    subprocess.run([str(VENV_PYTHON), "app.py"], cwd=CDK_DIR, env=env, check=True, capture_output=True, timeout=180)
    assert not (tmp_path / "FairTableRuntime.template.json").exists()


def synth_budget(tmp_path, **extra):
    env = {**os.environ, "CDK_OUTDIR": str(tmp_path), "CDK_DEFAULT_ACCOUNT": "123456789012", "AWS_REGION": "us-east-1",
           "RUNTIME_ZIP": str(tmp_path / "missing.zip"), "BUDGET_EMAIL": "alerts@example.com", **extra}
    return subprocess.run([str(VENV_PYTHON), "app.py"], cwd=CDK_DIR, env=env, capture_output=True, timeout=180, text=True)


def test_a_small_account_can_set_a_five_dollar_budget(tmp_path):
    run = synth_budget(tmp_path, BUDGET_LIMIT_USD="5", BUDGET_ALERTS="1,3,4.5")
    assert run.returncode == 0, run.stderr[-500:]
    template = json.loads((tmp_path / "FairTableBudget.template.json").read_text())
    (budget,) = resources(template, "AWS::Budgets::Budget")
    props = budget["Properties"]
    assert props["Budget"]["BudgetName"] == "fairtable-cap-5usd"
    assert props["Budget"]["BudgetLimit"] == {"Amount": 5, "Unit": "USD"}
    assert sorted(n["Notification"]["Threshold"] for n in props["NotificationsWithSubscribers"]) == [1, 3, 4.5]
    assert props["Budget"]["CostTypes"]["IncludeCredit"] is False


@pytest.mark.parametrize("alerts", ["6", "0,2", "3,1", "2,2", "-1"])
def test_alerts_that_do_not_fit_the_limit_are_refused(tmp_path, alerts):
    run = synth_budget(tmp_path, BUDGET_LIMIT_USD="5", BUDGET_ALERTS=alerts)
    assert run.returncode != 0 and "alerts" in run.stderr
