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
# String rows (centre y) for the 6 lines of a standard tab stave.
STRING_ROWS = (5.0, 17.0, 29.0, 41.0, 53.0, 65.0)


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


def nearest_string(cy: float) -> Optional[int]:
    """Map a glyph centre-y to a string index (0 = highest), or None."""
    best, bd = None, 1e9
    for idx, ry in enumerate(STRING_ROWS):
        d = abs(cy - ry)
        if d < bd:
            bd, best = d, idx
    return best if bd < 5.0 else None


def looks_like_digit(g: Glyph) -> bool:
    b = g.bbox
    return 6.5 <= b.height <= 12.0 and b.width <= 9.0 and nearest_string(b.cy) is not None


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
