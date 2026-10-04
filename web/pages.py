"""HTML for the sign-in, chat and owner pages. Plain strings, every dynamic value escaped with ``html.escape``."""

import re
from html import escape
from itertools import groupby
from typing import Any

from server.domain.models import Venue
from server.resources import policy_text
from simulator.events import Step

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
.you{background:#e8f0fe;border-radius:10px;padding:.5rem .8rem;margin:.4rem 0 .4rem 2rem}.bot{background:#f1f1ee;border-radius:10px;padding:.5rem .8rem;margin:.4rem 2rem .4rem 0}.bot p,.bot ul,.bot ol{margin:.3rem 0}.bot ul,.bot ol{padding-left:1.3rem}code{background:#ebebe6;padding:0 .25rem;border-radius:4px}.steps{margin-top:.4rem;font-size:.85rem}.steps summary{cursor:pointer;color:#555}.steps ol{margin:.4rem 0;padding-left:1.3rem}.chip{display:inline-block;padding:0 .4rem;border-radius:6px;background:#e3f1e6;color:#1a5f2c}.chip.no{background:#fbe3e3;color:#8a1c1c}.chip.wait{background:#fff1d6;color:#8a5a00}.badge{font-size:.75rem;padding:0 .35rem;border-radius:6px}.badge.ok{background:#e3f1e6;color:#1a5f2c}.badge.no{background:#fbe3e3;color:#8a1c1c}.badge.wait{background:#fff1d6;color:#8a5a00}.say{color:#333;font-style:italic}.grant{background:#f6f5f2;border-radius:8px;padding:.6rem .8rem;margin:.8rem 0}.grant select{width:auto;display:inline;padding:.1rem;margin:0}.tick{width:auto;margin:0 .3rem 0 0}.perms{padding-left:1.1rem}.perms form{display:inline;margin-left:.6rem}.err{color:#b00020}.ok{color:#1a7f37}pre{white-space:pre-wrap;font-size:.85rem;background:#f6f5f2;padding:.6rem;border-radius:8px}.rules{background:#f6f5f2;border-radius:8px;padding:.2rem .9rem;font-size:.92rem}.rules ul{padding-left:1.1rem}.rules li{margin:.4rem 0}.rules p{margin:.5rem 0}form.pick{display:block;margin:.4rem 0 .8rem}select{font-size:1rem;padding:.4rem;max-width:100%;margin:.3rem 0 .8rem}.muted{color:#666;font-size:.9rem}
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
        "<h1>Sign in</h1><p class='muted'>Use your FairTable account. "
        "This page is separate from your assistant.</p>"
        f"{err}<form method='post' action='/login'>"
        f"<input type='hidden' name='next' value='{escape(next_url, quote=True)}'>"
        "<label>Username<input name='username' autocomplete='username' required></label>"
        "<label>Password<input name='password' type='password' autocomplete='current-password' required></label>"
        "<button class='approve' type='submit'>Sign in</button></form>",
    )


def landing_page() -> str:
    return layout(
        "FairTable",
        "<h1>FairTable</h1><p>Book a table through a simulated voice assistant, "
        "or manage a restaurant.</p>"
        "<p><a href='/chat'>Sign in and chat</a> &middot; <a href='/owner'>Restaurant owners</a></p>",
    )


def message_page(title: str, text: str) -> str:
    return layout(title, f"<h1>{escape(title)}</h1><p>{escape(text)}</p>")


def _seat_label(slot_key: str) -> str:
    hhmm, _, group = slot_key.partition("#")
    return f"{hhmm[:2]}:{hhmm[2:]} {group}"


def rules_html(text: str) -> str:
    """The rules text (markdown with bullets wrapped over several lines) as the console shows it: wrapped lines are
    joined first, then the same safe renderer as the chat page (everything is escaped before any mark is applied)."""
    joined: list[str] = []
    for line in text.splitlines():
        if line.startswith("  ") and joined and joined[-1].strip():
            joined[-1] += " " + line.strip()
        else:
            joined.append(line)
    return f"<div class='rules'>{render_message(chr(10).join(joined))}</div>"


def owner_page(venue: Venue, username: str, csrf: dict[str, str], audit: list[dict[str, Any]],
               notice: str | None = None, *, seats: list | None = None, drops: list | None = None, draw: int = 24) -> str:
    """The owner console: the agent-share cap, the cancellation terms, the Fair Drops, the rules as diners'
    assistants see them, recent audit. ``csrf`` holds one token per form."""
    seat_rows = "".join(
        f"<optgroup label='{escape(date)}'>"
        + "".join(f"<option value='{escape(o.value, quote=True)}'>{escape(o.label)}</option>" for o in group)
        + "</optgroup>"
        for date, group in groupby(seats or [], key=lambda o: o.slot.date)
    )
    drop_rows = "".join(
        "<tr><td>{seat}</td><td>{draw}</td><td>{status}</td><td><code>{commit}</code></td></tr>".format(
            seat=escape(f"{d.date} " + ", ".join(_seat_label(k) for k in d.slot_keys)),
            draw=escape(d.drop_at.replace("T", " ").replace("Z", " UTC")[:20]), status=escape(d.status),
            commit=escape(d.commitment[:16]),
        )
        for d in (drops or [])
    ) or "<tr><td colspan='4'>No Fair Drops yet.</td></tr>"
    fee = f"{venue.cancel_fee_cents / 100:.2f}".rstrip("0").rstrip(".") or "0"
    draw_rows = "".join(
        f"<option value='{h}'{' selected' if h == draw else ''}>{h} hours before the seat</option>" for h in (24, 12, 6, 2)
    )
    seat_rows = seat_rows or "<option value=''>No seat is far enough away</option>"
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
        f"<input type='hidden' name='csrf' value='{escape(csrf['share'], quote=True)}'>"
        "<label>New share, percent (0-100)<input name='pct' type='number' min='0' max='100' required></label>"
        "<button class='approve' type='submit'>Save</button></form>"
        "<h2>Cancellation terms</h2>"
        f"<p>Cancelling less than <b>{venue.free_cancel_hours} hours</b> before the table costs <b>${escape(fee)}</b>. "
        "New holds use the new terms; a booking keeps the terms it was made with.</p>"
        "<form method='post' action='/owner/terms'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf['terms'], quote=True)}'>"
        "<label>Fee, dollars (0-200)<input name='fee' inputmode='decimal' required></label>"
        "<label>Free cancellation up to, hours before (0-168)<input name='hours' type='number' min='0' max='168' required></label>"
        "<button class='approve' type='submit'>Save</button></form>"
        "<h2>Fair Drops</h2>"
        "<p>A hot seat can be given out by a lottery that anyone can check instead of first come, first served. "
        "A secret seed is drawn now and only its fingerprint is published; entries stay open until the draw.</p>"
        "<p><b>1.</b> Choose when the draw happens. The list below shows the seats that are far enough away for it.</p>"
        "<form class='pick' method='get' action='/owner'>"
        f"<select name='draw'>{draw_rows}</select><button class='decline' type='submit'>Show seats</button></form>"
        f"<p><b>2.</b> Choose the seat (draw {draw} hours before it).</p>"
        "<form method='post' action='/owner/drops'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf['drops'], quote=True)}'>"
        f"<input type='hidden' name='hours_before' value='{int(draw)}'>"
        f"<select name='seat' required>{seat_rows}</select>"
        "<button class='approve' type='submit'>Create Fair Drop</button></form>"
        f"<table><tr><td>Seat</td><td>Draw (UTC)</td><td>Status</td><td>Commitment</td></tr>{drop_rows}</table>"
        "<h2>Rules assistants must follow</h2>"
        "<p class='muted'>These rules are checked with Cedar policies (<code>policies/*.cedar</code>): G1 to G4 at the "
        "AgentCore Gateway on AWS and again in the server, all the others in the server. "
        f"The same text is published as the public MCP resource <code>fairtable://restaurants/{escape(venue.venue_id)}/policies</code> "
        "(not a tool). Any MCP client can read it; whether a given assistant does is up to that assistant. "
        "It is only a description: the server enforces these rules whether or not the assistant reads it.</p>"
        f"{rules_html(policy_text(venue))}"
        "<h2>Recent activity</h2>"
        f"<table><tr><td>Time (UTC)</td><td>Tool</td><td>Decision</td><td>Rule</td></tr>{rows}</table>"
        f"<p class='muted'>Signed in as {escape(username)}.</p>",
    )


BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
CODE = re.compile(r"`([^`]+)`")
BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
NUMBERED = re.compile(r"^\s*\d{1,3}[.)]\s+(.*)$")
HEADING = re.compile(r"^\s*#{1,6}\s+(.*)$")


def _inline(line: str) -> str:
    """One line: escaped first, then the few markdown marks we honour (bold, italic, code)."""
    out = escape(line)
    out = CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", out)
    return ITALIC.sub(lambda m: f"<i>{m.group(1)}</i>", out)


def render_message(text: str) -> str:
    """The assistant's text as safe HTML. Everything is escaped before any mark is applied, so the model
    (or a diner) cannot inject markup; only bold, italic, `code`, bullet and numbered lists, headings
    (shown bold), paragraphs and line breaks are recognised."""
    blocks: list[str] = []
    items: list[str] = []
    kind = ""
    lines: list[str] = []

    def close_list() -> None:
        nonlocal items, kind
        if items:
            blocks.append(f"<{kind}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{kind}>")
        items, kind = [], ""

    def close_paragraph() -> None:
        nonlocal lines
        if lines:
            blocks.append("<p>" + "<br>".join(lines) + "</p>")
        lines = []

    for raw in text.replace("\r\n", "\n").split("\n"):
        bullet, numbered, heading = BULLET.match(raw), NUMBERED.match(raw), HEADING.match(raw)
        if bullet or numbered:
            close_paragraph()
            want = "ul" if bullet else "ol"
            if kind and kind != want:
                close_list()
            kind = want
            items.append(_inline((bullet or numbered).group(1)))
        elif not raw.strip():
            close_list()
            close_paragraph()
        else:
            close_list()
            lines.append(f"<b>{_inline(heading.group(1))}</b>" if heading else _inline(raw))
    close_list()
    close_paragraph()
    return "".join(blocks)


SHOWN_ARGS = ("restaurant_id", "date", "time_window", "party_size", "action", "query", "drop_id", "new_party_size")
SHOWN_IDS = ("hold_id", "reservation_id", "watch_id", "offer_id", "idempotency_key")


def _short(value: object, limit: int = 60) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _step_outcome(step: Step) -> tuple[str, str, str]:
    """(css class, badge, one line) for what the server did with this call. Only what the tool returned."""
    r = step.result
    if not step.is_error:
        return "ok", "ok", str(r.get("spoken_summary") or "")
    code, rule = str(r.get("error") or "error"), r.get("rule_id")
    kind = "wait" if code == "CONFIRMATION_REQUIRED" else "no"
    badge = "waiting for the user's yes" if kind == "wait" else "refused"
    label = f"{code} by {rule}" if rule else code
    return kind, badge, f"{label}: {r.get('message') or ''}".strip()


def steps_html(steps: tuple[Step, ...]) -> str:
    """A collapsible list of the tool calls behind an answer: proof of what was asked of the server and
    what the server decided. Everything is escaped; long tokens are shortened; no secrets are shown."""
    if not steps:
        return ""
    chips, rows = [], []
    for step in steps:
        css, badge, line = _step_outcome(step)
        chips.append(f"<span class='chip {css}'>{escape(step.tool)} {'&#10003;' if css == 'ok' else '&#10007;'}</span>")
        args = ", ".join(f"{k}={escape(_short(v))}" for k, v in step.args.items() if k in SHOWN_ARGS)
        ids = ", ".join(f"{k}={escape(_short(step.args[k], 14))}" for k in SHOWN_IDS if k in step.args)
        follow = (step.result.get("next_step") or {}).get("tool") if step.is_error else None
        rows.append(
            f"<li><b>{escape(step.tool)}</b>({args}"
            + (f"; <span class='muted'>{ids}</span>" if ids else "")
            + f") <span class='badge {css}'>{badge}</span>"
            + (f"<div class='muted'>{escape(_short(line, 220))}</div>" if line else "")
            + (f"<div class='muted'>suggested next step: {escape(str(follow))}</div>" if follow else "")
            + (f"<div class='say'>assistant said: {escape(_short(step.note, 200))}</div>" if step.note else "")
            + "</li>"
        )
    return (f"<details class='steps'><summary>{len(steps)} step{'s' if len(steps) != 1 else ''}: "
            + " &rarr; ".join(chips) + "</summary><ol>" + "".join(rows) + "</ol></details>")


VOICE_STYLE = """
.status{padding:.6rem .8rem;border-radius:8px;background:#eef;margin:.8rem 0}
.status.live{background:#e4f5e6}.status.bad{background:#fde3e3}
.status.work{background:#fff4d6;animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{50%{opacity:.55}}
.meters{display:flex;align-items:center;gap:.6rem;margin:.6rem 0;flex-wrap:wrap}
.pill{padding:.3rem .8rem;border-radius:999px;background:#e6e6e6;color:#666;font-weight:600;transition:background .15s,color .15s}
.pill.on{background:#1a7f37;color:#fff}.pill.bot.on{background:#3b5bdb}
.bar{flex:1;min-width:8rem;height:.6rem;border-radius:999px;background:#e6e6e6;overflow:hidden}
.bar i{display:block;height:100%;width:0;background:#1a7f37;transition:width .08s}
#talk{max-height:26rem;overflow:auto;margin:.8rem 0}
.stepsbox{margin:.1rem 0 .9rem 1rem;padding:.3rem .6rem;border-left:3px solid #c9c9d6;font-size:.85rem;max-height:7.5rem;overflow:auto}
.stepsbox ol{margin:.2rem 0 0;padding-left:1.1rem}
.badge{font-size:.75rem;padding:.1rem .4rem;border-radius:6px;background:#ddd}
.badge.ok{background:#cfe9d2}.badge.no{background:#f4cccc}
button:disabled{opacity:.5;cursor:default}
"""


def voice_page(username: str) -> str:
    """The voice demo: a call with the assistant. Its scripts are `/voice/worklet.js` and `/voice/voice.js`."""
    return layout(
        "Voice",
        f"<h1>Talk to your assistant</h1><p class='muted'>Signed in as {escape(username)}. Press Start, allow the "
        "microphone and speak. Use headphones to avoid echo. Try: <i>Book a table at Luna Trattoria for two "
        "tomorrow at seven.</i> The assistant reads the details back and books only after you say yes.</p>"
        "<button id='start' class='approve' type='button'>Start the call</button>"
        "<button id='stop' class='decline' type='button' disabled>End the call</button>"
        "<div id='status' class='status' role='status'>Not connected.</div>"
        "<div class='meters' aria-hidden='true'><span id='ind-you' class='pill'>You</span>"
        "<span id='ind-bot' class='pill bot'>Assistant</span><span class='bar'><i id='level'></i></span></div>"
        "<div id='talk' aria-live='polite'></div>"
        "<p class='muted'>Usage: <span id='usage'>none yet</span>. "
        "<a href='/chat'>Text chat</a></p>"
        f"<style>{VOICE_STYLE}</style><script src='/voice/voice.js' defer></script>",
    )


def chat_page(username: str, turns: list[tuple[str, str, tuple]], inbox: list[dict[str, Any]], csrf: str,
              voice: bool = False) -> str:
    """The demo chat: what the diner said, what the assistant answered (with the tool calls behind it), and
    the dev inbox."""
    talk = "".join(
        f"<div class='{'you' if who == 'you' else 'bot'}'><b>{'You' if who == 'you' else 'Assistant'}:</b> "
        f"{render_message(text) if who != 'you' else escape(text)}"
        f"{steps_html(steps) if who != 'you' else ''}</div>"
        for who, text, steps in turns
    ) or ("<p class='muted'>Try: <i>Book a table at Luna Trattoria for 2 tomorrow at 7pm</i></p>")
    mail = "".join(
        f"<li><b>{escape(str(m.get('subject', '')))}</b> {escape(str(m.get('body', '')))}</li>"
        for m in inbox[-5:]
    ) or "<li class='muted'>Nothing yet.</li>"
    token = escape(csrf, quote=True)
    voice_link = "<p><a href='/voice'>Talk to the assistant by voice instead</a></p>" if voice else ""
    return layout(
        "Chat",
        f"<h1>Your assistant</h1><p class='muted'>Signed in as {escape(username)}. This is a simulated voice assistant.</p>"
        f"{voice_link}"
        f"{talk}"
        "<form method='post' action='/chat'>"
        f"<input type='hidden' name='csrf' value='{token}'>"
        "<input name='message' maxlength='500' autocomplete='off' autofocus required placeholder='Say something'>"
        "<button class='approve' type='submit'>Send</button></form>"
        "<p class='muted'>A real model can take several seconds: press Send once and wait for the answer.</p>"
        f"<form method='post' action='/chat/reset'><input type='hidden' name='csrf' value='{token}'>"
        "<button class='decline' type='submit'>Start over</button></form>"
        "<h2>Notifications</h2>"
        f"<ul>{mail}</ul>",
    )
