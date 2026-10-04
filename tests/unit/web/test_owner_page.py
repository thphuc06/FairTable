"""The owner page tells the owner where the rules text comes from and what it is (and is not)."""

from server.domain.models import Venue
from web.pages import owner_page

LUNA = Venue("luna-trattoria", "Luna Trattoria", "Italian", "Seattle", "d", 60, 40, 0, 0)
CSRF = {"share": "a", "terms": "b", "drops": "c"}


def test_the_rules_text_is_named_as_a_public_mcp_resource_and_not_a_tool():
    html = owner_page(LUNA, "owner-luna", CSRF, [])
    assert "fairtable://restaurants/luna-trattoria/policies" in html
    assert "public MCP resource" in html and "not a tool" in html
    assert "checked with Cedar policies" in html and "G1 to G4 at the AgentCore Gateway" in html
    assert "whether a given assistant does is up to that assistant" in html
    assert "enforces these rules whether or not the assistant reads it" in html


def test_the_rules_text_mentions_one_table_per_day():
    assert "one confirmed table per day" in owner_page(LUNA, "owner-luna", CSRF, [])


def test_the_rules_are_formatted_not_shown_as_raw_markdown():
    html = owner_page(LUNA, "owner-luna", CSRF, [])
    rules = html[html.index("<div class='rules'>"):]
    assert "**" not in rules.split("</div>")[0] and "`" not in rules.split("</div>")[0]
    # a bullet that is wrapped over two lines in the text is one list item
    assert ("<li>Only a <b>verified agent acting for a signed-in diner</b> with the <code>fairtable/book</code> "
            "permission can hold, confirm, change or cancel a booking or join a waitlist") in rules


def test_the_rules_text_cannot_inject_markup():
    from web.pages import rules_html

    out = rules_html("- **bold** <script>alert(1)</script> `code`\n  continued <b>x</b>")
    assert "<script>" not in out and "&lt;script&gt;" in out and "<b>bold</b>" in out and "&lt;b&gt;x&lt;/b&gt;" in out


def test_the_fair_drop_form_has_a_draw_time_step_and_an_empty_message():
    html = owner_page(LUNA, "owner-luna", CSRF, [], seats=[], draw=6)
    assert "<option value='6' selected>" in html and "name='hours_before' value='6'" in html
    assert "No seat is far enough away" in html and "method='get' action='/owner'" in html
