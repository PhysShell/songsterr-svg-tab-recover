"""Fret-digit recovery via structural glyph matching.

In a Songsterr-rendered tab the fret numbers are *not* ``<text>`` nodes -- the
layout engine has already baked them into Bezier outlines inside the
``data-notes-measure`` paths.  Because they come from a font, every instance of
a given digit shares the same outline up to translation/scale, so we can
recover them with deterministic template matching instead of fuzzy OCR.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Sequence, Tuple

from svgpathtools import Path

from .geometry import (
    BBox,
    hamming,
    rasterize,
    sample_polyline,
    subpath_bbox,
)

GLYPH_SIZE = 16
# Fallback string-row y-positions (the 6 horizontal lines of a tab stave).
# These are DERIVED per line from the strings path when available -- never
# rely on the constant alone, since fret glyphs are mapped to a string by
# nearest row and a hardcoded guess silently drops digits whose centre lands
# just outside the tolerance.
DEFAULT_STRING_ROWS = (0.5, 12.5, 24.5, 36.5, 48.5, 60.5)


@dataclass
class Glyph:
    """A rendered character: one or more continuous subpaths drawn together."""

    subs: List[Path]
    measure: int

    @property
    def bbox(self) -> BBox:
        boxes = [subpath_bbox(s) for s in self.subs]
        return BBox(
            min(b.xmin for b in boxes),
            min(b.ymin for b in boxes),
            max(b.xmax for b in boxes),
            max(b.ymax for b in boxes),
        )

    def bitmap(self, size: int = GLYPH_SIZE) -> List[int]:
        polys = [sample_polyline(s) for s in self.subs]
        return rasterize(polys, self.bbox, size)


def group_glyphs(subs_with_measure: Sequence[Tuple[Path, int]]) -> List[Glyph]:
    """Cluster raw subpaths into glyphs.

    A digit's counter (the hole in 0/6/8/9) is a separate continuous subpath
    that sits *inside* the outer contour, so it x-overlaps it; neighbouring
    digits do not x-overlap.  Grouping on x-overlap within the same string row
    therefore reunites a glyph with its counters without merging neighbours.
    """
    items = []
    for sub, measure in subs_with_measure:
        items.append((sub, measure, subpath_bbox(sub)))
    items.sort(key=lambda it: (it[1], it[2].xmin))

    glyphs: List[Glyph] = []
    boxes: List[BBox] = []
    for sub, measure, box in items:
        placed = False
        for g, gbox in zip(glyphs, boxes):
            last = subpath_bbox(g.subs[-1])
            if (
                g.measure == measure
                and abs(last.cy - box.cy) < 6.0
                and last.x_overlap(box) > 0.3
            ):
                g.subs.append(sub)
                placed = True
                break
        if not placed:
            glyphs.append(Glyph(subs=[sub], measure=measure))
            boxes.append(box)
    return glyphs


def nearest_string(
    cy: float,
    rows: Sequence[float] = DEFAULT_STRING_ROWS,
    tol: Optional[float] = None,
) -> Optional[int]:
    """Map a glyph centre-y to a string index (0 = highest), or None.

    Tolerance defaults to half the row spacing, so a glyph is assigned to a
    string as long as it is closer to that line than to its neighbour.
    """
    if tol is None:
        spacing = (rows[-1] - rows[0]) / (len(rows) - 1) if len(rows) > 1 else 12.0
        tol = spacing / 2.0
    best, bd = None, 1e9
    for idx, ry in enumerate(rows):
        d = abs(cy - ry)
        if d < bd:
            bd, best = d, idx
    return best if bd <= tol else None


def looks_like_digit(g: Glyph, rows: Sequence[float] = DEFAULT_STRING_ROWS) -> bool:
    b = g.bbox
    return 6.5 <= b.height <= 12.0 and b.width <= 9.0 and nearest_string(b.cy, rows) is not None


def looks_like_rest(g: Glyph) -> bool:
    """Rest glyphs are drawn in the note voice, taller than a digit and
    vertically centred on the stave (around the middle string).

    The lower width bound excludes the thin parenthesis glyphs Songsterr draws
    around let-ring / tied notes, which are otherwise rest-shaped."""
    b = g.bbox
    return b.height > 12.5 and 6.0 <= b.width <= 13.0 and 12.0 <= b.cy <= 40.0


def looks_like_bar_rest(g: Glyph) -> bool:
    """A half / whole rest: a short wide block sitting on or under a stave line
    (much shorter than the hooked eighth/16th rests)."""
    b = g.bbox
    return 9.0 < b.width < 16.0 and 3.0 < b.height < 9.0 and 12.0 <= b.cy <= 50.0


def bar_rest_value(g: Glyph, rows: Sequence[float]) -> Fraction:
    """Half rest sits *on top* of its line (block above it); whole rest *hangs*
    below the line (block beneath it)."""
    b = g.bbox
    line = min(rows, key=lambda r: abs(r - b.cy))
    return Fraction(1, 2) if b.cy <= line else Fraction(1)


def looks_like_paren(g: Glyph) -> bool:
    """A thin tall glyph on the stave: the parenthesis Songsterr draws around a
    let-ring / tied note."""
    b = g.bbox
    return b.height > 12.5 and b.width < 6.0 and 12.0 <= b.cy <= 40.0


def rest_value(g: Glyph) -> Optional[Fraction]:
    """Duration of a rest glyph from its shape. Songsterr stacks flag hooks like
    note flags, so among the tall glyphs the *wider* (two side-by-side hooks) is
    the shorter 16th rest, while the narrow tall zig-zag is the quarter rest. A
    single short hook is the eighth rest."""
    b = g.bbox
    if b.height < 19.0:          # one short hook -> eighth rest
        return Fraction(1, 8)
    if b.width < 10.0:           # narrow tall zig-zag -> quarter rest
        return Fraction(1, 4)
    return Fraction(1, 16)       # wide two-hook -> sixteenth rest


@dataclass
class DigitTemplate:
    label: str
    bitmap: List[int]


@dataclass
class DigitRecognizer:
    templates: List[DigitTemplate]
    size: int = GLYPH_SIZE
    # Max Hamming distance (out of size*size bits) accepted as a match.
    threshold: int = 40

    @classmethod
    def load(cls, path: str) -> "DigitRecognizer":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        tpls = [DigitTemplate(t["label"], t["bitmap"]) for t in data["templates"]]
        return cls(templates=tpls, size=data.get("size", GLYPH_SIZE),
                   threshold=data.get("threshold", 40))

    def classify(self, bitmap: Sequence[int]) -> Tuple[Optional[str], int]:
        best, bd = None, 10 ** 9
        for t in self.templates:
            d = hamming(bitmap, t.bitmap)
            if d < bd:
                bd, best = d, t.label
        if best is None or bd > self.threshold:
            return None, bd
        return best, bd


DEFAULT_TEMPLATES = os.path.join(
    os.path.dirname(__file__), "..", "templates", "digits.json"
)
