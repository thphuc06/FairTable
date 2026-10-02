"""P3-3: the chart is drawn from measured values only, and a picture that cannot be drawn says so."""

import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from eval import charts, gate
from tests.unit.eval.test_gate import WEAK_A0, WEAK_A2, summary

NS = {"s": "http://www.w3.org/2000/svg"}
REPORT = Path(__file__).resolve().parents[3] / "eval" / "reports" / "mock-k4-2026-10-02.json"
RT = {"A1": {"blocked": 12, "total": 12, "expected": 12}, "A0": {"blocked": 8, "total": 12, "expected": 8},
      "A2": {"blocked": 11, "total": 12, "expected": 11}}


def drawn(summaries, redteam):
    return ET.fromstring(charts.render_svg(summaries, redteam))


def test_the_chart_is_valid_xml_with_every_count_written_on_its_bar():
    root = drawn({"A1": summary(), "A0": WEAK_A0, "A2": WEAK_A2}, RT)
    texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    for label in ("32/32", "48/48", "30/48", "40/48", "12/12", "8/12", "11/12", "A1 FairTable"):
        assert label in texts, label
    desc = root.find("s:desc", NS).text
    assert "A0 open store 30 of 48" in desc and "A1 FairTable 12 of 12" in desc  # the screen reader's table


def test_the_mock_banner_is_on_the_picture():
    text = charts.render_svg({"A1": summary()}, {})
    assert "a script, not a real model" in text
    real = charts.render_svg({"A1": replace(summary(), provider="deepseek")}, {})
    assert "deepseek" in real and "a script" not in real


def test_a_group_that_was_not_measured_is_left_out_not_drawn_as_zero():
    root = drawn({"A1": summary()}, {})  # no red team
    texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert "Red-team attacks blocked" not in texts
    no_adv = drawn({"A1": summary(blocked={"NEG": (32, 32), "ADV": (0, 0)})}, {})
    assert "Attacks blocked (ADV)" not in [t.text for t in no_adv.iter("{http://www.w3.org/2000/svg}text")]


def test_nothing_measured_is_an_error():
    with pytest.raises(ValueError):
        charts.render_svg({"A1": summary(blocked={"NEG": (0, 0), "ADV": (0, 0)})}, {})


def test_a_zero_bar_has_no_path_and_a_full_bar_ends_at_the_scale():
    assert charts.bar_path(200, 10, 0, 20) == ""
    root = drawn({"A1": summary(), "A0": WEAK_A0}, {})
    assert len(root.findall(".//s:path", NS)) == 4  # two groups, two configurations, every bar longer than zero
    full = charts.bar_path(200, 10, charts.PLOT, 20)
    assert f"h{charts.PLOT - 4:.1f}" in full


def test_the_committed_report_can_be_drawn(tmp_path):
    out = tmp_path / "chart.svg"
    assert charts.main([str(REPORT), "--out", str(out)]) == 0
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    assert len(root.findall(".//s:path", NS)) == 8  # nine bars, one of them (A0 under attack) is empty
    assert gate.load(REPORT)[0]["A0"].blocked["ADV"] == (0, 48)
