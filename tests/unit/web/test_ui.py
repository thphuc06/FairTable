"""The page design: the shared frame, the chat page with the server's decisions beside it, the owner console cards, and the
public Fair Drop page whose button recomputes the draw in the browser."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server.domain.fairdrop import DROP_ALLOCATED, Drop, DropEntry, build_audit, commitment, entry_id, order_entries
from server.domain.models import Venue
from simulator.events import Step
from web import pages
from web.app import WebDeps, create_app

ROOT = Path(__file__).resolve().parents[3]
LUNA = Venue("luna-trattoria", "Luna Trattoria", "Italian", "Seattle", "d", 60, 40, 0, 0)
CSRF = {"share": "a", "terms": "b", "drops": "c"}

OK = Step("availability_check", {"restaurant_id": "luna-trattoria", "party_size": 2},
          {"spoken_summary": "There is a table at 7 PM."})
DENIED = Step("reservation_hold", {"offer_id": "x"},
              {"error": "POLICY_DENIED", "rule_id": "G3_party_size_max_10", "message": "Large groups call the restaurant."}, True)
NEEDS_YES = Step("reservation_confirm", {"hold_id": "h1"},
                 {"error": "CONFIRMATION_REQUIRED", "message": "I need the user's yes first."}, True)

SEED = bytes(range(32))


def an_audit(n: int = 4) -> tuple[Drop, dict]:
    drop = Drop("drop-test", "luna-trattoria", "2026-10-09", ("2000#T2",), "2026-10-02T10:00:00Z",
                "2026-10-08T18:00:00Z", commitment(SEED), status=DROP_ALLOCATED)
    entries = [DropEntry(entry_id("drop-test", f"sub{i}"), "drop-test", f"sub{i}", None, None, None, frozenset(), 2,
                         f"2026-10-02T10:0{i}:00Z") for i in range(n)]  # real ticket ids: the drop id, then a SHA-256
    order = order_entries(SEED, [e.entry_id for e in entries])
    outcomes = {e: ("won" if i == 0 else "lost", None) for i, e in enumerate(order)}
    return drop, build_audit(drop, SEED, entries, outcomes, "2026-10-08T18:00:01Z")


# ---------------------------------------------------------------- the frame
def test_every_page_has_the_header_and_only_the_links_that_apply():
    assert "class='brand'" in pages.landing_page() and "href='/voice'" not in pages.chat_page("alice", [], [], "t")
    assert "href='/voice'" in pages.chat_page("alice", [], [], "t", voice=True)
    owner = pages.owner_page(LUNA, "owner-luna", CSRF, [])
    assert "href='/owner' class='here'" in owner and "owner-luna" in owner


def test_the_landing_page_still_links_to_chat_and_owner():
    html = pages.landing_page()
    assert "href='/chat'" in html and "href='/owner'" in html and "Verified identity" in html


# ---------------------------------------------------------------- the chat page
def test_the_decisions_panel_says_what_the_server_decided_and_which_rule():
    html = pages.chat_page("alice", [("you", "Book for 12", ()), ("assistant", "I could not.", (OK, DENIED, NEEDS_YES))],
                           [], "t")
    panel = html[html.index("<aside"):html.index("</aside>")]
    assert "What the server decided" in panel and "Refused by G3_party_size_max_10" in panel
    assert "Allowed" in panel and "Waiting for the diner&#x27;s yes" in panel and "Large groups call the restaurant." in panel
    assert "After: &ldquo;Book for 12&rdquo;" in panel and "k-no" in panel and "k-wait" in panel and "k-ok" in panel


def test_the_panel_explains_itself_before_the_first_question():
    html = pages.chat_page("alice", [], [], "t")
    assert "Nothing yet" in html and "the server decides" in html


def test_the_panel_lists_the_newest_exchange_first():
    first = Step("restaurant_search", {"query": "first"}, {"spoken_summary": "one"})
    second = Step("restaurant_search", {"query": "second"}, {"spoken_summary": "two"})
    turns = [("you", "ask one", ()), ("assistant", "a", (first,)), ("you", "ask two", ()), ("assistant", "b", (second,))]
    panel = pages.decisions_html(turns)
    assert panel.index("ask two") < panel.index("ask one")


def test_the_panel_escapes_everything_it_shows():
    evil = Step("<script>alert(1)</script>", {"query": "<img src=x>"}, {"error": "X", "message": "<b>hi</b>"}, True)
    panel = pages.decisions_html([("you", "<i>q</i>", ()), ("assistant", "a", (evil,))])
    assert "<script" not in panel and "<img" not in panel and "<b>hi</b>" not in panel and "<i>q</i>" not in panel


def test_suggestions_start_a_conversation_and_answer_a_question_with_forms_that_need_no_script():
    start = pages.chat_page("alice", [], [], "tok")
    assert start.count("class='qbtn'") == 2 and "for 12 tomorrow" in start
    assert "name='csrf' value='tok'" in start
    asked = pages.chat_page("alice", [("you", "book", ()), ("assistant", "Shall I book it?", ())], [], "tok")
    assert "value='Yes, please'" in asked and "value='No, thanks'" in asked
    plain = pages.chat_page("alice", [("you", "hi", ()), ("assistant", "Hello.", ())], [], "tok")
    assert "Yes, please" not in plain


def test_the_messages_keep_their_classes_and_the_chat_loads_one_script_of_ours():
    html = pages.chat_page("alice", [("you", "hi", ()), ("assistant", "Hello.", ())], [], "t")
    assert re.findall(r"<div class=.(you|bot).>", html) == ["you", "bot"]
    assert "<script src='/static/chat.js' defer></script>" in html and "<script>" not in html


# ---------------------------------------------------------------- the owner console
def test_the_owner_console_shows_the_numbers_at_a_glance_and_links_each_drop_to_its_check():
    drop = SimpleNamespace(drop_id="drop-sakura-2026-10-09", date="2026-10-09", slot_keys=("2000#T2",),
                           drop_at="2026-10-08T18:00:00Z", status="open", commitment="ab" * 32)
    html = pages.owner_page(LUNA, "owner-luna", CSRF, [{"at": "2026-10-04T10:00:00Z", "tool": "reservation_hold",
                                                        "decision": "deny", "rule_ids": ["S2"]}], drops=[drop])
    assert "class='stat'" in html and f"<b>{LUNA.agent_share_pct}%</b>" in html
    assert "href='/drops/drop-sakura-2026-10-09'" in html
    assert "tag no" in html and "Refused" in html


# ---------------------------------------------------------------- the Fair Drop page
def app_with(drop: Drop | None, venue: Venue | None = LUNA) -> TestClient:
    store = SimpleNamespace(get_drop=lambda drop_id: drop if drop and drop.drop_id == drop_id else None,
                            get_venue=lambda venue_id: venue)
    deps = WebDeps(settings=SimpleNamespace(web_public_url="http://localhost:8080"), store=store, clock=None, login=None,
                   sessions=SimpleNamespace(read=lambda cookie: None), new_id=None)
    return TestClient(create_app(deps))


def test_the_page_before_the_draw_shows_the_commitment_and_never_the_seed():
    drop, _ = an_audit()
    pending = Drop(drop.drop_id, drop.venue_id, drop.date, drop.slot_keys, drop.opens_at, drop.drop_at, drop.commitment,
                   seed_hex=SEED.hex())  # the secret is stored, and must not reach the page
    r = app_with(pending).get(f"/drops/{drop.drop_id}")
    assert r.status_code == 200 and drop.commitment in r.text and "Not drawn yet" in r.text
    assert SEED.hex() not in r.text and "verify-btn" not in r.text and "audit-data" not in r.text


def test_the_page_after_the_draw_has_the_record_and_the_check():
    drop, audit = an_audit()
    full = Drop(drop.drop_id, drop.venue_id, drop.date, drop.slot_keys, drop.opens_at, drop.drop_at, drop.commitment,
                status=DROP_ALLOCATED, seed_hex=SEED.hex(), audit=audit)
    r = app_with(full).get(f"/drops/{drop.drop_id}")
    assert r.status_code == 200 and "Verify this draw" in r.text and "Luna Trattoria" in r.text
    record = json.loads(re.search(r"<script type='application/json' id='audit-data'>(.*?)</script>", r.text, re.S).group(1))
    assert record == audit and record["seed"] == SEED.hex()
    assert "<script src='/static/verify.js' defer></script>" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"] and "unsafe-inline'" in r.headers["content-security-policy"]


def test_markup_in_the_record_cannot_close_the_data_block():
    _, audit = an_audit()
    audit["entries"][0] = "</script><script>alert(1)</script>"
    html = pages.drop_page(audit, "Luna")
    assert html.count("<script") == 2 and "</script><script>alert" not in html  # the data block and verify.js only


def test_an_unknown_or_odd_drop_id_is_a_plain_404():
    client = app_with(None)
    assert client.get("/drops/nope").status_code == 404
    assert client.get("/drops/a%23b").status_code == 404


def test_the_page_scripts_are_served_without_a_sign_in_and_nothing_else_is():
    client = app_with(None)
    for name in ("chat.js", "verify.js"):
        r = client.get(f"/static/{name}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
    assert client.get("/static/voice.js").status_code == 404 and client.get("/static/..%2Fapp.py").status_code == 404


# ---------------------------------------------------------------- the browser check agrees with the server
NODE = shutil.which("node")
RUN_VERIFY = """
const { verifyAudit } = require(process.argv[1]);
let input = '';
process.stdin.on('data', d => input += d).on('end', async () => {
  const results = await verifyAudit(JSON.parse(input));
  console.log(JSON.stringify(results.map(r => r.ok)));
});
"""


def js_results(audit: dict) -> list[bool]:
    done = subprocess.run([NODE, "-e", RUN_VERIFY, str(ROOT / "web" / "static" / "verify.js")], input=json.dumps(audit),
                          capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_the_script_accepts_a_real_record_and_rejects_each_kind_of_tampering():
    _, audit = an_audit(5)
    assert js_results(audit) == [True] * 6
    wrong_seed = {**audit, "seed": "00" * 32}
    assert js_results(wrong_seed)[0] is False
    swapped = json.loads(json.dumps(audit))
    swapped["order"][0], swapped["order"][1] = swapped["order"][1], swapped["order"][0]
    assert not all(js_results(swapped))
    other_winner = json.loads(json.dumps(audit))
    other_winner["winners"] = [other_winner["order"][1]["entry_id"]]
    assert js_results(other_winner)[4] is False
    passed_over = json.loads(json.dumps(audit))
    passed_over["order"][0]["outcome"] = "lost"
    passed_over["winners"] = []
    assert js_results(passed_over)[5] is False


RUN_FIND = """
const { findTicket } = require(process.argv[1]);
let input = '';
process.stdin.on('data', d => input += d).on('end', () => {
  const { audit, code } = JSON.parse(input);
  console.log(JSON.stringify(findTicket(audit, code)));
});
"""


def js_find(audit: dict, code: str):
    done = subprocess.run([NODE, "-e", RUN_FIND, str(ROOT / "web" / "static" / "verify.js")], input=json.dumps({"audit": audit, "code": code}),
                          capture_output=True, text=True, timeout=60, check=True)
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_a_diner_finds_their_own_ticket_by_its_code_whole_or_by_its_fingerprint():
    _, audit = an_audit(5)
    row = audit["order"][2]
    digest = row["entry_id"].rsplit("~", 1)[-1] if "~" in row["entry_id"] else row["entry_id"]
    for code in (row["entry_id"], row["entry_id"].upper(), f"  {row['entry_id']}  ", digest):
        found = js_find(audit, code)
        assert found and found["position"] == 3 and found["of"] == 5 and found["outcome"] == row["outcome"], code
    assert js_find(audit, "no-such-ticket") is None and js_find(audit, "") is None


def test_the_page_has_the_ticket_box_and_tells_the_rows_apart():
    _, audit = an_audit(3)
    html = pages.drop_page(audit, "Luna")
    assert "id='ticket-input'" in html and "id='ticket-btn'" in html and "id='ticket-result'" in html
    rows = re.findall(r"<tr data-entry='([^']+)'><td>(\d+)</td><td title='[^']+'><code>(&hellip;[^<]+)</code>", html)
    assert len(rows) == 3 and len({short for _, _, short in rows}) == 3  # the label is the end of the code, so it differs


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_a_record_that_cannot_be_read_is_reported_not_thrown():
    assert js_results({"seed": "zz"}) == [False]


# ---------------------------------------------------------------- the slider and the voice page look
def test_the_share_form_carries_what_the_slider_needs_and_still_works_without_the_script():
    html = pages.owner_page(LUNA, "owner-luna", CSRF, [])
    form = html[html.index("<form data-share"):html.index("</form>", html.index("<form data-share"))]
    assert f"data-seats='{LUNA.seats_per_day}'" in form and f"data-current='{LUNA.agent_share_pct}'" in form
    assert "action='/owner/agent-share'" in form and "name='pct'" in form and "name='csrf'" in form
    assert "<script src='/static/owner.js' defer></script>" in html


def test_the_owner_pages_may_load_their_script_and_nothing_else():
    client = app_with(None)
    assert client.get("/static/owner.js").status_code == 200
    csp = client.get("/owner", follow_redirects=False).headers["content-security-policy"]
    assert "script-src 'self'" in csp and "connect-src" not in csp and "default-src 'none'" in csp


def test_the_voice_page_keeps_the_ids_its_script_uses_and_the_shared_frame():
    html = pages.voice_page("diner-alice")
    for element in ("start", "stop", "status", "ind-you", "ind-bot", "level", "talk", "usage"):
        assert f"id='{element}'" in html
    assert "class='brand'" in html and "href='/chat'" in html and "class='talk'" in html


def test_the_boxes_in_a_conversation_never_shrink_to_nothing():
    """A scrolling flex column squeezes its children: the tool-call box (overflow: auto) went to zero height on the voice page."""
    assert ".talk>*{flex:none}" in pages.STYLE and ".talk{display:flex;flex-direction:column" in pages.STYLE


def test_the_tool_calls_under_an_answer_are_all_visible_without_scrolling_inside_the_box():
    """The box once had a max-height with its own scrollbar: from the third tool call on, the list was cut off."""
    rule = pages.VOICE_STYLE.split(".stepsbox{", 1)[1].split("}", 1)[0]
    assert "max-height" not in rule and "overflow:auto" not in rule


def test_the_voice_assistant_is_told_to_keep_answers_short_and_not_to_make_facts_up():
    from web.voice_nova import VOICE_PROMPT

    assert "two short sentences" in VOICE_PROMPT and "never make up" in VOICE_PROMPT
    assert "do not name any limit" in VOICE_PROMPT and "suggest calling the restaurant" in VOICE_PROMPT
