"""Render a debug overlay SVG so glyph recovery can be eyeballed.

For each tab line we redraw the stave (string lines + barlines) and stamp every
recognised fret as text inside a box at the glyph's location.  If the boxes sit
on the right strings and the numbers read correctly, the pipeline is sound.
"""
from __future__ import annotations

import html
from typing import List

from .geometry import continuous_subpaths
from .glyphs import (
    DigitRecognizer,
    Glyph,
    group_glyphs,
    looks_like_digit,
    nearest_string,
)
from .notes import _cluster_digit_glyphs, _fret_from_digits
from .parse import TabLine, measure_boundaries


def overlay_line(line: TabLine, recog: DigitRecognizer) -> str:
    vb = line.viewbox
    parts: List[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}" '
        f'font-family="monospace">',
        '<rect x="{0}" y="{1}" width="{2}" height="{3}" fill="#111"/>'.format(*vb),
    ]

    # original stave geometry
    if line.strings_path:
        parts.append(
            f'<path d="{html.escape(line.strings_path)}" fill="none" '
            f'stroke="#444" stroke-width="0.4"/>'
        )
        for bx in measure_boundaries(line.strings_path):
            parts.append(
                f'<line x1="{bx}" y1="-2" x2="{bx}" y2="62" '
                f'stroke="#2a6" stroke-width="0.5"/>'
            )

    # recovered frets
    pairs = []
    for d, measure in line.note_paths:
        for sub in continuous_subpaths(d):
            pairs.append((sub, measure))
    glyphs = [g for g in group_glyphs(pairs) if looks_like_digit(g)]
    by_measure = {}
    for g in glyphs:
        by_measure.setdefault(g.measure, []).append(g)

    for mglyphs in by_measure.values():
        for grp in _cluster_digit_glyphs(mglyphs):
            fret, dist, cx, cy = _fret_from_digits(grp, recog)
            xmin = min(g.bbox.xmin for g in grp)
            xmax = max(g.bbox.xmax for g in grp)
            ymin = min(g.bbox.ymin for g in grp)
            ymax = max(g.bbox.ymax for g in grp)
            ok = fret is not None
            color = "#3c9" if ok else "#e44"
            parts.append(
                f'<rect x="{xmin:.1f}" y="{ymin:.1f}" '
                f'width="{xmax - xmin:.1f}" height="{ymax - ymin:.1f}" '
                f'fill="none" stroke="{color}" stroke-width="0.4"/>'
            )
            label = str(fret) if ok else "?"
            parts.append(
                f'<text x="{cx:.1f}" y="{ymax + 8:.1f}" fill="{color}" '
                f'font-size="6" text-anchor="middle">{label}</text>'
            )

    # measure numbers
    for x, num in line.measure_numbers:
        parts.append(
            f'<text x="{x:.1f}" y="-6" fill="#888" font-size="6">m{num}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)
