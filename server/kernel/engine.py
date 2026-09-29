"""Cedar policy bundle: load, validate, evaluate, and turn cedarpy reasons into decisions.

Verified against cedarpy 4.12.1 (docs/PLAN.md section 3a): reasons come back as ``policyN`` where N is
the index of the policy in the exact text that was parsed, so the ``policyN -> (@id, @on_deny)``
table is built from that same text through ``policies_to_json_str``, never by position in a file.

Priority: deny > step_up > allow. No matching permit is a deny (``no_permit``). Any evaluation
error is a deny too (``policy_error``): a Cedar forbid whose condition errors is skipped, which
would otherwise let a permit win (design section 6.1).
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import cedarpy

NO_PERMIT = "no_permit"
POLICY_ERROR = "policy_error"
ON_DENY_VALUES = frozenset({"deny", "step_up"})


class PolicyLoadError(Exception):
    """A policy file is malformed, inconsistent, or fails schema validation. Startup must stop."""


class DecisionKind(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    STEP_UP = "step_up"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    rule_ids: tuple[str, ...]
    source: str  # bundle name: "pep1" or "pep2"
    errors: tuple[str, ...] = ()  # Cedar evaluation errors, server-side only

    @property
    def rule_id(self) -> str | None:
        return self.rule_ids[0] if self.rule_ids else None

    @property
    def allowed(self) -> bool:
        return self.kind is DecisionKind.ALLOW


@dataclass(frozen=True)
class Rule:
    policy_id: str  # cedarpy's "policyN"
    rule_id: str  # @id
    effect: str  # "permit" | "forbid"
    on_deny: str | None  # @on_deny, forbid only


def _parse_rules(text: str) -> dict[str, Rule]:
    try:
        parsed = json.loads(cedarpy.policies_to_json_str(text))
    except ValueError as e:
        raise PolicyLoadError(f"cannot parse policies: {e}") from e
    if parsed.get("templates"):
        raise PolicyLoadError("policy templates are not supported")
    rules: dict[str, Rule] = {}
    seen: set[str] = set()
    for policy_id, pol in parsed["staticPolicies"].items():
        ann = pol.get("annotations", {})
        rule_id = ann.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise PolicyLoadError(f"{policy_id}: every policy needs a non-empty @id")
        if rule_id in seen:
            raise PolicyLoadError(f"duplicate @id {rule_id!r}")
        seen.add(rule_id)
        effect = pol["effect"]
        on_deny = ann.get("on_deny")
        if effect == "forbid" and on_deny not in ON_DENY_VALUES:
            raise PolicyLoadError(f"{rule_id}: forbid needs @on_deny(\"deny\"|\"step_up\")")
        if effect == "permit" and on_deny is not None:
            raise PolicyLoadError(f"{rule_id}: permit must not have @on_deny")
        rules[policy_id] = Rule(policy_id, rule_id, effect, on_deny)
    if not rules:
        raise PolicyLoadError("no policies found")
    return rules


class PolicyBundle:
    def __init__(self, name: str, text: str, schema_text: str) -> None:
        self.name = name
        self.text = text
        self._rules = _parse_rules(text)
        validation = cedarpy.validate_policies(text, schema_text)
        if not validation.validation_passed:
            problems = "; ".join(str(e) for e in validation.errors)
            raise PolicyLoadError(f"{name}: schema validation failed: {problems}")
        self._policy_set = cedarpy.PolicySet.from_str(text)

    @classmethod
    def from_dir(
        cls, name: str, directory: Path, patterns: Iterable[str], schema_file: str
    ) -> "PolicyBundle":
        files = sorted({f for pattern in patterns for f in directory.glob(pattern)})
        if not files:
            raise PolicyLoadError(f"{name}: no policy files in {directory} for {list(patterns)}")
        text = "\n".join(f.read_text(encoding="utf-8") for f in files)
        schema_text = (directory / schema_file).read_text(encoding="utf-8")
        return cls(name, text, schema_text)

    @property
    def rule_ids(self) -> frozenset[str]:
        return frozenset(r.rule_id for r in self._rules.values())

    def evaluate(self, request: dict[str, Any], entities: list[dict[str, Any]]) -> Decision:
        result = cedarpy.is_authorized(request, self._policy_set, entities)
        errors = tuple(result.diagnostics.errors)
        matched = [self._rules.get(r) for r in result.diagnostics.reasons]
        if errors or any(m is None for m in matched):
            return Decision(DecisionKind.DENY, (POLICY_ERROR,), self.name, errors)
        rules: list[Rule] = [m for m in matched if m is not None]
        if result.allowed:
            return Decision(DecisionKind.ALLOW, tuple(sorted(r.rule_id for r in rules)), self.name)
        if not rules:
            return Decision(DecisionKind.DENY, (NO_PERMIT,), self.name)
        denies = sorted(r.rule_id for r in rules if r.on_deny == "deny")
        if denies:
            return Decision(DecisionKind.DENY, tuple(denies), self.name)
        return Decision(
            DecisionKind.STEP_UP,
            tuple(sorted(r.rule_id for r in rules if r.on_deny == "step_up")),
            self.name,
        )
