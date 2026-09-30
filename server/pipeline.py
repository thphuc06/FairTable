"""The write pipeline (design section 6, diagram): every state-changing tool goes through here.

    identity  ->  PEP-1  ->  idempotency lookup  ->  facts  ->  PEP-2  ->  ONE transaction

* Cedar decides; the DynamoDB conditions inside the transaction are the final guarantee under
  concurrency (docs/DECISIONS.md D-008).
* The transaction holds the tool's own changes plus the idempotency record and the audit entry, so
  a stored key always means "this really happened". Denied, step-up and failed calls store no key.
* Business code stays in the operation objects (one per tool, added in batch C); this module only
  orders the steps.
"""

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from server.domain.audit import AuditEntry
from server.domain.clock import iso_z
from server.domain.errors import ErrorCode, FairTableError
from server.domain.idempotency import (
    IdempotencyRecord,
    conflict,
    is_replay,
    params_hash,
    validate_key,
)
from server.domain.models import Identity
from server.domain.tool_names import ToolName
from server.kernel import Decision, DecisionKind, PolicyContext, VenueRef, deny_to_error
from server.store import Store, TransactionCancelled, TxOp
from server.telemetry import annotate, annotate_decision
from server.tools.common import AppDeps

log = logging.getLogger("fairtable.pipeline")


@dataclass(frozen=True)
class WriteFacts:
    """What Cedar needs, read from the store by the operation."""

    venue: VenueRef
    ctx: PolicyContext


@dataclass(frozen=True)
class WritePlan:
    ops: list[TxOp]  # the tool's own conditional writes
    result: dict[str, Any]  # what the agent gets back (stored with the idempotency record)
    audit_detail: dict[str, Any]


class WriteOperation(Protocol):
    tool: ToolName
    venue_id: str
    party_size: int  # 0 when the tool carries none (input to PEP-1 rule G3)

    def params(self) -> dict[str, Any]:
        """The parameters that define 'the same request' for idempotency."""

    def load_facts(self, store: Store, identity: Identity, now_iso: str) -> WriteFacts: ...

    def plan(self, store: Store, identity: Identity, now_iso: str, decision: Decision) -> WritePlan:
        ...

    def approval_request(self):
        """What the user must approve when PEP-2 asks for step-up (a consent.ApprovalRequest)."""

    def explain_cancel(self, failed: list[int], exc: TransactionCancelled) -> FairTableError:
        """Turn 'operation i failed' (indexes into ``plan().ops``) into SLOT_TAKEN, POLICY_DENIED..."""


class StepUpRequired(Exception):
    """PEP-2 says the user must approve first. The tool layer turns this into -32042 or a
    ``consent_url`` result (docs/DECISIONS.md D-016)."""

    def __init__(self, decision: Decision, op: WriteOperation, identity: Identity) -> None:
        super().__init__(f"step-up required by {', '.join(decision.rule_ids)}")
        self.decision = decision
        self.op = op
        self.identity = identity


def _iso(deps: AppDeps) -> str:
    return iso_z(deps.clock.now())


def _audit(deps: AppDeps, identity: Identity, op: WriteOperation, decision: str,
           rule_ids: tuple[str, ...], detail: dict[str, Any] | None = None) -> AuditEntry:
    return AuditEntry(
        venue_id=op.venue_id, timestamp=_iso(deps), request_id=deps.new_id(), sub=identity.sub,
        agent_id=identity.agent_id, tool=op.tool.value, decision=decision, rule_ids=rule_ids,
        detail=detail or {},
    )


def _audit_quietly(deps: AppDeps, entry: AuditEntry) -> None:
    """A failed audit write must not turn a correct refusal into a crash."""
    try:
        deps.store.put_audit(entry)
    except Exception:
        log.exception("could not write audit entry %s", entry.request_id)


def _replayed(record: IdempotencyRecord) -> dict[str, Any]:
    return {**record.result, "idempotent_replay": True}


def _late_replay(deps: AppDeps, identity: Identity, key: str, digest: str) -> dict | None:
    """After a failure that came *after* the first idempotency lookup, look once more.

    A duplicate delivery can slip in between its lookup and its checks: the original commits in
    that window, so the copy then sees state the original changed (slot taken, hold confirmed) and
    fails for a reason that is really "this was already done". If the key is stored now, the right
    answer is the stored result (or a conflict when the parameters differ), not that failure.
    """
    record = deps.store.get_idempotency(identity.sub, key)
    if record is None:
        return None
    if record.params_hash != digest:
        raise conflict()
    return _replayed(record)


def run_write(deps: AppDeps, identity: Identity, op: WriteOperation, idempotency_key: str) -> dict:
    key = validate_key(idempotency_key)
    now_iso = _iso(deps)
    digest = params_hash(op.tool, op.params())

    # 1. PEP-1: claims and request shape (stateless).
    pep1 = deps.kernel.pep1.decide(identity=identity, action=op.tool, party_size=op.party_size)
    annotate(venue_id=op.venue_id, party_size=op.party_size or None)
    annotate_decision("pep1", pep1)
    if not pep1.allowed:
        _audit_quietly(deps, _audit(deps, identity, op, "deny", pep1.rule_ids))
        raise deny_to_error(pep1)

    # 2. Idempotency: a repeat returns the stored result without touching anything.
    record = deps.store.get_idempotency(identity.sub, key)
    if is_replay(record, digest):
        assert record is not None
        return _replayed(record)

    # 3. Facts, then PEP-2 (stateful). Any refusal here re-checks the key once (see _late_replay).
    try:
        facts = op.load_facts(deps.store, identity, now_iso)
    except FairTableError:
        late = _late_replay(deps, identity, key, digest)
        if late is not None:
            return late
        raise
    pep2 = deps.kernel.pep2.decide(
        action=op.tool, diner_id=identity.sub, venue=facts.venue, ctx=facts.ctx
    )
    annotate_decision("pep2", pep2)
    if pep2.kind is not DecisionKind.ALLOW:
        late = _late_replay(deps, identity, key, digest)
        if late is not None:
            return late
    if pep2.kind is DecisionKind.DENY:
        _audit_quietly(deps, _audit(deps, identity, op, "deny", pep2.rule_ids))
        raise deny_to_error(pep2)
    if pep2.kind is DecisionKind.STEP_UP:
        _audit_quietly(deps, _audit(deps, identity, op, "step_up", pep2.rule_ids))
        raise StepUpRequired(pep2, op, identity)

    # 4. One transaction: the tool's writes + idempotency record + audit entry.
    try:
        plan = op.plan(deps.store, identity, now_iso, pep2)
    except FairTableError:
        late = _late_replay(deps, identity, key, digest)
        if late is not None:
            return late
        raise
    new_record = IdempotencyRecord(identity.sub, key, op.tool.value, digest, plan.result, now_iso)
    entry = _audit(deps, identity, op, "allow", pep2.rule_ids, plan.audit_detail)
    ops = [*plan.ops, deps.store.idempotency_op(new_record), deps.store.audit_op(entry)]
    idem_index = len(plan.ops)
    try:
        deps.store.transact(ops)
    except TransactionCancelled as exc:
        failed = exc.failed_indexes()
        if idem_index in failed:
            # The same key was stored between our lookup and the write (a duplicate delivery).
            winner = deps.store.get_idempotency(identity.sub, key)
            if winner is None:
                raise FairTableError(
                    ErrorCode.SLOT_TAKEN, "The request could not be completed; try again."
                ) from exc
            if winner.params_hash != digest:
                raise conflict() from exc
            return _replayed(winner)
        late = _late_replay(deps, identity, key, digest)
        if late is not None:
            return late
        error = op.explain_cancel([i for i in failed if i < idem_index], exc)
        _audit_quietly(deps, _audit(deps, identity, op, "failed", (), {"error": error.code.value}))
        raise error from exc
    return plan.result
