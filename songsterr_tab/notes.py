"""Recover note events (string + fret) from a Songsterr tab page."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .geometry import continuous_subpaths
from .glyphs import DigitRecognizer, Glyph, group_glyphs, looks_like_digit, nearest_string
from .parse import SongMeta, TabLine, measure_boundaries, parse_lines, parse_meta

# MIDI pitch of each open-string note name in octave-less form is ambiguous, so
# we resolve open-string pitches from the tuning letters using a standard
# octave layout for a 6-string guitar (string 1 = highest).
_NOTE_TO_SEMITONE = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
# Default MIDI octaves per string for E-standard (E4 B3 G3 D3 A2 E2).
_STANDARD_OPEN_MIDI = [64, 59, 55, 50, 45, 40]


@dataclass
class Note:
    string: int          # 0 = highest string
    fret: int
    x: float
    midi: Optional[int] = None
    confidence: int = 0   # Hamming distance of the worst-matched digit


@dataclass
class Beat:
    x: float
    notes: List[Note] = field(default_factory=list)


@dataclass
class Measure:
    number: int
    line: int
    beats: List[Beat] = field(default_factory=list)


@dataclass
class TabRecovery:
    meta: SongMeta
    measures: List[Measure]
    unrecognized: int = 0


def _open_string_midi(tuning: List[str]) -> List[Optional[int]]:
    """Best-effort MIDI for each open string given tuning letters.

    We keep the per-string octave of standard tuning and only shift the pitch
    class to the tuned note, choosing the nearest octave so e.g. a dropped low
    string stays below its neighbour.
    """
    midis: List[Optional[int]] = []
    for i, name in enumerate(tuning[:6]):
        pc = _NOTE_TO_SEMITONE.get(name)
        if pc is None:
            midis.append(None)
            continue
        ref = _STANDARD_OPEN_MIDI[i] if i < len(_STANDARD_OPEN_MIDI) else 40
        # nearest midi with this pitch class to the standard reference
        base = ref - (ref % 12)
        candidates = [base + pc - 12, base + pc, base + pc + 12]
        midis.append(min(candidates, key=lambda m: abs(m - ref)))
    return midis


def _fret_from_digits(glyphs: List[Glyph], recog: DigitRecognizer) -> Tuple[Optional[int], int, float, float]:
    """Combine left-to-right digit glyphs into a single fret integer.

    Returns (fret, worst_distance, x_center, y_center) or (None, ...) on failure.
    """
    glyphs = sorted(glyphs, key=lambda g: g.bbox.xmin)
    digits = []
    worst = 0
    for g in glyphs:
        label, dist = recog.classify(g.bitmap())
        if label is None:
            return None, dist, glyphs[0].bbox.cx, glyphs[0].bbox.cy
        digits.append(label)
        worst = max(worst, dist)
    fret = int("".join(digits))
    xs = [g.bbox.cx for g in glyphs]
    ys = [g.bbox.cy for g in glyphs]
    return fret, worst, sum(xs) / len(xs), sum(ys) / len(ys)


def _cluster_digit_glyphs(glyphs: List[Glyph]) -> List[List[Glyph]]:
    """Group digit glyphs that form one multi-digit fret on the same string.

    Same string row + small x gap => same number (e.g. '1' and '0' of '10').
    """
    glyphs = sorted(glyphs, key=lambda g: (round(g.bbox.cy), g.bbox.xmin))
    groups: List[List[Glyph]] = []
    for g in glyphs:
        placed = False
        for grp in groups:
            last = grp[-1].bbox
            if abs(last.cy - g.bbox.cy) < 5 and 0 <= g.bbox.xmin - last.xmax <= 2.5:
                grp.append(g)
                placed = True
                break
        if not placed:
            groups.append([g])
    return groups


def recover(html_src: str, recog: DigitRecognizer) -> TabRecovery:
    meta = parse_meta(html_src)
    lines = parse_lines(html_src)
    open_midi = _open_string_midi(meta.tuning)

    measures: Dict[int, Measure] = {}
    unrecognized = 0

    for line in lines:
        # All digit glyphs on this line, tagged with their measure number.
        pairs = []
        for d, measure in line.note_paths:
            for sub in continuous_subpaths(d):
                pairs.append((sub, measure))
        glyphs = [g for g in group_glyphs(pairs) if looks_like_digit(g)]

        # Bucket glyphs by measure, then by string row.
        by_measure: Dict[int, List[Glyph]] = {}
        for g in glyphs:
            by_measure.setdefault(g.measure, []).append(g)

        for mnum, mglyphs in by_measure.items():
            measure = measures.setdefault(mnum, Measure(number=mnum, line=line.index))
            # form multi-digit frets
            notes: List[Note] = []
            for grp in _cluster_digit_glyphs(mglyphs):
                fret, dist, cx, cy = _fret_from_digits(grp, recog)
                if fret is None:
                    unrecognized += 1
                    continue
                s = nearest_string(cy)
                if s is None:
                    unrecognized += 1
                    continue
                midi = None
                if s < len(open_midi) and open_midi[s] is not None:
                    midi = open_midi[s] + fret
                notes.append(Note(string=s, fret=fret, x=cx, midi=midi, confidence=dist))

            # group notes into beats by x proximity (chord = same x)
            notes.sort(key=lambda n: n.x)
            for n in notes:
                if measure.beats and abs(measure.beats[-1].x - n.x) < 4.0:
                    measure.beats[-1].notes.append(n)
                else:
                    measure.beats.append(Beat(x=n.x, notes=[n]))

    ordered = [measures[k] for k in sorted(measures)]
    for m in ordered:
        m.beats.sort(key=lambda b: b.x)
        for b in m.beats:
            b.notes.sort(key=lambda n: n.string)
    return TabRecovery(meta=meta, measures=ordered, unrecognized=unrecognized)
