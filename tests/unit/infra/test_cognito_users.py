"""P2-2: the script that fills the Cognito pool with the demo users, checked against a fake client."""

import importlib.util
import sys
from pathlib import Path

import pytest

from devauth.accounts import USERS

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # seed.py imports cognito_users as a sibling
    spec.loader.exec_module(module)
    return module


class UsernameExists(Exception):
    pass


class FakeCognito:
    class exceptions:  # noqa: N801 (boto3 exposes it like this)
        UsernameExistsException = UsernameExists

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.calls: list[tuple] = []

    def admin_create_user(self, UserPoolId, Username, UserAttributes, MessageAction):  # noqa: N803
        self.calls.append(("create", Username, MessageAction))
        if Username in self.users:
            raise UsernameExists()
        self.users[Username] = {"sub": f"uuid-{Username}", "attrs": {a["Name"]: a["Value"] for a in UserAttributes},
                                "groups": set(), "password": None, "permanent": False}

    def admin_update_user_attributes(self, UserPoolId, Username, UserAttributes):  # noqa: N803
        self.calls.append(("update", Username))
        self.users[Username]["attrs"].update({a["Name"]: a["Value"] for a in UserAttributes})

    def admin_set_user_password(self, UserPoolId, Username, Password, Permanent):  # noqa: N803
        self.users[Username].update(password=Password, permanent=Permanent)

    def admin_add_user_to_group(self, UserPoolId, Username, GroupName):  # noqa: N803
        self.users[Username]["groups"].add(GroupName)

    def admin_get_user(self, UserPoolId, Username):  # noqa: N803
        u = self.users[Username]
        return {"UserAttributes": [{"Name": "sub", "Value": u["sub"]}]}


def test_every_dev_user_is_created_with_a_permanent_password_and_no_email():
    mod, fake = load("cognito_users"), FakeCognito()
    subs = mod.ensure_users(fake, "pool")
    assert set(subs) == {u.username for u in USERS}
    for u in USERS:
        stored = fake.users[u.username]
        assert stored["password"] == u.password and stored["permanent"] is True
    assert {c[2] for c in fake.calls if c[0] == "create"} == {"SUPPRESS"}


def test_owners_get_their_group_and_venue_and_diners_get_neither():
    mod, fake = load("cognito_users"), FakeCognito()
    mod.ensure_users(fake, "pool")
    assert fake.users["owner-luna"]["groups"] == {"owners"}
    assert fake.users["owner-luna"]["attrs"] == {"custom:venue_id": "luna-trattoria"}
    assert fake.users["diner-alice"]["groups"] == set() and fake.users["diner-alice"]["attrs"] == {}


def test_running_twice_is_safe_and_keeps_the_same_subs():
    mod, fake = load("cognito_users"), FakeCognito()
    first = mod.ensure_users(fake, "pool")
    second = mod.ensure_users(fake, "pool")
    assert first == second and len(fake.users) == len(USERS)


def test_the_seed_uses_the_dev_subs_unless_a_pool_is_named():
    load("cognito_users")
    seed = load("seed")
    assert seed.subs_for_env({}) == seed.SUBS
    assert seed.SUBS["alice"] == "dev-alice"


def test_resolve_subs_reads_what_cognito_generated():
    mod, fake = load("cognito_users"), FakeCognito()
    mod.ensure_users(fake, "pool")
    assert mod.resolve_subs(fake, "pool", ["diner-bob"]) == {"diner-bob": "uuid-diner-bob"}


def test_the_script_refuses_to_run_without_a_pool(monkeypatch, capsys):
    mod = load("cognito_users")
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    assert mod.main() == 2
    assert "COGNITO_USER_POOL_ID" in capsys.readouterr().err


@pytest.mark.parametrize("user", USERS, ids=lambda u: u.username)
def test_dev_passwords_satisfy_the_pools_policy(user):
    assert len(user.password) >= 8  # the pool's minimum length (infra/cdk/stacks/identity_stack.py)
