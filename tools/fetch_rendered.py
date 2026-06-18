"""Render a Songsterr tab page with a headless browser and save the DOM.

The free Songsterr page draws the tablature as SVG client-side after fetching
its note data.  Saving "view source" misses it; a real browser doesn't.  This
loads the public page like any browser would, scrolls through it so every
(virtualised) tab line gets drawn at least once, accumulates each line's SVG by
its line index, and writes a self-contained HTML document the SVG parser can
read.

Usage:
    python -m tools.fetch_rendered <songsterr-url> out/rendered.html
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

# Collect every rendered tab line (those that actually contain fret paths),
# keyed by its absolute data-line index so re-virtualised lines don't duplicate.
_GRAB_LINES = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('[data-player-key="tab"][data-line]')) {
    if (el.querySelector('[data-notes-measure]')) {
      out.push([parseInt(el.getAttribute('data-line'), 10), el.outerHTML]);
    }
  }
  return out;
}
"""


def fetch(url: str, out_path: str, timeout_ms: int = 60000) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1400, "height": 2200},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_selector("[data-notes-measure]", timeout=timeout_ms)
        page.wait_for_timeout(1500)

        # Header metadata (title / artist / track) lives outside the line SVGs.
        header = page.eval_on_selector(
            "#header", "el => el.outerHTML"
        ) if page.query_selector("#header") else ""

        lines = {}
        stagnant = 0
        # Small overlapping steps so no virtualised line is skipped between grabs.
        while stagnant < 4:
            for idx, html in page.evaluate(_GRAB_LINES):
                lines[idx] = html
            y = page.evaluate("() => window.scrollY")
            page.evaluate("() => window.scrollBy(0, window.innerHeight * 0.5)")
            page.wait_for_timeout(650)
            new_y = page.evaluate("() => window.scrollY")
            stagnant = stagnant + 1 if new_y <= y else 0
        # final grab at the very bottom
        for idx, html in page.evaluate(_GRAB_LINES):
            lines[idx] = html

        browser.close()

    ordered = "".join(lines[i] for i in sorted(lines))
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        f"{header}"
        '<section id="tablature">'
        f"{ordered}"
        "</section></body></html>"
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return doc


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    url, out_path = sys.argv[1], sys.argv[2]
    doc = fetch(url, out_path)
    import re
    measures = sorted({int(m) for m in re.findall(r'data-notes-measure="(\d+)"', doc)})
    print(f"rendered {len(doc)} bytes; {len(measures)} measures "
          f"({measures[0]}..{measures[-1]}) -> {out_path}")
    return 0 if measures else 1


if __name__ == "__main__":
    raise SystemExit(main())
