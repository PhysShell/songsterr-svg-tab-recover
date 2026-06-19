#!/usr/bin/env python3
"""Capture the *rendered* DOM of a Songsterr tab for offline note recovery.

Songsterr renders tab lines lazily as you scroll, so we scroll the whole song
to force every line into the DOM, then dump outerHTML -- the same thing you'd do
by hand in DevTools, automated.

Usage:
    python scripts/capture_songsterr.py <songsterr-url> --track 1 --out will-swan.rendered.html

Track selection is by URL suffix: track 0 is the bare ...-tab-s<id>, track N is
...-tab-s<id>t<N>. Pass --track to append it for you.
"""
import argparse, re, sys
from playwright.sync_api import sync_playwright

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--track", type=int, default=0, help="track index (0 = first)")
    ap.add_argument("--out", default="rendered.html")
    ap.add_argument("--timeout", type=int, default=45000)
    ap.add_argument("--show", action="store_true", help="run headed (visible browser)")
    args = ap.parse_args()

    url = args.url.split("?")[0].rstrip("/")
    url = re.sub(r"t\d+$", "", url)              # strip any existing tN
    if args.track:
        url += f"t{args.track}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.show)
        ctx = browser.new_context(ignore_https_errors=True,
                                  viewport={"width": 1500, "height": 1000})
        pg = ctx.new_page()
        print(f"loading {url}", file=sys.stderr)
        pg.goto(url, wait_until="domcontentloaded", timeout=args.timeout)
        pg.wait_for_selector('[data-testid="tab-strings-path"]', timeout=args.timeout)
        name = pg.eval_on_selector('.gYbqeG_name', 'e=>e.textContent') \
            if pg.query_selector('.gYbqeG_name') else '?'
        print(f"track: {name}", file=sys.stderr)

        # Songsterr renders tab lines lazily as they near the viewport. Walk down
        # the page in small steps -- never jumping to the end (which skips the
        # middle, leaving those lines as bare measure-number placeholders) --
        # pausing so each line draws its stave before moving on.
        count = lambda: pg.eval_on_selector_all('[data-testid="tab-strings-path"]', 'e=>e.length')
        state = lambda: pg.evaluate("()=>[Math.round(scrollY), document.body.scrollHeight, innerHeight]")
        stable = 0
        for _ in range(1000):
            y, _h, ih = state()
            n = count()
            pg.mouse.wheel(0, int(ih * 0.5))
            pg.wait_for_timeout(250)
            y2, _h2, _ = state()
            if y2 <= y + 2 and count() == n:        # at the bottom, nothing new
                stable += 1
                if stable >= 3:
                    break
            else:
                stable = 0
        total = pg.eval_on_selector_all('[data-player-key="tab"]', 'e=>e.length')
        print(f"rendered staves: {count()} / {total} tab lines", file=sys.stderr)

        html = pg.content()
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"-> {args.out} ({len(html)//1024} KB)", file=sys.stderr)
        browser.close()

if __name__ == "__main__":
    main()
