"""P2-8: the deploy / inspect / teardown tool. Everything is checked with fake AWS clients: the tests never
touch an account."""

import importlib.util
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[3] / "infra" / "aws_ctl.py"
spec = importlib.util.spec_from_file_location("aws_ctl", PATH)
ctl = importlib.util.module_from_spec(spec)
sys.modules["aws_ctl"] = ctl
spec.loader.exec_module(ctl)

Item = ctl.Item


# ---------------------------------------------------------------------------------------- ownership
@pytest.mark.parametrize("name,ours", [
    ("fairtable", True), ("ft-test-abc123", True), ("ft-test-shared-1", True), ("ft-race-9", True),
    ("ft-seedscript-1f", True), ("someone-elses-table", False), ("fairtable-other", False), ("test", False),
])
def test_only_our_tables_are_ours(name, ours):
    assert ctl.table_is_ours(name, "fairtable") is ours


@pytest.mark.parametrize("name,ours", [
    ("/aws/bedrock-agentcore/runtimes/fairtable_mcp-AbC123-DEFAULT", True),
    ("/aws/lambda/FairTableIdentity-PreToken-XYZ", True),
    ("/aws/bedrock-agentcore/runtimes/other_agent-1-DEFAULT", False),
    ("/aws/lambda/some-other-function", False),
])
def test_only_our_log_groups_are_ours(name, ours):
    assert ctl.log_group_is_ours(name) is ours


# ---------------------------------------------------------------------------------------- planning
def test_stacks_are_destroyed_dependents_first_and_the_budget_and_bootstrap_only_when_asked():
    every = {"FairTableData", "FairTableIdentity", "FairTableRuntime", "FairTableGateway", "FairTableBudget",
             "CDKToolkit", "Other"}
    assert ctl.stack_order(every, include_budget=False, include_bootstrap=False) == [
        "FairTableGateway", "FairTableRuntime", "FairTableIdentity", "FairTableData"]
    assert ctl.stack_order(every, include_budget=True, include_bootstrap=True) == [
        "FairTableGateway", "FairTableRuntime", "FairTableIdentity", "FairTableData", "FairTableBudget", "CDKToolkit"]
    assert ctl.stack_order({"FairTableData"}, include_budget=False, include_bootstrap=False) == ["FairTableData"]


def test_a_stack_that_does_not_exist_is_not_in_the_plan():
    assert ctl.stack_order(set(), include_budget=True, include_bootstrap=True) == []


def test_strays_are_what_no_live_stack_will_remove():
    items = [
        Item("table", "fairtable", True, "stack:FairTableData"),
        Item("table", "ft-test-1", True, "direct"),
        Item("log-group", "/aws/bedrock-agentcore/runtimes/fairtable_mcp-1-DEFAULT", True, "direct"),
        Item("function", "FairTableIdentity-PreToken", False, "stack:FairTableIdentity"),
    ]
    assert [i.name for i in ctl.strays(items, {"FairTableData"})] == [
        "ft-test-1", "/aws/bedrock-agentcore/runtimes/fairtable_mcp-1-DEFAULT"]
    assert "fairtable" in [i.name for i in ctl.strays(items, set())]  # its stack is already gone: it is a stray


def test_the_budget_and_the_bootstrap_stack_are_not_leftovers_unless_they_were_to_go():
    items = [
        Item("budget", "fairtable-cap-150usd", False, "stack:FairTableBudget"),
        Item("bootstrap", "CDKToolkit", True, "direct"),
        Item("table", "fairtable", True, "stack:FairTableData"),
    ]
    assert [i.name for i in ctl.billable_leftovers(items, include_budget=False, include_bootstrap=False)] == ["fairtable"]
    assert [i.name for i in ctl.billable_leftovers(items, include_budget=True, include_bootstrap=True)] == [
        "CDKToolkit", "fairtable"]


def test_a_free_item_is_never_a_leftover():
    items = [Item("function", "FairTableIdentity-PreToken", False, "stack:FairTableIdentity")]
    assert ctl.billable_leftovers(items, include_budget=True, include_bootstrap=True) == []


# ---------------------------------------------------------------------------------------- the inventory
class FakePaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **_):
        return iter(self.pages)


class FakeClient:
    def __init__(self, **pages):
        self.pages = pages
        self.deleted = []
        self.exceptions = type("E", (), {"ClientError": Exception})

    def get_paginator(self, op):
        return FakePaginator(self.pages.get(op, []))

    def get_caller_identity(self):
        return {"Account": "123456789012"}


class FakeSession:
    def __init__(self, **clients):
        self.clients = clients

    def client(self, name):
        return self.clients.get(name, FakeClient())


def account(**clients):
    return ctl.Account("us-east-1", "fairtable", session=FakeSession(**clients))


def test_the_inventory_lists_ours_and_ignores_everything_else():
    acct = account(
        cloudformation=FakeClient(list_stacks=[{"StackSummaries": [
            {"StackName": "FairTableData"}, {"StackName": "SomebodyElsesStack"}, {"StackName": "CDKToolkit"}]}]),
        dynamodb=FakeClient(list_tables=[{"TableNames": ["fairtable", "ft-test-1", "orders", "users"]}]),
        **{"cognito-idp": FakeClient(list_user_pools=[{"UserPools": [
            {"Id": "us-east-1_abc", "Name": "fairtable-users"}, {"Id": "us-east-1_zzz", "Name": "prod-users"}]}])},
        **{"lambda": FakeClient(list_functions=[{"Functions": [
            {"FunctionName": "FairTableIdentity-PreToken-1"}, {"FunctionName": "billing-export"}]}])},
        secretsmanager=FakeClient(list_secrets=[{"SecretList": [
            {"Name": "FairTableRuntime-SlotTokenSecret-1"}, {"Name": "prod/db"},
            {"Name": "FairTableRuntime-SlotTokenSecret-old", "DeletedDate": "2026-09-30"}]}]),
        **{"bedrock-agentcore-control": FakeClient(
            list_agent_runtimes=[{"agentRuntimes": [
                {"agentRuntimeName": "fairtable_mcp", "agentRuntimeId": "fairtable_mcp-x1"},
                {"agentRuntimeName": "another_agent", "agentRuntimeId": "another_agent-y2"}]}],
            list_gateways=[{"items": [
                {"name": "fairtable-gw", "gatewayId": "fairtable-gw-abc"},
                {"name": "someone-elses-gateway", "gatewayId": "someone-elses-gateway-zzz"}]}],
            list_policy_engines=[{"policyEngines": [
                {"name": "fairtable_engine", "policyEngineId": "fairtable_engine-p1"},
                {"name": "other_engine", "policyEngineId": "other_engine-q2"}]}])},
        logs=FakeClient(describe_log_groups=[{"logGroups": [{"logGroupName": "/aws/lambda/FairTableIdentity-PreToken-1"}]}]),
        budgets=FakeClient(describe_budgets=[{"Budgets": [{"BudgetName": "fairtable-cap-150usd"},
                                                          {"BudgetName": "fairtable-5usd"}]}]),
        sts=FakeClient(),
    )
    names = sorted(i.name for i in acct.inventory())
    assert "SomebodyElsesStack" not in names and "orders" not in names and "users" not in names
    assert "us-east-1_zzz (prod-users)" not in names and "billing-export" not in names and "prod/db" not in names
    assert "another_agent another_agent-y2" not in names and "FairTableRuntime-SlotTokenSecret-old" not in names
    assert "fairtable-5usd" not in names  # the developer's own alarm is never ours to touch
    assert {"FairTableData", "CDKToolkit", "fairtable", "ft-test-1", "us-east-1_abc (fairtable-users)",
            "FairTableIdentity-PreToken-1", "FairTableRuntime-SlotTokenSecret-1",
            "fairtable_mcp fairtable_mcp-x1", "fairtable-gw fairtable-gw-abc", "fairtable-cap-150usd",
            "fairtable_engine fairtable_engine-p1"} <= set(names)
    assert "other_engine other_engine-q2" not in names
    assert "someone-elses-gateway someone-elses-gateway-zzz" not in names


# ---------------------------------------------------------------------------------------- down
class FakeAccount:
    def who(self):
        return "1905", "user"

    def __init__(self, items, after=None):
        self._items, self._after = items, after
        self.calls = []
        self.region, self.table_name = "us-east-1", "fairtable"
        self._inventories = 0

    def inventory(self):
        self._inventories += 1
        return self._items if self._inventories == 1 or self._after is None else self._after

    def delete_table(self, name):
        self.calls.append(("delete_table", name))

    def delete_log_group(self, name):
        self.calls.append(("delete_log_group", name))

    def bootstrap_bucket(self):
        return "bucket"

    def empty_and_delete_bucket(self, bucket):
        self.calls.append(("empty_bucket", bucket))

    class cfn:  # noqa: N801
        @staticmethod
        def delete_stack(**_):
            pass

        @staticmethod
        def get_waiter(_):
            return type("W", (), {"wait": staticmethod(lambda **_: None)})


FULL = [
    Item("stack", "FairTableRuntime", False, "direct"),
    Item("stack", "FairTableIdentity", False, "direct"),
    Item("stack", "FairTableData", False, "direct"),
    Item("table", "fairtable", True, "stack:FairTableData"),
    Item("table", "ft-test-left-over", True, "direct"),
    Item("log-group", "/aws/bedrock-agentcore/runtimes/fairtable_mcp-1-DEFAULT", True, "direct"),
]


def test_down_without_yes_changes_nothing_and_prints_the_plan(monkeypatch, capsys):
    destroyed = []
    monkeypatch.setattr(ctl, "cdk", lambda args, env_extra=None: destroyed.append(args) or 0)
    acct = FakeAccount(FULL)
    assert ctl.cmd_down(acct, yes=False, include_budget=False, include_bootstrap=False) == 0
    out = capsys.readouterr().out
    assert "dry run" in out and "destroy stack FairTableRuntime" in out and "delete table ft-test-left-over" in out
    assert destroyed == [] and acct.calls == []


def test_down_destroys_stacks_in_order_then_removes_what_they_leave(monkeypatch, capsys):
    destroyed = []
    monkeypatch.setattr(ctl, "cdk", lambda args, env_extra=None: destroyed.append(args[1]) or 0)
    acct = FakeAccount(FULL, after=[])
    assert ctl.cmd_down(acct, yes=True, include_budget=False, include_bootstrap=False, confirm="1905") == 0
    assert destroyed == ["FairTableRuntime", "FairTableIdentity", "FairTableData"]
    assert ("delete_table", "ft-test-left-over") in acct.calls
    assert ("delete_table", "fairtable") not in acct.calls  # the stack removes its own table
    assert ("delete_log_group", "/aws/bedrock-agentcore/runtimes/fairtable_mcp-1-DEFAULT") in acct.calls
    assert "nothing that costs money is left" in capsys.readouterr().out


def test_down_reports_failure_when_something_that_costs_money_is_left(monkeypatch, capsys):
    monkeypatch.setattr(ctl, "cdk", lambda args, env_extra=None: 0)
    still = [Item("table", "ft-test-left-over", True, "direct")]
    assert ctl.cmd_down(FakeAccount(FULL, after=still), yes=True, include_budget=False, include_bootstrap=False,
                        confirm="1905") == 1
    assert "ft-test-left-over" in capsys.readouterr().out


def test_down_stops_at_the_first_failed_destroy(monkeypatch):
    calls = []

    def fail_first(args, env_extra=None):
        calls.append(args[1])
        return 1

    monkeypatch.setattr(ctl, "cdk", fail_first)
    acct = FakeAccount(FULL, after=[])
    assert ctl.cmd_down(acct, yes=True, include_budget=False, include_bootstrap=False, confirm="1905") == 1
    assert calls == ["FairTableRuntime"] and acct.calls == []  # nothing else was touched


def test_the_bootstrap_bucket_is_emptied_before_its_stack_goes(monkeypatch):
    monkeypatch.setattr(ctl, "cdk", lambda args, env_extra=None: 0)
    items = [Item("bootstrap", "CDKToolkit", True, "direct")]
    acct = FakeAccount(items, after=[])
    assert ctl.cmd_down(acct, yes=True, include_budget=False, include_bootstrap=True, confirm="1905") == 0
    assert acct.calls == [("empty_bucket", "bucket")]


def test_the_bootstrap_stack_is_left_alone_by_default(monkeypatch):
    monkeypatch.setattr(ctl, "cdk", lambda args, env_extra=None: 0)
    items = [Item("bootstrap", "CDKToolkit", True, "direct")]
    acct = FakeAccount(items)
    assert ctl.cmd_down(acct, yes=True, include_budget=False, include_bootstrap=False, confirm="1905") == 0
    assert acct.calls == []


def test_seed_needs_the_cognito_pool(capsys):
    acct = FakeAccount([])
    assert ctl.cmd_seed(acct) == 2
    assert "run `up` first" in capsys.readouterr().err


def test_a_destructive_run_must_name_the_account(monkeypatch, capsys):
    destroyed = []
    monkeypatch.setattr(ctl, "cdk", lambda args, env_extra=None: destroyed.append(args) or 0)
    acct = FakeAccount(FULL)
    assert ctl.cmd_down(acct, yes=True, include_budget=False, include_bootstrap=False) == 2
    assert ctl.cmd_down(acct, yes=True, include_budget=False, include_bootstrap=False, confirm="0000") == 2
    assert "ending 1905" in capsys.readouterr().err
    assert destroyed == [] and acct.calls == []  # nothing was touched in the wrong account


def test_a_dry_run_needs_no_confirmation(monkeypatch):
    monkeypatch.setattr(ctl, "cdk", lambda args, env_extra=None: 1 / 0)
    assert ctl.cmd_down(FakeAccount(FULL), yes=False, include_budget=False, include_bootstrap=False) == 0


@pytest.mark.parametrize("arn,kind", [
    ("arn:aws:iam::123456789012:root", "root"),
    ("arn:aws:iam::123456789012:user/phuc", "user"),
    ("arn:aws:sts::123456789012:assumed-role/Admin/session", "role"),
])
def test_who_tells_root_user_and_role_apart(arn, kind):
    class Sts:
        @staticmethod
        def get_caller_identity():
            return {"Account": "123456789012", "Arn": arn}

    acct = ctl.Account("us-east-1", "fairtable", session=FakeSession(sts=Sts()))
    assert acct.who() == ("9012", kind)
