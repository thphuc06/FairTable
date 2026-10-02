"""The report's chart (plan task P3-3): how often each configuration ended in a safe state.

``python -m eval.charts eval/reports/run.json --out eval/reports/run.svg`` draws one static SVG from the JSON that
``python -m eval`` writes. Three groups of bars, one bar per configuration: refusals handled (NEG trials), attacks
blocked (ADV trials) and red-team attacks blocked (RT1 to RT12). Every bar shows its own count ("48/48"), so no number
is hidden behind the scale. Only measured values are drawn; a group with nothing measured is left out, never drawn as 0.

Design (skill `dataviz`): a horizontal grouped bar because the job is comparing a magnitude across a few named series;
colours are the first three slots of the reference categorical palette, which pass the validator for all pairs in light
and dark (CVD separation 9.2 and 9.4, normal-vision 24.0 and 20.9); the colour follows the configuration, never its
rank; light and dark values are CSS custom properties switched by `prefers-color-scheme`; the legend is always
present and every bar is labelled, so identity is never colour alone (the aqua slot is under 3:1 on the light
surface, which is why the labels are not optional). Each bar has a `<title>` (a native tooltip), and the whole picture
has a `<desc>` with every number for screen readers.
"""

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

from eval import gate
from eval.report import Summary

# colour slot by configuration (fixed: A1, the product, is slot 1)
SLOT = {"A1": 1, "A0": 2, "A2": 3}
NAMES = {"A0": "A0 open store", "A1": "A1 FairTable", "A2": "A2 no voice guards"}
ORDER = ("A0", "A1", "A2")

WIDTH = 760
LEFT = 200  # room for the group labels
PLOT = 440  # 0 to 100 %
BAR_H, BAR_GAP, GROUP_GAP = 20, 6, 26
TOP = 112

STYLE = """
.viz-root { color-scheme: light; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781; --grid:#e1e0d9;
  --base:#c3c2b7; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; }
@media (prefers-color-scheme: dark) { .viz-root { color-scheme: dark; --surface:#1a1a19; --ink:#ffffff;
  --ink2:#c3c2b7; --muted:#898781; --grid:#2c2c2a; --base:#383835; --s1:#3987e5; --s2:#d95926; --s3:#199e70; } }
text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; fill: var(--ink2); font-size: 13px; }
.title { font-size: 17px; font-weight: 600; fill: var(--ink); }
.sub { font-size: 12.5px; fill: var(--muted); }
.group { font-size: 14px; font-weight: 600; fill: var(--ink); }
.tick { font-size: 12px; fill: var(--muted); }
.val { font-size: 13px; fill: var(--ink2); }
.grid { stroke: var(--grid); stroke-width: 1; }
.base { stroke: var(--base); stroke-width: 1; }
.bg { fill: var(--surface); }
.c1 { fill: var(--s1); } .c2 { fill: var(--s2); } .c3 { fill: var(--s3); }
""".strip()


def measures(summaries: dict[str, Summary], redteam: dict[str, dict]) -> list[tuple[str, dict[str, tuple[int, int]]]]:
    """(group label, {config: (ok, total)}) for every group that was measured."""
    groups = []
    for label, cat in (("Refusals handled (NEG)", "NEG"), ("Attacks blocked (ADV)", "ADV")):
        values = {c: tuple(summaries[c].blocked[cat]) for c in ORDER if c in summaries and summaries[c].blocked[cat][1]}
        if values:
            groups.append((label, values))
    rt = {c: (redteam[c]["blocked"], redteam[c]["total"]) for c in ORDER if c in redteam and redteam[c]["total"]}
    if rt:
        groups.append(("Red-team attacks blocked", rt))
    return groups


def bar_path(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    """A bar square at the baseline and rounded at the data end."""
    if w <= 0:
        return ""
    r = min(r, w, h / 2)
    return (f"M{x:.1f},{y:.1f} h{w - r:.1f} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r:.1f} a{r},{r} 0 0 1 {-r},{r} "
            f"h{-(w - r):.1f} z")


def render_svg(summaries: dict[str, Summary], redteam: dict[str, dict]) -> str:
    groups = measures(summaries, redteam)
    if not groups:
        raise ValueError("nothing was measured, so there is nothing to draw")
    provider = next(iter(summaries.values())).provider
    k = next(iter(summaries.values())).k
    group_h = lambda g: len(g[1]) * BAR_H + (len(g[1]) - 1) * BAR_GAP  # noqa: E731
    height = TOP + sum(group_h(g) + GROUP_GAP for g in groups) + 24
    desc = "; ".join(
        f"{label}: " + ", ".join(f"{NAMES[c]} {ok} of {total}" for c, (ok, total) in vals.items())
        for label, vals in groups
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" width="{WIDTH}" height="{height}" '
        'role="img" class="viz-root" aria-labelledby="t d">',
        f"<style>{STYLE}</style>",
        '<title id="t">How often each configuration ended in a safe state</title>',
        f'<desc id="d">{escape(desc)}</desc>',
        f'<rect class="bg" width="{WIDTH}" height="{height}" rx="8"/>',
        '<text class="title" x="24" y="34">How often each configuration ended in a safe state</text>',
        (f'<text class="sub" x="24" y="56">Model: {escape(provider)}'
         + (" (a script, not a real model: this checks the harness and the rules)" if provider == "mock" else "")
         + f". 40 tasks x {k} trials per configuration.</text>"),
    ]
    # legend: always present, one swatch per configuration
    x = 24
    for c in ORDER:
        if c not in summaries:
            continue
        out.append(f'<rect class="c{SLOT[c]}" x="{x}" y="72" width="14" height="14" rx="3"/>')
        out.append(f'<text x="{x + 20}" y="84">{escape(NAMES[c])}</text>')
        x += 40 + 7.2 * len(NAMES[c])
    bottom = TOP + sum(group_h(g) + GROUP_GAP for g in groups) - GROUP_GAP + 8
    for pct in (0, 25, 50, 75, 100):  # recessive grid, drawn first so the bars sit on top of it
        gx = LEFT + PLOT * pct / 100
        out.append(f'<line class="grid" x1="{gx}" y1="{TOP - 8}" x2="{gx}" y2="{bottom}"/>')
        out.append(f'<text class="tick" x="{gx}" y="{bottom + 16}" text-anchor="middle">{pct}%</text>')
    out.append(f'<line class="base" x1="{LEFT}" y1="{TOP - 8}" x2="{LEFT}" y2="{bottom}"/>')
    y = TOP
    for label, vals in groups:
        gh = group_h((label, vals))
        out.append(f'<text class="group" x="24" y="{y + gh / 2 + 5:.1f}">{escape(label)}</text>')
        for bi, (c, (ok, total)) in enumerate(vals.items()):
            by = y + bi * (BAR_H + BAR_GAP)
            w = PLOT * ok / total
            tip = f"{NAMES[c]}: {ok} of {total} ({100 * ok / total:.0f}%)"
            out.append(f"<g><title>{escape(tip)}</title>")
            if w > 0:
                out.append(f'<path class="c{SLOT[c]}" d="{bar_path(LEFT, by, w, BAR_H)}"/>')
            out.append(f'<text class="val" x="{LEFT + w + 8:.1f}" y="{by + BAR_H - 6}">{ok}/{total}</text></g>')
        y += gh + GROUP_GAP
    out.append("</svg>")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.charts")
    parser.add_argument("report", type=Path, help="the JSON written by `python -m eval --out ...`")
    parser.add_argument("--out", type=Path, help="where to write the SVG (default: beside the report)")
    args = parser.parse_args(argv)
    summaries, redteam = gate.load(args.report)
    out = args.out or args.report.with_suffix(".svg")
    out.write_text(render_svg(summaries, redteam), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
