"""The consent page (plan task P1-11): a signed-in user approves or declines what their assistant
asked for. The link only *names* the approval; access needs a login as the same user.

Routes: ``GET /login``, ``POST /login``, ``GET /consent/{id}``, ``POST /consent/{id}/decision``,
``GET /healthz``. Every response is ``no-store`` and cannot be framed (clickjacking).
"""

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from server.config import Settings
from server.domain.audit import AuditEntry
from server.domain.booking import (
    APPROVAL_APPROVED,
    APPROVAL_DECLINED,
    APPROVAL_PENDING,
    HOLD_HELD,
    KIND_CANCEL_FEE,
    RES_CONFIRMED,
    Approval,
    approval_is_expired,
)
from server.domain.clock import Clock, iso_z
from server.store import Store, TransactionCancelled, TxOp, keys
from web import pages
from web.auth import Login
from web.chat import ChatService
from web.session import COOKIE_NAME, Session, SessionCodec

SUBJECT_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SAFE_NEXT = re.compile(r"^(/consent/[A-Za-z0-9_-]{1,128}|/owner|/chat)$")
HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
}


@dataclass
class WebDeps:
    settings: Settings
    store: Store
    clock: Clock
    login: Login
    sessions: SessionCodec
    new_id: Any
    chat: ChatService | None = None  # the demo chat page; off when there is no assistant configured


def page(status: int, title: str, text: str) -> HTMLResponse:
    return HTMLResponse(pages.message_page(title, text), status_code=status)


def safe_next(value: str | None) -> str:
    return value if value and SAFE_NEXT.match(value) else "/"


def create_app(deps: WebDeps) -> FastAPI:
    app = FastAPI(title="FairTable consent", docs_url=None, redoc_url=None, openapi_url=None)
    secure_cookie = deps.settings.consent_base_url.startswith("https://")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers[name] = value
        return response

    def session_of(request: Request) -> Session | None:
        return deps.sessions.read(request.cookies.get(COOKIE_NAME))

    def to_login(subject_path: str) -> RedirectResponse:
        return RedirectResponse(f"/login?next={subject_path}", status_code=303)

    def live_approval(subject_id: str, session: Session) -> tuple[Approval | None, Response | None]:
        """The approval this user may act on, or the page to show instead."""
        if not SUBJECT_ID.match(subject_id):
            return None, page(404, "Not found", "There is nothing to approve here.")
        approval = deps.store.get_approval(subject_id)
        if approval is None:
            return None, page(404, "Not found", "There is nothing to approve here.")
        if approval.sub != session.sub:
            return None, page(403, "Not your request",
                              "This request belongs to another account. Sign in with the account that made it.")
        now_iso = iso_z(deps.clock.now())
        if approval.status == APPROVAL_PENDING and approval_is_expired(approval, now_iso):
            return None, page(410, "Expired", "This request has expired. Ask your assistant to try again.")
        if approval.status == APPROVAL_PENDING and not subject_is_live(subject_id, approval, now_iso):
            return None, page(410, "No longer active",
                              "The booking this refers to is no longer active. Ask your assistant to try again.")
        return approval, None

    def subject_is_live(subject_id: str, approval: Approval, now_iso: str) -> bool:
        if approval.kind == KIND_CANCEL_FEE:
            reservation = deps.store.get_reservation(subject_id)
            return reservation is not None and reservation.status == RES_CONFIRMED
        hold = deps.store.get_hold(subject_id)
        return hold is not None and hold.status == HOLD_HELD and hold.held_until > now_iso

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/")
    def home(request: Request) -> Response:
        session = session_of(request)
        if session is None:
            return page(200, "FairTable", "Open the approval link your assistant gave you, or sign in to chat.")
        return RedirectResponse("/owner" if session.owner_of else "/chat", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_form(next: str | None = None) -> HTMLResponse:
        return HTMLResponse(pages.login_page(safe_next(next)))

    @app.post("/login")
    def login(username: str = Form(""), password: str = Form(""), next: str = Form("/")) -> Response:
        signed_in = deps.login.sign_in(username, password)
        if signed_in is None:
            return HTMLResponse(pages.login_page(safe_next(next), "Wrong username or password."), status_code=401)
        identity = signed_in.identity
        if deps.chat is not None:
            deps.chat.remember(identity.sub, signed_in.access_token, signed_in.expires_in_s)
        response = RedirectResponse(safe_next(next), status_code=303)
        response.set_cookie(
            COOKIE_NAME,
            deps.sessions.issue(identity.sub, identity.username or identity.sub, identity.owned_venue),
            max_age=deps.sessions.ttl_s, httponly=True, samesite="lax", secure=secure_cookie, path="/",
        )
        return response

    @app.get("/consent/{subject_id}")
    def show(subject_id: str, request: Request) -> Response:
        session = session_of(request)
        if session is None:
            return to_login(f"/consent/{subject_id}" if SUBJECT_ID.match(subject_id) else "/")
        approval, problem = live_approval(subject_id, session)
        if problem is not None:
            return problem
        assert approval is not None
        if approval.status == APPROVAL_PENDING:
            csrf = deps.sessions.csrf_token(session, subject_id)
            return HTMLResponse(pages.consent_page(approval, session.username, csrf))
        done = {
            APPROVAL_APPROVED: "You approved this. Go back to your assistant and ask it to try again.",
            APPROVAL_DECLINED: "You declined this. Nothing was booked or changed.",
        }.get(approval.status, "This request has already been used.")
        return page(200, "Already answered", done)

    @app.post("/consent/{subject_id}/decision")
    def decide(subject_id: str, request: Request, decision: str = Form(""), csrf: str = Form("")) -> Response:
        session = session_of(request)
        if session is None:
            return to_login(f"/consent/{subject_id}" if SUBJECT_ID.match(subject_id) else "/")
        if not deps.sessions.csrf_ok(session, subject_id, csrf):
            return page(403, "Not allowed", "This form is out of date. Open the link again.")
        approval, problem = live_approval(subject_id, session)
        if problem is not None:
            return problem
        assert approval is not None
        if decision not in ("approve", "decline"):
            return page(400, "Not understood", "Choose Approve or Decline.")
        if approval.status == APPROVAL_PENDING:
            record_decision(deps, approval, session, approved=decision == "approve")
        return RedirectResponse(f"/consent/{subject_id}", status_code=303)

    def owner_session(request: Request) -> tuple[Session | None, Response | None]:
        session = session_of(request)
        if session is None:
            return None, RedirectResponse("/login?next=/owner", status_code=303)
        if session.owner_of is None:
            return None, page(403, "Owners only", "This page is for restaurant owners.")
        return session, None

    def render_chat(session: Session, status: int = 200) -> Response:
        assert deps.chat is not None
        turns = [(t.who, t.text) for t in deps.chat.transcript(session.sub)]
        inbox = deps.store.list_inbox(session.sub)
        csrf = deps.sessions.csrf_token(session, "chat")
        html = pages.chat_page(session.username, turns, inbox, csrf, deps.settings.consent_base_url.rstrip("/") + "/consent")
        return HTMLResponse(html, status_code=status)

    def chat_session(request: Request) -> tuple[Session | None, Response | None]:
        if deps.chat is None:
            return None, page(404, "Not found", "The chat page is not switched on here.")
        session = session_of(request)
        if session is None or not deps.chat.is_signed_in(session.sub):
            return None, RedirectResponse("/login?next=/chat", status_code=303)
        return session, None

    @app.get("/chat")
    def chat(request: Request) -> Response:
        session, problem = chat_session(request)
        return problem if problem is not None else render_chat(session)  # type: ignore[arg-type]

    @app.post("/chat")
    async def chat_send(request: Request, message: str = Form(""), csrf: str = Form("")) -> Response:
        session, problem = chat_session(request)
        if problem is not None:
            return problem
        assert session is not None and deps.chat is not None
        if not deps.sessions.csrf_ok(session, "chat", csrf):
            return page(403, "Not allowed", "This form is out of date. Open the page again.")
        await deps.chat.send(session.sub, message)
        return RedirectResponse("/chat", status_code=303)

    @app.post("/chat/reset")
    def chat_reset(request: Request, csrf: str = Form("")) -> Response:
        session, problem = chat_session(request)
        if problem is not None:
            return problem
        assert session is not None and deps.chat is not None
        if not deps.sessions.csrf_ok(session, "chat", csrf):
            return page(403, "Not allowed", "This form is out of date. Open the page again.")
        deps.chat.reset(session.sub)
        return RedirectResponse("/chat", status_code=303)

    def csrf_subject(venue_id: str) -> str:
        return f"owner-share:{venue_id}"

    def render_owner(session: Session, notice: str | None = None, status: int = 200) -> Response:
        venue = deps.store.get_venue(session.owner_of or "")
        if venue is None:
            return page(404, "Not found", "Your restaurant is not set up yet.")
        today = deps.clock.now().date()
        audit: list[dict] = []
        for back in range(3):
            audit += deps.store.list_audit(venue.venue_id, (today - timedelta(days=back)).isoformat())
        audit.sort(key=lambda a: str(a.get("at", "")), reverse=True)
        csrf = deps.sessions.csrf_token(session, csrf_subject(venue.venue_id))
        return HTMLResponse(pages.owner_page(venue, session.username, csrf, audit[:40], notice), status_code=status)

    @app.get("/owner")
    def owner(request: Request) -> Response:
        session, problem = owner_session(request)
        return problem if problem is not None else render_owner(session)  # type: ignore[arg-type]

    @app.post("/owner/agent-share")
    def owner_set_share(request: Request, pct: str = Form(""), csrf: str = Form("")) -> Response:
        session, problem = owner_session(request)
        if problem is not None:
            return problem
        assert session is not None and session.owner_of is not None
        if not deps.sessions.csrf_ok(session, csrf_subject(session.owner_of), csrf):
            return page(403, "Not allowed", "This form is out of date. Open the page again.")
        if not re.fullmatch(r"[0-9]{1,3}", pct.strip()) or int(pct) > 100:
            return render_owner(session, "Enter a whole number from 0 to 100.", status=400)
        change_agent_share(deps, session, int(pct))
        return RedirectResponse("/owner", status_code=303)

    return app


def change_agent_share(deps: WebDeps, session: Session, pct: int) -> None:
    """Set the venue's agent share and audit the change in one transaction. Rule S2 reads this on the
    next hold, so the effect is immediate."""
    venue_id = session.owner_of
    assert venue_id is not None
    venue = deps.store.get_venue(venue_id)
    if venue is None:
        return
    now_iso = iso_z(deps.clock.now())
    key = keys.venue(venue_id)
    op = TxOp(
        "Update", key={"PK": key.pk, "SK": key.sk}, update="SET agent_share_pct = :new",
        condition="attribute_exists(PK)", values={":new": pct},
    )
    entry = AuditEntry(
        venue_id=venue_id, timestamp=now_iso, request_id=deps.new_id(), sub=session.sub, agent_id=None,
        tool="owner_console", decision="changed", rule_ids=("S2",),
        detail={"agent_share_pct_from": venue.agent_share_pct, "agent_share_pct_to": pct},
    )
    deps.store.transact([op, deps.store.audit_op(entry)])


def record_decision(deps: WebDeps, approval: Approval, session: Session, *, approved: bool) -> None:
    """Pending -> approved/declined, exactly once, and audited in the same transaction.
    A double click or a race finds the approval already answered and changes nothing."""
    now_iso = iso_z(deps.clock.now())
    status = APPROVAL_APPROVED if approved else APPROVAL_DECLINED
    key = keys.approval(approval.subject_id)
    op = TxOp(
        "Update", key={"PK": key.pk, "SK": key.sk}, update="SET #st = :new, decided_at = :now",
        condition="#st = :pending AND #sub = :sub AND expires_at > :now AND terms_hash = :h",
        names={"#st": "status", "#sub": "sub"},
        values={":new": status, ":pending": APPROVAL_PENDING, ":sub": session.sub, ":now": now_iso,
                ":h": approval.terms_hash},
    )
    entry = AuditEntry(
        venue_id=approval.venue_id, timestamp=now_iso, request_id=deps.new_id(), sub=session.sub,
        agent_id=None, tool="consent_page", decision=status, rule_ids=(),
        detail={"subject_id": approval.subject_id, "kind": approval.kind},
    )
    try:
        deps.store.transact([op, deps.store.audit_op(entry)])
    except TransactionCancelled:
        pass  # answered or expired in the meantime: the page shows the current state
