"""The demo web app: sign-in, the chat page with the simulated assistant, and the owner console.

There is no consent page any more: a booking is confirmed by the diner's spoken yes (docs/DECISIONS.md D-051).
Routes: ``GET/POST /login``, ``GET/POST /chat``, ``POST /chat/reset``, ``GET /owner``, ``POST /owner/agent-share``,
``GET /healthz``. Every response is ``no-store`` and cannot be framed (clickjacking).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, Form, Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from server.config import Settings
from server.domain.audit import AuditEntry
from server.domain.clock import Clock, iso_z
from server.store import Store, TxOp, keys
from web import pages
from web.auth import Login
from web.chat import ChatService
from web.session import COOKIE_NAME, Session, SessionCodec
from web.voice import VoiceService
from web.voice_protocol import origin_ok

SAFE_NEXT = re.compile(r"^(/owner|/chat|/voice)$")
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


VOICE_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; media-src 'self'; "
    "worker-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)
STATIC = Path(__file__).parent / "static"
STATIC_FILES = {"voice.js": "text/javascript", "worklet.js": "text/javascript"}


@dataclass
class WebDeps:
    settings: Settings
    store: Store
    clock: Clock
    login: Login
    sessions: SessionCodec
    new_id: Any
    chat: ChatService | None = None  # the demo chat page; off when there is no assistant configured
    voice: VoiceService | None = None  # the voice page; off unless the voice extra and a model are configured


def page(status: int, title: str, text: str) -> HTMLResponse:
    return HTMLResponse(pages.message_page(title, text), status_code=status)


def safe_next(value: str | None) -> str:
    return value if value and SAFE_NEXT.match(value) else "/"


def create_app(deps: WebDeps) -> FastAPI:
    app = FastAPI(title="FairTable", docs_url=None, redoc_url=None, openapi_url=None)
    secure_cookie = deps.settings.web_public_url.startswith("https://")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in HEADERS.items():
            response.headers[name] = value
        if request.url.path.startswith("/voice"):  # the voice page needs its own scripts, the microphone and a socket
            response.headers["Content-Security-Policy"] = VOICE_CSP
            response.headers["Permissions-Policy"] = "microphone=(self)"
        return response

    def session_of(request: Request) -> Session | None:
        return deps.sessions.read(request.cookies.get(COOKIE_NAME))

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/")
    def home(request: Request) -> Response:
        session = session_of(request)
        if session is None:
            return HTMLResponse(pages.landing_page())
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

    def owner_session(request: Request) -> tuple[Session | None, Response | None]:
        session = session_of(request)
        if session is None:
            return None, RedirectResponse("/login?next=/owner", status_code=303)
        if session.owner_of is None:
            return None, page(403, "Owners only", "This page is for restaurant owners.")
        return session, None

    def render_chat(session: Session, status: int = 200) -> Response:
        assert deps.chat is not None
        turns = [(t.who, t.text, t.steps) for t in deps.chat.transcript(session.sub)]
        inbox = deps.store.list_inbox(session.sub)
        csrf = deps.sessions.csrf_token(session, "chat")
        html = pages.chat_page(session.username, turns, inbox, csrf, voice=deps.voice is not None)
        return HTMLResponse(html, status_code=status)

    def chat_session(request: Request) -> tuple[Session | None, Response | None]:
        if deps.chat is None:
            return None, page(404, "Not found", "The chat page is not switched on here.")
        session = session_of(request)
        if session is None or not deps.chat.is_signed_in(session.sub):
            return None, RedirectResponse("/login?next=/chat", status_code=303)
        return session, None

    def voice_session(request: Request) -> tuple[Session | None, Response | None]:
        if deps.voice is None or deps.chat is None:
            return None, page(404, "Not found", "The voice page is not switched on here.")
        session = session_of(request)
        if session is None or deps.chat.token_of(session.sub) is None:
            return None, RedirectResponse("/login?next=/voice", status_code=303)
        return session, None

    @app.get("/voice")
    def voice(request: Request) -> Response:
        session, problem = voice_session(request)
        return problem if problem is not None else HTMLResponse(pages.voice_page(session.username))  # type: ignore[union-attr]

    @app.get("/voice/{name}")
    def voice_static(name: str) -> Response:
        if deps.voice is None or name not in STATIC_FILES:
            return page(404, "Not found", "There is nothing here.")
        return Response((STATIC / name).read_bytes(), media_type=STATIC_FILES[name])

    @app.websocket("/voice/ws")
    async def voice_ws(ws: WebSocket) -> None:
        session = deps.sessions.read(ws.cookies.get(COOKIE_NAME))
        token = deps.chat.token_of(session.sub) if session is not None and deps.chat is not None else None
        if (deps.voice is None or session is None or token is None
                or not origin_ok(ws.headers.get("origin"), ws.headers.get("host"), deps.settings.web_public_url)):
            await ws.close(code=1008)  # policy violation: not signed in, or not our own page
            return
        await deps.voice.serve(ws, sub=session.sub, token=token)

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
