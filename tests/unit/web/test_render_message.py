"""The chat page shows the assistant's markdown as formatting, and nothing else it could smuggle in."""

import re

import pytest

from web.pages import render_message

def render(text: str) -> str:
    return render_message(text)


def test_bold_italic_and_code():
    assert render("**Luna** is *cosy* and `LUN-1`") == "<p><b>Luna</b> is <i>cosy</i> and <code>LUN-1</code></p>"


def test_bullets_become_a_list_and_the_intro_stays_a_paragraph():
    html = render("Three places:\n\n- **Ember Grill**: steak\n- **Luna**: pasta\n\nWhere to?")
    assert html == ("<p>Three places:</p><ul><li><b>Ember Grill</b>: steak</li><li><b>Luna</b>: pasta</li></ul>"
                    "<p>Where to?</p>")


def test_a_list_can_follow_text_without_a_blank_line_and_numbers_make_an_ordered_list():
    html = render("Options:\n1. one\n2) two")
    assert html == "<p>Options:</p><ol><li>one</li><li>two</li></ol>"


def test_a_bullet_list_switching_to_numbers_starts_a_new_list():
    assert render("- a\n1. b") == "<ul><li>a</li></ul><ol><li>b</li></ol>"


def test_single_newlines_are_line_breaks_and_blank_lines_split_paragraphs():
    assert render("one\ntwo\n\nthree") == "<p>one<br>two</p><p>three</p>"


def test_headings_are_shown_bold_without_the_hashes():
    assert render("### Rules\ntext") == "<p><b>Rules</b><br>text</p>"


def test_windows_line_endings_are_handled():
    assert render("a\r\nb") == "<p>a<br>b</p>"


@pytest.mark.parametrize("attack", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "**<b onmouseover=alert(1)>x</b>**",
    "[click](javascript:alert(1))",
    "- <a href='http://evil.example'>x</a>",
])
def test_markup_from_the_model_is_never_live(attack):
    html = render(attack)
    tags = set(re.findall(r"</?([a-zA-Z][a-zA-Z0-9]*)", html))
    assert tags <= {"p", "br", "b", "i", "code", "ul", "ol", "li"}, tags  # nothing the model wrote became a tag
    assert "&lt;" in html or "javascript:" in html  # shown as text, not interpreted


def test_links_are_never_made_live():
    """The assistant has no links to give any more (D-051); whatever it writes stays text."""
    assert "<a " not in render("see http://evil.example/consent/abc")
    assert "<a " not in render("http://localhost:8080/consent/abc")


def test_underscores_in_a_word_are_not_read_as_italics():
    html = render("a_b_c and *real*")
    assert "<i>real</i>" in html and "a_b_c" in html


def test_unbalanced_marks_are_left_alone_and_empty_text_is_empty():
    assert render("2 * 3 = 6 and **open") == "<p>2 * 3 = 6 and **open</p>"
    assert render("") == ""
