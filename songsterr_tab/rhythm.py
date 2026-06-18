"""Recover note durations from the Songsterr rhythm voice.

Below the tab stave Songsterr draws a rhythm voice (`vENqEG_voice`): a vertical
stem per beat, horizontal beams grouping subdivisions, augmentation dots, and
rest glyphs.  Duration follows standard engraving:

    beams over a stem   0 -> quarter   1 -> eighth   2 -> 16th   3 -> 32nd

A trailing augmentation dot multiplies by 3/2.  Rests (glyphs with no stem)
occupy time too.  This is a first pass: beamed notes (the vast majority) are
recovered reliably; plain quarters are the beamless default; half/whole notes
and full rest-duration typing are approximate, so each measure carries a flag
for whether its durations add up to the time signature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional, Tuple

from svgpathtools import parse_path

import re

# beam count -> note value (as a fraction of a whole note)
_BEAM_DUR = {0: Fraction(1, 4), 1: Fraction(1, 8), 2: Fraction(1, 16), 3: Fraction(1, 32)}


@dataclass
class Stem:
    x: float
    top: float
    bottom: float


@dataclass
class Beam:
    x0: float
    x1: float
    y: float


@dataclass
class RhythmLine:
    stems: List[Stem] = field(default_factory=list)
    beams: List[Beam] = field(default_factory=list)
    dots: List[float] = field(default_factory=list)       # x of augmentation dots
    rests: List[Tuple[float, float]] = field(default_factory=list)  # (x, height)


def parse_rhythm(rhythm_paths: List[str]) -> RhythmLine:
    rl = RhythmLine()
    for d in rhythm_paths:
        for sub in parse_path(d).continuous_subpaths():
            xn, xx, yn, yx = sub.bbox()
            w, h = xx - xn, yx - yn
            if w < 0.6 and h > 4:                 # vertical stem
                rl.stems.append(Stem((xn + xx) / 2, yn, yx))
            elif h < 3 and w > 3:                 # horizontal beam
                rl.beams.append(Beam(xn, xx, (yn + yx) / 2))
            elif abs(w - 2) < 1 and abs(h - 2) < 1:   # augmentation dot
                rl.dots.append((xn + xx) / 2)
            else:                                  # rest / flag glyph
                rl.rests.append(((xn + xx) / 2, round(h, 1)))
    return rl


def beams_over(x: float, beams: List[Beam]) -> int:
    """Number of distinct beam *levels* (y-rows) crossing this stem.

    Counting levels rather than segments avoids double-counting when a beam at
    one level is drawn as several pieces, and respects partial (secondary)
    beams that only span part of a group."""
    levels = {round(b.y) for b in beams if b.x0 - 1 <= x <= b.x1 + 1}
    return len(levels)


def stem_duration(stem: Stem, rl: RhythmLine) -> Fraction:
    bc = min(beams_over(stem.x, rl.beams), 3)
    dur = _BEAM_DUR[bc]
    # augmentation dot just to the right of the stem
    if any(stem.x < dx < stem.x + 8 for dx in rl.dots):
        dur = dur * Fraction(3, 2)
    return dur


def durations_for_beats(
    beat_xs: List[float], rl: RhythmLine, tol: float = 9.0
) -> List[Optional[Fraction]]:
    """Assign a duration to each beat x by matching it to the nearest stem."""
    out: List[Optional[Fraction]] = []
    for bx in beat_xs:
        stem = min(rl.stems, key=lambda s: abs(s.x - bx), default=None)
        if stem is not None and abs(stem.x - bx) <= tol:
            out.append(stem_duration(stem, rl))
        else:
            out.append(None)
    return out
