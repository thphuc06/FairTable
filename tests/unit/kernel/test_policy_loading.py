"""P1-2: the policy loader rejects malformed or inconsistent policy sets at startup."""

import pytest

from server.kernel import PolicyLoadError, TrustKernel, default_policy_dir
from server.kernel.engine import PolicyBundle

SCHEMA = """
entity Diner;
entity Venue;
type Ctx = { n: Long };
action x appliesTo { principal: Diner, resource: Venue, context: Ctx };
"""


def load(text: str, schema: str = SCHEMA) -> PolicyBundle:
    return PolicyBundle("t", text, schema)


def test_real_policy_directory_loads_both_bundles():
    kernel = TrustKernel.load()
    assert len(kernel.pep1.bundle.rule_ids) == 4
    assert len(kernel.pep2.bundle.rule_ids) == 6
    assert default_policy_dir().name == "policies"


def test_missing_id_is_rejected():
    with pytest.raises(PolicyLoadError, match="@id"):
        load("permit (principal, action, resource);")


def test_duplicate_id_is_rejected():
    with pytest.raises(PolicyLoadError, match="duplicate"):
        load('@id("A") permit (principal, action, resource); @id("A") permit (principal, action, resource);')


def test_forbid_needs_on_deny():
    with pytest.raises(PolicyLoadError, match="on_deny"):
        load('@id("F") forbid (principal, action, resource);')


def test_forbid_with_unknown_on_deny_is_rejected():
    with pytest.raises(PolicyLoadError, match="on_deny"):
        load('@id("F") @on_deny("maybe") forbid (principal, action, resource);')


def test_permit_must_not_have_on_deny():
    with pytest.raises(PolicyLoadError, match="permit"):
        load('@id("P") @on_deny("deny") permit (principal, action, resource);')


def test_unparseable_text_is_rejected():
    with pytest.raises(PolicyLoadError, match="parse"):
        load("this is not cedar")


def test_empty_policy_set_is_rejected():
    with pytest.raises(PolicyLoadError, match="no policies"):
        load("// nothing here")


def test_typo_in_an_attribute_name_is_caught_by_schema_validation():
    typo = '@id("F") @on_deny("deny") forbid (principal, action, resource) when { context.m > 1 };'
    with pytest.raises(PolicyLoadError, match="schema validation"):
        load(typo)


def test_missing_policy_files_are_reported(tmp_path):
    (tmp_path / "pep1.cedarschema").write_text(SCHEMA)
    with pytest.raises(PolicyLoadError, match="no policy files"):
        PolicyBundle.from_dir("pep1", tmp_path, ("g*.cedar",), "pep1.cedarschema")


def test_only_matching_files_are_read(tmp_path):
    (tmp_path / "g1.cedar").write_text('@id("A") permit (principal, action, resource);')
    (tmp_path / "s1.cedar").write_text("not valid cedar at all")  # other bundle's file: ignored
    (tmp_path / "pep1.cedarschema").write_text(SCHEMA)
    bundle = PolicyBundle.from_dir("pep1", tmp_path, ("g*.cedar",), "pep1.cedarschema")
    assert bundle.rule_ids == {"A"}
