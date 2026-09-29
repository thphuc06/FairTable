"""HTML for the consent page. Plain strings, every dynamic value escaped with ``html.escape``."""

from html import escape
from typing import Any

from server.domain.booking import KIND_CANCEL_FEE, Approval
from server.tools.present import cancel_policy_text_from_terms, say_date, say_money, say_time

STYLE = """
body{font-family:system-ui,sans-serif;background:#f6f5f2;color:#1c1c1c;margin:0}
main{max-width:30rem;margin:2rem auto;padding:1.5rem;background:#fff;border-radius:12px;
box-shadow:0 1px 4px rgba(0,0,0,.12)}
h1{font-size:1.3rem;margin-top:0}
table{border-collapse:collapse;width:100%;margin:1rem 0}
td{padding:.4rem .2rem;border-bottom:1px solid #eee}td:first-child{color:#666;width:40%}
form{display:inline}
button{font-size:1rem;padding:.7rem 1.4rem;border:0;border-radius:8px;cursor:pointer;margin-right:.6rem}
.approve{background:#1a7f37;color:#fff}.decline{background:#e5e5e5}
input{font-size:1rem;padding:.5rem;width:100%;box-sizing:border-box;margin:.3rem 0 .8rem}
.err{color:#b00020}.muted{color:#666;font-size:.9rem}
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
