"""HTML for the sign-in, chat and owner pages. Plain strings, every dynamic value escaped with ``html.escape``."""

import json
import re
from html import escape
from itertools import groupby
from typing import Any

from server.domain.models import Venue
from server.resources import policy_text
from simulator.events import Step

STYLE = """
:root{--bg:#faf7f2;--ink:#1d2433;--muted:#667085;--card:#fff;--line:#e7e1d6;--soft:#f4f0e8;--brand:#b4442a;--brand-d:#923520;
--ok:#17744a;--okbg:#e2f4ea;--no:#b3261e;--nobg:#fdeaea;--wait:#946200;--waitbg:#fff3d1}
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--ink)}
a{color:var(--brand)}
.top{background:var(--ink);color:#fff;padding:.75rem 1.2rem;display:flex;align-items:center;gap:1.2rem;flex-wrap:wrap}
.brand{font-weight:700;font-size:1.15rem;color:#fff;text-decoration:none}
.brand::before{content:"";display:inline-block;width:.7rem;height:.7rem;border-radius:50%;background:var(--brand);margin-right:.5rem}
.nav{display:flex;gap:1.1rem;margin-left:auto;align-items:center;font-size:.95rem;flex-wrap:wrap}
.nav a{color:#d6dbe6;text-decoration:none}.nav a:hover,.nav a.here{color:#fff}.nav .user{color:#9aa3b5}
main{max-width:34rem;margin:1.5rem auto;padding:0 1rem}main.mid{max-width:52rem}main.wide{max-width:74rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.2rem 1.4rem;margin:0 0 1rem;
box-shadow:0 1px 2px rgba(29,36,51,.05)}
h1{font-size:1.5rem;line-height:1.25;margin:.1rem 0 .5rem}h2{font-size:1.1rem;margin:0 0 .5rem}
p{margin:.5rem 0}.muted{color:var(--muted);font-size:.9rem}
table{border-collapse:collapse;width:100%;margin:.8rem 0;font-size:.93rem}
.card{overflow-wrap:anywhere}.card table{display:block;overflow-x:auto}
th{text-align:left;color:var(--muted);font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}
th,td{padding:.45rem .35rem;border-bottom:1px solid var(--line);vertical-align:top}
form{display:inline}form.pick{display:block;margin:.4rem 0 .8rem}
button,.btn{font:inherit;font-size:1rem;padding:.65rem 1.3rem;border:0;border-radius:10px;cursor:pointer;margin-right:.5rem;
text-decoration:none;display:inline-block;transition:background .15s}
.approve,.btn{background:var(--brand);color:#fff}.approve:hover,.btn:hover{background:var(--brand-d)}
.decline,.btn.ghost{background:var(--soft);color:var(--ink);border:1px solid var(--line)}.decline:hover,.btn.ghost:hover{background:#ebe5d9}
button:disabled{opacity:.5;cursor:default}
input,select,textarea{font:inherit;font-size:1rem;padding:.55rem .65rem;width:100%;margin:.3rem 0 .8rem;border:1px solid #cfc8ba;
border-radius:9px;background:#fff;color:var(--ink)}
input:focus,select:focus,textarea:focus{outline:2px solid var(--brand);outline-offset:1px}
input[type=range]{padding:0;border:0;accent-color:var(--brand);margin:.4rem 0}
select{width:auto;max-width:100%}label{display:block;font-size:.92rem;color:#3a4252}
code{background:var(--soft);padding:0 .3rem;border-radius:5px;font-size:.88em}
pre{white-space:pre-wrap;font-size:.85rem;background:var(--soft);padding:.6rem;border-radius:8px}
.err{color:var(--no)}.ok{color:var(--ok)}
.hero{text-align:center;padding:1.6rem 1rem .6rem}.hero h1{font-size:1.9rem}.hero p{color:#4a5365}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.8rem;margin:1rem 0}
.grid3 .card{margin:0;font-size:.93rem}.grid3 b{display:block;margin-bottom:.2rem}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.8rem;margin:0 0 1rem}
.stat{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:.8rem 1rem}
.stat span{display:block;font-size:.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.stat b{display:block;font-size:1.6rem;line-height:1.2}.stat small{color:var(--muted)}
.chat-grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:1rem;align-items:start}
@media(max-width:52rem){.chat-grid{grid-template-columns:minmax(0,1fr)}.panel{position:static}}
.chat-grid>*{min-width:0}
.talk{display:flex;flex-direction:column;gap:.7rem;margin:.8rem 0;max-height:32rem;overflow:auto;padding:.2rem}
.talk>*{flex:none}
.you,.bot{position:relative;max-width:88%;padding:.55rem .9rem;border-radius:16px;margin:0}
.you{align-self:flex-end;background:var(--brand);color:#fff;border-bottom-right-radius:4px}
.you code{background:rgba(255,255,255,.2);color:#fff}
.bot{align-self:flex-start;background:var(--soft);border:1px solid var(--line);border-bottom-left-radius:4px}
.who{display:block;font-size:.7rem;letter-spacing:.06em;text-transform:uppercase;opacity:.7;margin-bottom:.1rem}
.bot p,.bot ul,.bot ol{margin:.3rem 0}.bot ul,.bot ol{padding-left:1.3rem}
.typing{align-self:flex-start;display:flex;gap:.3rem;padding:.7rem .9rem;background:var(--soft);border:1px solid var(--line);
border-radius:16px;border-bottom-left-radius:4px}
.typing i{width:.5rem;height:.5rem;border-radius:50%;background:#9aa3b5;animation:blink 1.1s infinite ease-in-out}
.typing i:nth-child(2){animation-delay:.18s}.typing i:nth-child(3){animation-delay:.36s}
@keyframes blink{0%,80%,100%{opacity:.25}40%{opacity:1}}
.quick{display:flex;flex-wrap:wrap;gap:.5rem;margin:.4rem 0 .6rem}.quick form{margin:0}
.qbtn{background:#fff;color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:.35rem .9rem;font-size:.9rem;margin:0}
.qbtn:hover{border-color:var(--brand);color:var(--brand)}
.sendrow{display:flex;gap:.5rem;align-items:center}.sendrow input{margin:0;flex:1}.sendrow button{margin:0}
.steps{margin-top:.45rem;font-size:.85rem;border-top:1px dashed #d8d1c3;padding-top:.35rem}
.steps summary{cursor:pointer;color:#555}.steps ol{margin:.4rem 0;padding-left:1.3rem}
.chip{display:inline-block;padding:0 .4rem;border-radius:6px;background:var(--okbg);color:var(--ok)}
.chip.no{background:var(--nobg);color:var(--no)}.chip.wait{background:var(--waitbg);color:var(--wait)}
.badge{font-size:.75rem;padding:0 .35rem;border-radius:6px}.badge.ok{background:var(--okbg);color:var(--ok)}
.badge.no{background:var(--nobg);color:var(--no)}.badge.wait{background:var(--waitbg);color:var(--wait)}
.say{color:#333;font-style:italic}
.panel{position:sticky;top:1rem}.panel h2{margin-bottom:.2rem}
.turn{margin:.8rem 0 0}.ask{font-size:.82rem;color:var(--muted);margin-bottom:.2rem}
.dec{list-style:none;margin:0;padding:0}
.dec li{border-left:4px solid var(--line);background:#fff;border-radius:0 9px 9px 0;padding:.35rem .6rem;margin:.35rem 0;
box-shadow:0 1px 1px rgba(29,36,51,.06)}
.dec li.k-ok{border-left-color:var(--ok)}.dec li.k-no{border-left-color:var(--no)}.dec li.k-wait{border-left-color:var(--wait)}
.dh{display:flex;justify-content:space-between;gap:.5rem;align-items:center;flex-wrap:wrap}.dh b{font-size:.92rem}
.dm{font-size:.84rem;color:#4a5365;margin-top:.1rem}
.tag{font-size:.74rem;font-weight:600;padding:.05rem .5rem;border-radius:999px;overflow-wrap:anywhere}
.tag.ok{background:var(--okbg);color:var(--ok)}.tag.no{background:var(--nobg);color:var(--no)}.tag.wait{background:var(--waitbg);color:var(--wait)}
.legend{display:flex;gap:.4rem;flex-wrap:wrap;margin:.5rem 0}
.rules{background:var(--soft);border-radius:10px;padding:.2rem .9rem;font-size:.92rem}
.rules ul{padding-left:1.1rem}.rules li{margin:.4rem 0}.rules p{margin:.5rem 0}
.checks{list-style:none;margin:.8rem 0;padding:0}
.find{margin:1rem 0 0;font-size:1rem}
tr.mine td{background:var(--waitbg);font-weight:700}tr.mine code{background:#fff}
.checks li{padding:.45rem .7rem;border-radius:9px;margin:.3rem 0}
.checks li.pass{background:var(--okbg);color:var(--ok)}.checks li.fail{background:var(--nobg);color:var(--no)}
.facts{display:grid;grid-template-columns:auto 1fr;gap:.2rem 1rem;margin:.6rem 0}.facts dt{color:var(--muted)}.facts dd{margin:0}
.steplist{counter-reset:s;list-style:none;padding:0;margin:.6rem 0}
.steplist li{counter-increment:s;padding-left:2.2rem;position:relative;margin:.6rem 0}
.steplist li::before{content:counter(s);position:absolute;left:0;top:.05rem;width:1.5rem;height:1.5rem;border-radius:50%;
background:var(--brand);color:#fff;text-align:center;font-size:.85rem;line-height:1.5rem}
textarea{font-family:ui-monospace,Consolas,monospace;font-size:.82rem}
"""


def layout(title: str, body: str, *, size: str = "", bare: bool = False, here: str = "",
           nav: tuple[tuple[str, str], ...] = (), user: str = "", scripts: str = "") -> str:
    """The frame of every page: a header with the product name and the links that apply, then the content in a
    card (``bare`` pages bring their own cards). ``scripts`` goes at the end of the page."""
    links = "".join(
        "<a href='{}'{}>{}</a>".format(escape(href, quote=True), " class='here'" if href == here else "", escape(label))
        for label, href in nav
    )
    who = f"<span class='user'>{escape(user)}</span>" if user else ""
    main = f"<main class='{size}'>" if size else "<main>"
    inner = body if bare else "<section class='card'>" + body + "</section>"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><header class='top'><a class='brand' href='/'>FairTable</a><nav class='nav'>{links}{who}</nav></header>"
        f"{main}{inner}</main>{scripts}</body></html>"
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
        "<section class='hero'><h1>Let an assistant book your table. Safely.</h1>"
        "<p>FairTable is the booking front door a restaurant publishes for AI assistants such as Alexa+. "
        "Every booking has a real diner and a verified assistant behind it, and the restaurant's own rules decide "
        "what is allowed.</p>"
        "<p><a class='btn' href='/chat'>Try the simulated assistant</a>"
        "<a class='btn ghost' href='/owner'>Restaurant owners</a></p></section>"
        "<div class='grid3'>"
        "<div class='card'><b>Verified identity</b>A booking needs a signed-in diner and a verified assistant. "
        "Bots can read but not book.</div>"
        "<div class='card'><b>Rules the owner sets</b>Party size, holds per diner, the share of seats assistants "
        "may take. Checked by the server on every call.</div>"
        "<div class='card'><b>A fair lottery for hot tables</b>The seed is committed first and revealed after the "
        "draw, so anyone can check the result.</div></div>",
        bare=True, size="mid",
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


DECISION_LOOK = {
    "allow": ("ok", "Allowed"), "changed": ("ok", "Changed"), "deny": ("no", "Refused"),
    "conflict": ("wait", "Conflict"), "failed": ("no", "Failed"),
}


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
        "<tr><td>{seat}</td><td>{draw}</td><td>{status}</td><td><code>{commit}</code></td>"
        "<td><a href='/drops/{drop_id}'>Check the draw</a></td></tr>".format(
            seat=escape(f"{d.date} " + ", ".join(_seat_label(k) for k in d.slot_keys)),
            draw=escape(d.drop_at.replace("T", " ").replace("Z", " UTC")[:20]), status=escape(d.status),
            commit=escape(d.commitment[:16]), drop_id=escape(d.drop_id, quote=True),
        )
        for d in (drops or [])
    ) or "<tr><td colspan='5'>No Fair Drops yet.</td></tr>"
    fee = f"{venue.cancel_fee_cents / 100:.2f}".rstrip("0").rstrip(".") or "0"
    draw_rows = "".join(
        f"<option value='{h}'{' selected' if h == draw else ''}>{h} hours before the seat</option>" for h in (24, 12, 6, 2)
    )
    seat_rows = seat_rows or "<option value=''>No seat is far enough away</option>"
    note = f"<p class='ok'>{escape(notice)}</p>" if notice else ""
    rows = "".join(
        "<tr><td>{at}</td><td>{tool}</td><td>{decision}</td><td>{rules}</td></tr>".format(
            at=escape(str(a.get("at", ""))[11:19]), tool=escape(str(a.get("tool", ""))),
            decision=_decision_tag(str(a.get("decision", ""))), rules=escape(", ".join(a.get("rule_ids") or [])),
        )
        for a in audit
    ) or "<tr><td colspan='4'>No activity yet.</td></tr>"
    stats = (
        "<div class='stats'>"
        f"<div class='stat'><span>Agent share</span><b>{venue.agent_share_pct}%</b>"
        f"<small>{venue.agent_cover_cap} of {venue.seats_per_day} seats a day</small></div>"
        f"<div class='stat'><span>Free cancellation</span><b>{venue.free_cancel_hours} h</b><small>before the table</small></div>"
        f"<div class='stat'><span>Late cancellation</span><b>${escape(fee)}</b><small>per booking</small></div>"
        f"<div class='stat'><span>Fair Drops</span><b>{len(drops or [])}</b><small>created so far</small></div></div>"
    )
    return layout(
        f"{venue.name} - owner",
        f"<h1>{escape(venue.name)}</h1><p class='muted'>Owner console. Every change here is checked, applied in one "
        f"step and written to the audit list below.</p>{note}{stats}"
        "<div class='card'><h2>Agent share</h2>"
        f"<p>Assistants may book <b>{venue.agent_share_pct}%</b> of {venue.seats_per_day} seats a day "
        f"(<b>{venue.agent_cover_cap}</b> covers). The rest stays for phone and walk-in guests.</p>"
        f"<form data-share data-seats='{venue.seats_per_day}' data-current='{venue.agent_share_pct}' "
        "method='post' action='/owner/agent-share'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf['share'], quote=True)}'>"
        "<label>New share, percent (0-100)<input name='pct' type='number' min='0' max='100' required></label>"
        "<button class='approve' type='submit'>Save</button></form></div>"
        "<div class='card'><h2>Cancellation terms</h2>"
        f"<p>Cancelling less than <b>{venue.free_cancel_hours} hours</b> before the table costs <b>${escape(fee)}</b>. "
        "New holds use the new terms; a booking keeps the terms it was made with.</p>"
        "<form method='post' action='/owner/terms'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf['terms'], quote=True)}'>"
        "<label>Fee, dollars (0-200)<input name='fee' inputmode='decimal' required></label>"
        "<label>Free cancellation up to, hours before (0-168)<input name='hours' type='number' min='0' max='168' required></label>"
        "<button class='approve' type='submit'>Save</button></form></div>"
        "<div class='card'><h2>Fair Drops</h2>"
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
        "<table><tr><th>Seat</th><th>Draw (UTC)</th><th>Status</th><th>Commitment</th><th></th></tr>"
        f"{drop_rows}</table></div>"
        "<div class='card'><h2>Rules assistants must follow</h2>"
        "<p class='muted'>These rules are checked with Cedar policies (<code>policies/*.cedar</code>): G1 to G4 at the "
        "AgentCore Gateway on AWS and again in the server, all the others in the server. "
        f"The same text is published as the public MCP resource <code>fairtable://restaurants/{escape(venue.venue_id)}/policies</code> "
        "(not a tool). Any MCP client can read it; whether a given assistant does is up to that assistant. "
        "It is only a description: the server enforces these rules whether or not the assistant reads it.</p>"
        f"{rules_html(policy_text(venue))}</div>"
        "<div class='card'><h2>Recent activity</h2>"
        f"<table><tr><th>Time (UTC)</th><th>Tool</th><th>Decision</th><th>Rule</th></tr>{rows}</table>"
        f"<p class='muted'>Signed in as {escape(username)}.</p></div>",
        size="mid", bare=True, here="/owner", nav=(("Owner console", "/owner"),), user=username,
        scripts="<script src='/static/owner.js' defer></script>",
    )


def _decision_tag(decision: str) -> str:
    css, label = DECISION_LOOK.get(decision, ("wait", decision or "-"))
    return f"<span class='tag {css}'>{escape(label)}</span>"


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
.status{display:flex;align-items:center;gap:.6rem;padding:.6rem .9rem;border-radius:10px;background:var(--soft);
border:1px solid var(--line);margin:.8rem 0}
.status::before{content:"";flex:none;width:.65rem;height:.65rem;border-radius:50%;background:#9aa3b5}
.status.live{background:var(--okbg);border-color:#bfe3cf}.status.live::before{background:var(--ok)}
.status.bad{background:var(--nobg);border-color:#f1c4c1}.status.bad::before{background:var(--no)}
.status.work{background:var(--waitbg);border-color:#ecd9a0;animation:pulse 1.2s ease-in-out infinite}
.status.work::before{background:var(--wait)}
@keyframes pulse{50%{opacity:.6}}
.meters{display:flex;align-items:center;gap:1.1rem;margin:1rem 0;flex-wrap:wrap}
.pill{width:5.2rem;height:5.2rem;border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;
background:var(--soft);border:2px solid var(--line);color:var(--muted);font-size:.74rem;font-weight:600;line-height:1.15;
transition:background .15s,color .15s,border-color .15s}
.pill.on{background:var(--brand);border-color:var(--brand);color:#fff;animation:ripple 1.1s ease-out infinite}
.pill.bot.on{background:var(--ink);border-color:var(--ink);animation-name:rippledark}
@keyframes ripple{0%{box-shadow:0 0 0 0 rgba(180,68,42,.45)}100%{box-shadow:0 0 0 1rem rgba(180,68,42,0)}}
@keyframes rippledark{0%{box-shadow:0 0 0 0 rgba(29,36,51,.4)}100%{box-shadow:0 0 0 1rem rgba(29,36,51,0)}}
.bar{flex:1;min-width:8rem;height:.5rem;border-radius:999px;background:var(--soft);overflow:hidden}
.bar i{display:block;height:100%;width:0;background:var(--brand);transition:width .08s}
#talk{max-height:26rem;overflow:auto;margin:.8rem 0}
.stepsbox{align-self:flex-start;margin:-.3rem 0 .2rem .6rem;padding:.35rem .7rem;border-left:3px solid var(--line);
background:#fff;border-radius:0 9px 9px 0;font-size:.85rem;overflow-wrap:anywhere}
.stepsbox ol{margin:.2rem 0 0;padding-left:1.1rem}
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
        "<div id='talk' class='talk' aria-live='polite'></div>"
        "<p class='muted'>Usage: <span id='usage'>none yet</span>. "
        "<a href='/chat'>Text chat</a></p>"
        f"<style>{VOICE_STYLE}</style><script src='/voice/voice.js' defer></script>",
        size="mid", here="/voice", nav=_nav(True), user=username,
    )


def _nav(voice: bool) -> tuple[tuple[str, str], ...]:
    return (("Chat", "/chat"),) + ((("Voice", "/voice"),) if voice else ())


def _quick(label: str, message: str, token: str) -> str:
    """A suggestion button. It is a form of its own, so it also works without any script."""
    return (
        "<form method='post' action='/chat' data-busy>"
        f"<input type='hidden' name='csrf' value='{token}'>"
        f"<input type='hidden' name='message' value='{escape(message, quote=True)}'>"
        f"<button class='qbtn' type='submit'>{escape(label)}</button></form>"
    )


STARTERS = (
    ("Book a table for 2", "Book a table at Luna Trattoria for 2 tomorrow at 7pm"),
    ("Try a party of 12 (the server refuses)", "Book a table at Luna Trattoria for 12 tomorrow at 7pm"),
)


def _decision_item(step: Step) -> str:
    css, badge, _line = _step_outcome(step)
    rule = step.result.get("rule_id") if step.is_error else None
    if css == "ok":
        label = "Allowed"
    elif css == "wait":
        label = "Waiting for the diner's yes"
    else:
        label = f"Refused by {rule}" if rule else "Refused"
    message = step.result.get("message") if step.is_error else step.result.get("spoken_summary")
    args = ", ".join(f"{k}={escape(_short(v, 30))}" for k, v in step.args.items() if k in SHOWN_ARGS)
    return (
        f"<li class='k-{css}'><div class='dh'><b>{escape(step.tool)}</b><span class='tag {css}'>{escape(label)}</span></div>"
        + (f"<div class='dm'>{escape(_short(message, 170))}</div>" if message else "")
        + (f"<div class='dm'>{args}</div>" if args else "")
        + "</li>"
    )


def decisions_html(turns: list[tuple[str, str, tuple]]) -> str:
    """The panel beside the chat: every call the assistant made to the server and what the server decided, newest
    first. This is where a refusal and the rule behind it are easy to see."""
    groups: list[tuple[str, tuple]] = []
    asked = ""
    for who, text, steps in turns:
        if who == "you":
            asked = text
        elif steps:
            groups.append((asked, steps))
    legend = (
        "<div class='legend'><span class='tag ok'>Allowed</span><span class='tag no'>Refused by a rule</span>"
        "<span class='tag wait'>Waiting for the diner's yes</span></div>"
    )
    head = (
        "<h2>What the server decided</h2>"
        "<p class='muted'>Every action the assistant takes is a call to the FairTable server, and the server decides, "
        "not the assistant. Each call and its decision appear here.</p>" + legend
    )
    if not groups:
        return head + "<p class='muted'>Nothing yet. Ask for a table and watch the calls arrive.</p>"
    return head + "".join(
        f"<div class='turn'><div class='ask'>After: &ldquo;{escape(_short(asked, 70))}&rdquo;</div>"
        f"<ul class='dec'>{''.join(_decision_item(s) for s in steps)}</ul></div>"
        for asked, steps in reversed(groups)
    )


def chat_page(username: str, turns: list[tuple[str, str, tuple]], inbox: list[dict[str, Any]], csrf: str,
              voice: bool = False) -> str:
    """The demo chat: what the diner said, what the assistant answered (with the tool calls behind it), the
    server's decisions beside it, and the dev inbox."""
    talk = "".join(
        f"<div class='{'you' if who == 'you' else 'bot'}'><b class='who'>{'You' if who == 'you' else 'Assistant'}:</b> "
        f"{render_message(text) if who != 'you' else escape(text)}"
        f"{steps_html(steps) if who != 'you' else ''}</div>"
        for who, text, steps in turns
    )
    mail = "".join(
        f"<li><b>{escape(str(m.get('subject', '')))}</b> {escape(str(m.get('body', '')))}</li>"
        for m in inbox[-5:]
    ) or "<li class='muted'>Nothing yet.</li>"
    token = escape(csrf, quote=True)
    if not turns:
        quick = "".join(_quick(label, message, token) for label, message in STARTERS)
        hint = "<p class='muted'>Try: <i>Book a table at Luna Trattoria for 2 tomorrow at 7pm</i></p>"
    else:
        asks = turns[-1][0] == "assistant" and turns[-1][1].rstrip().endswith("?")
        quick = (_quick("Yes, please", "Yes, please", token) + _quick("No, thanks", "No, thanks", token)) if asks else ""
        hint = ""
    voice_link = "<p><a href='/voice'>Talk to the assistant by voice instead</a></p>" if voice else ""
    return layout(
        "Chat",
        "<div class='chat-grid'><section class='card'>"
        f"<h1>Your assistant</h1><p class='muted'>Signed in as {escape(username)}. This is a simulated voice assistant.</p>"
        f"{voice_link}{hint}"
        f"<div class='talk' id='talk'>{talk}</div><div id='talk-end'></div>"
        f"<div class='quick'>{quick}</div>"
        "<form id='chat-form' method='post' action='/chat' data-busy>"
        f"<input type='hidden' name='csrf' value='{token}'>"
        "<div class='sendrow'><input name='message' maxlength='500' autocomplete='off' autofocus required "
        "placeholder='Say something'><button class='approve' type='submit'>Send</button></div></form>"
        "<p class='muted'>A real model can take several seconds: press Send once and wait for the answer.</p>"
        f"<form method='post' action='/chat/reset'><input type='hidden' name='csrf' value='{token}'>"
        "<button class='decline' type='submit'>Start over</button></form></section>"
        f"<aside class='card panel'>{decisions_html(turns)}</aside></div>"
        f"<section class='card'><h2>Notifications</h2><ul>{mail}</ul></section>",
        size="wide", bare=True, here="/chat", nav=_nav(voice), user=username,
        scripts="<script src='/static/chat.js' defer></script>",
    )


def drop_page(audit: dict[str, Any], venue_name: str | None) -> str:
    """The public page of one Fair Drop. Before the draw it shows the commitment; after it, the whole record and a
    button that recomputes the draw in the visitor's browser (``/static/verify.js``). Nothing here is secret: it is
    the same record as the public MCP resource ``fairtable://drops/<id>/audit``."""
    data = json.dumps(audit, sort_keys=True).replace("<", "\\u003c")
    seats = ", ".join(_seat_label(k) for k in audit.get("slots", []))
    drop_at = str(audit.get("drop_at", "")).replace("T", " ").replace("Z", " UTC")
    facts = (
        "<dl class='facts'>"
        f"<dt>Restaurant</dt><dd>{escape(venue_name or str(audit.get('restaurant_id', '')))}</dd>"
        f"<dt>Seat</dt><dd>{escape(str(audit.get('date', '')))} {escape(seats)}</dd>"
        f"<dt>Places</dt><dd>{escape(str(audit.get('capacity', '')))}</dd>"
        f"<dt>Draw time</dt><dd>{escape(drop_at)}</dd>"
        f"<dt>Commitment</dt><dd><code>{escape(str(audit.get('commitment', '')))}</code></dd></dl>"
    )
    how = (
        "<ol class='steplist'>"
        "<li><b>Before entries open</b>, a secret seed is drawn and only its fingerprint, SHA-256(seed), is published. "
        "That is the commitment above, so nobody can pick a seed after seeing who entered.</li>"
        "<li><b>At the draw</b>, the seed is revealed. Each entry gets a draw key, HMAC-SHA256(seed, entry id), "
        "and the entries are ordered from the lowest key to the highest.</li>"
        "<li><b>The places go down that list</b>. Anyone can repeat this from the published record.</li></ol>"
    )
    if "seed" not in audit:
        body = (
            f"<div class='card'><h1>Fair Drop</h1>{facts}"
            "<p><span class='tag wait'>Not drawn yet</span> The seed is secret until the draw. Come back after the draw "
            "time to check the result yourself.</p></div>"
            f"<div class='card'><h2>How the draw works</h2>{how}</div>"
        )
        return layout("Fair Drop", body, size="mid", bare=True)
    rows = "".join(
        "<tr data-entry='{full}'><td>{n}</td><td title='{full}'><code>{short}</code></td><td><code>{key}</code></td>"
        "<td>{outcome}</td></tr>".format(
            n=n, full=escape(str(r.get("entry_id", "")), quote=True), short="&hellip;" + escape(str(r.get("entry_id", ""))[-8:]),
            key=escape(str(r.get("draw_key", ""))[:12]),
            outcome=_outcome_tag(str(r.get("outcome", "")), str(r.get("reason", ""))),
        )
        for n, r in enumerate(audit.get("order", []), 1)
    ) or "<tr><td colspan='4'>Nobody entered.</td></tr>"
    body = (
        f"<div class='card'><h1>Fair Drop</h1>{facts}"
        f"<p><span class='tag ok'>Drawn</span> {len(audit.get('winners', []))} of {escape(str(audit.get('capacity', '')))} "
        "place(s) given out.</p></div>"
        f"<div class='card'><h2>How the draw works</h2>{how}</div>"
        "<div class='card'><h2>Check this draw yourself</h2>"
        "<p>The button below runs in your browser. It does not ask this server anything: it recomputes every step from "
        "the record at the bottom of this page.</p>"
        "<button id='verify-btn' class='approve' type='button'>Verify this draw</button>"
        "<button id='tamper-btn' class='decline' type='button'>Change one result and verify again</button>"
        "<ul id='checks' class='checks' aria-live='polite'></ul>"
        "<noscript><p class='err'>This check needs JavaScript.</p></noscript>"
        "<h3 class='find'>Find your own ticket</h3>"
        "<p class='muted'>The record has no names: a ticket is a code. Your assistant gives you yours when you enter the draw. "
        "Paste it here and the page shows where it is in the list and what it won. Nothing is sent anywhere.</p>"
        "<div class='sendrow'><input id='ticket-input' placeholder='Your ticket code' autocomplete='off'>"
        "<button id='ticket-btn' class='decline' type='button'>Find my ticket</button></div>"
        "<p id='ticket-result' class='muted' aria-live='polite'></p>"
        "<details><summary>Check another copy of the record (for example the file kept in the audit bucket)</summary>"
        "<textarea id='paste' rows='8' placeholder='Paste the JSON record here'></textarea>"
        "<button id='paste-btn' class='decline' type='button'>Verify the pasted record</button></details></div>"
        "<div class='card'><h2>Draw order</h2>"
        f"<table><tr><th>#</th><th>Entry</th><th>Draw key</th><th>Result</th></tr>{rows}</table>"
        "<p class='muted'>Entries are hashes: the record contains no names. Hover an entry to see it in full.</p></div>"
        f"<script type='application/json' id='audit-data'>{data}</script>"
    )
    return layout("Fair Drop", body, size="mid", bare=True,
                  scripts="<script src='/static/verify.js' defer></script>")


def _outcome_tag(outcome: str, reason: str) -> str:
    css = {"won": "ok", "lost": "no", "skipped": "wait"}.get(outcome, "wait")
    label = outcome.capitalize() + (f" ({reason})" if reason else "")
    return f"<span class='tag {css}'>{escape(label)}</span>"
