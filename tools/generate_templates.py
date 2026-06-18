"""Learn labeled fret-digit templates from a rendered fixture.

Songsterr draws fret numbers with a fixed font, so a handful of clean
exemplars from one page yields templates that generalise across pages.  We
cluster the digit glyphs by shape, then attach human-verified labels (the
clusters are ordered by frequency, which is stable for a given fixture).

Run:  python -m tools.generate_templates fixtures/speed-demon.sample.html
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from songsterr_tab.geometry import hamming
from songsterr_tab.glyphs import GLYPH_SIZE, group_glyphs, looks_like_digit
from songsterr_tab.geometry import continuous_subpaths
from songsterr_tab.parse import parse_lines, string_rows

# Labels for the rendered Speed Demon fixture, in descending cluster-frequency
# order.  Verified by rendering each cluster's medoid bitmap (see README).
# This fixture spans frets up to the teens, so all ten digits are present.
SPEED_DEMON_LABELS = ["1", "7", "0", "5", "2", "3", "8", "9", "4", "6"]


def collect_digit_glyphs(html_src: str):
    glyphs = []
    for line in parse_lines(html_src):
        rows = string_rows(line.strings_path) if line.strings_path else None
        pairs = []
        for d, measure in line.note_paths:
            for sub in continuous_subpaths(d):
                pairs.append((sub, measure))
        for g in group_glyphs(pairs):
            if looks_like_digit(g, rows) if rows else looks_like_digit(g):
                glyphs.append(g)
    return glyphs


def cluster(glyphs, threshold: int = 22):
    # Seed-based clustering: font glyphs of the same digit are near-identical,
    # so the first member is a stable representative.  Medoid is computed once
    # at the end for a slightly more robust template.
    clusters = []  # list of dict(seed=bitmap, members=[bitmap])
    for g in glyphs:
        bm = g.bitmap()
        best, bd = None, 10 ** 9
        for cl in clusters:
            d = hamming(bm, cl["seed"])
            if d < bd:
                bd, best = d, cl
        if best is not None and bd <= threshold:
            best["members"].append(bm)
        else:
            clusters.append({"seed": bm, "members": [bm]})
    clusters.sort(key=lambda c: -len(c["members"]))
    for cl in clusters:
        cl["medoid"] = _medoid(cl["members"])
    return clusters


def _medoid(bitmaps):
    bitmaps = bitmaps[:60]  # a sample is plenty; glyphs are near-identical
    best, bd = bitmaps[0], 10 ** 9
    for cand in bitmaps:
        s = sum(hamming(cand, other) for other in bitmaps)
        if s < bd:
            bd, best = s, cand
    return best


def main() -> int:
    fixture = sys.argv[1] if len(sys.argv) > 1 else "fixtures/speed-demon.sample.html"
    out = sys.argv[2] if len(sys.argv) > 2 else "templates/digits.json"
    labels = SPEED_DEMON_LABELS

    html_src = open(fixture, encoding="utf-8").read()
    glyphs = collect_digit_glyphs(html_src)
    clusters = cluster(glyphs)
    print(f"digit glyphs: {len(glyphs)}  clusters: {len(clusters)}")
    for i, cl in enumerate(clusters):
        lbl = labels[i] if i < len(labels) else "?"
        print(f"  cluster#{i}: label={lbl} count={len(cl['members'])}")

    if len(clusters) != len(labels):
        print(f"WARNING: cluster count {len(clusters)} != labels {len(labels)}")

    templates = [
        {"label": labels[i], "bitmap": clusters[i]["medoid"]}
        for i in range(min(len(clusters), len(labels)))
    ]
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"size": GLYPH_SIZE, "threshold": 40, "templates": templates}, fh)
    print(f"wrote {len(templates)} templates -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
