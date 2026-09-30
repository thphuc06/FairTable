"""HTML for the consent page. Plain strings, every dynamic value escaped with ``html.escape``."""

import re
from html import escape
from typing import Any

from server.domain.booking import KIND_CANCEL_FEE, Approval
from server.domain.models import Venue
from server.resources import policy_text
from server.tools.present import cancel_policy_text_from_terms, say_date, say_money, say_time

STYLE = """
body{font-family:system-ui,sans-serif;background:#f6f5f2;color:#1c1c1c;margin:0}
main{max-width:34rem;margin:2rem auto;padding:1.5rem;background:#fff;border-radius:12px;
box-shadow:0 1px 4px rgba(0,0,0,.12)}
h1{font-size:1.3rem;margin-top:0}
table{border-collapse:collapse;width:100%;margin:1rem 0}
td{padding:.4rem .2rem;border-bottom:1px solid #eee}td:first-child{color:#666;width:40%}
form{display:inline}
button{font-size:1rem;padding:.7rem 1.4rem;border:0;border-radius:8px;cursor:pointer;margin-right:.6rem}
.approve{background:#1a7f37;color:#fff}.decline{background:#e5e5e5}
input{font-size:1rem;padding:.5rem;width:100%;box-sizing:border-box;margin:.3rem 0 .8rem}
.you{background:#e8f0fe;border-radius:10px;padding:.5rem .8rem;margin:.4rem 0 .4rem 2rem}.bot{background:#f1f1ee;border-radius:10px;padding:.5rem .8rem;margin:.4rem 2rem .4rem 0}.err{color:#b00020}.ok{color:#1a7f37}pre{white-space:pre-wrap;font-size:.85rem;background:#f6f5f2;padding:.6rem;border-radius:8px}.muted{color:#666;font-size:.9rem}
"""


def layout(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )


def login_page(next_url: str, error: str | None = None) -> str:
    err = f"<p class='err'>{escape(error)}</p>" if error else ""
    return layout(
        "Sign in",
        "<h1>Sign in to approve</h1><p class='muted'>Use your FairTable account. "
        "This page is separate from your assistant.</p>"
        f"{err}<form method='post' action='/login'>"
        f"<input type='hidden' name='next' value='{escape(next_url, quote=True)}'>"
        "<label>Username<input name='username' autocomplete='username' required></label>"
        "<label>Password<input name='password' type='password' autocomplete='current-password' required></label>"
        "<button class='approve' type='submit'>Sign in</button></form>",
    )


def _rows(terms: dict[str, Any], kind: str) -> list[tuple[str, str]]:
    rows = [
        ("Restaurant", terms["restaurant"]),
        ("When", f"{say_date(terms['date'])} at {say_time(terms['time'])}"),
        ("Party size", str(terms["party_size"])),
    ]
    if kind == KIND_CANCEL_FEE:
        rows.append(("Cancellation fee", say_money(terms["fee_cents"])))
    else:
        rows.append(("Cancellation", cancel_policy_text_from_terms(terms)))
    return rows


def consent_page(approval: Approval, username: str, csrf: str) -> str:
    action = "Cancel this booking" if approval.kind == KIND_CANCEL_FEE else "Confirm this booking"
    table = "".join(
        f"<tr><td>{escape(k)}</td><td>{escape(v)}</td></tr>" for k, v in _rows(approval.terms, approval.kind)
    )
    path = f"/consent/{escape(approval.subject_id, quote=True)}/decision"
    return layout(
        "Approve",
        f"<h1>{escape(action)}?</h1>"
        "<p>Your assistant is asking for your approval.</p>"
        f"<table>{table}</table>"
        f"<form method='post' action='{path}'><input type='hidden' name='csrf' value='{escape(csrf, quote=True)}'>"
        "<button class='approve' name='decision' value='approve' type='submit'>Approve</button>"
        "<button class='decline' name='decision' value='decline' type='submit'>Decline</button></form>"
        f"<p class='muted'>Signed in as {escape(username)}. Nothing happens until you choose.</p>",
    )


def message_page(title: str, text: str) -> str:
    return layout(title, f"<h1>{escape(title)}</h1><p>{escape(text)}</p>")


def owner_page(venue: Venue, username: str, csrf: str, audit: list[dict[str, Any]], notice: str | None = None) -> str:
    """The owner console: the agent-share cap, the rules as diners' assistants see them, recent audit."""
    note = f"<p class='ok'>{escape(notice)}</p>" if notice else ""
    rows = "".join(
        "<tr><td>{at}</td><td>{tool}</td><td>{decision}</td><td>{rules}</td></tr>".format(
            at=escape(str(a.get("at", ""))[11:19]), tool=escape(str(a.get("tool", ""))),
            decision=escape(str(a.get("decision", ""))), rules=escape(", ".join(a.get("rule_ids") or [])),
        )
        for a in audit
    ) or "<tr><td colspan='4'>No activity yet.</td></tr>"
    return layout(
        f"{venue.name} - owner",
        f"<h1>{escape(venue.name)}</h1>{note}"
        "<h2>Agent share</h2>"
        f"<p>Assistants may book <b>{venue.agent_share_pct}%</b> of {venue.seats_per_day} seats a day "
        f"(<b>{venue.agent_cover_cap}</b> covers). The rest stays for phone and walk-in guests.</p>"
        "<form method='post' action='/owner/agent-share'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf, quote=True)}'>"
        "<label>New share, percent (0-100)<input name='pct' type='number' min='0' max='100' required></label>"
        "<button class='approve' type='submit'>Save</button></form>"
        "<h2>Rules assistants must follow</h2>"
        f"<pre>{escape(policy_text(venue))}</pre>"
        "<h2>Recent activity</h2>"
        f"<table><tr><td>Time (UTC)</td><td>Tool</td><td>Decision</td><td>Rule</td></tr>{rows}</table>"
        f"<p class='muted'>Signed in as {escape(username)}.</p>",
    )


def _linkify(text: str, consent_prefix: str) -> str:
    """Escape ``text``; turn only links to our own consent page into anchors."""
    safe = escape(text)
    pattern = re.compile(re.escape(escape(consent_prefix)) + r"/[A-Za-z0-9_-]{1,128}")
    return pattern.sub(lambda m: f"<a href='{m.group(0)}' target='_blank' rel='noopener'>{m.group(0)}</a>", safe)


def chat_page(username: str, turns: list[tuple[str, str]], inbox: list[dict[str, Any]], csrf: str,
              consent_prefix: str) -> str:
    """The demo chat: what the diner said, what the assistant answered, and the dev inbox."""
    talk = "".join(
        f"<div class='{'you' if who == 'you' else 'bot'}'><b>{'You' if who == 'you' else 'Assistant'}:</b> "
        f"{_linkify(text, consent_prefix)}</div>"
        for who, text in turns
    ) or ("<p class='muted'>Try: <i>Book a table at Luna Trattoria for 2 tomorrow at 7pm</i></p>")
    mail = "".join(
        f"<li><b>{escape(str(m.get('subject', '')))}</b> {_linkify(str(m.get('body', '')), consent_prefix)}</li>"
        for m in inbox[-5:]
    ) or "<li class='muted'>Nothing yet.</li>"
    token = escape(csrf, quote=True)
    return layout(
        "Chat",
        f"<h1>Your assistant</h1><p class='muted'>Signed in as {escape(username)}. This is a simulated voice assistant.</p>"
        f"{talk}"
        "<form method='post' action='/chat'>"
        f"<input type='hidden' name='csrf' value='{token}'>"
        "<input name='message' maxlength='500' autocomplete='off' autofocus required placeholder='Say something'>"
        "<button class='approve' type='submit'>Send</button></form>"
        f"<form method='post' action='/chat/reset'><input type='hidden' name='csrf' value='{token}'>"
        "<button class='decline' type='submit'>Start over</button></form>"
        "<h2>Notifications</h2>"
        f"<ul>{mail}</ul>",
    )
