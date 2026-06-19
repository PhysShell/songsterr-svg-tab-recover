"""Recover note events (string + fret) from a Songsterr tab page."""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from .geometry import continuous_subpaths
from .glyphs import (
    DEFAULT_STRING_ROWS,
    DigitRecognizer,
    Glyph,
    group_glyphs,
    looks_like_digit,
    looks_like_rest,
    rest_value,
    nearest_string,
)
from .parse import SongMeta, TabLine, measure_boundaries, parse_lines, parse_meta, string_rows

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
    duration: Optional[Fraction] = None   # as a fraction of a whole note
    position: Optional[Fraction] = None   # onset within the measure
    is_rest: bool = False


@dataclass
class Measure:
    number: int
    line: int
    beats: List[Beat] = field(default_factory=list)
    # does the sum of beat durations equal the time signature?
    rhythm_ok: Optional[bool] = None
    duration_sum: Optional[Fraction] = None


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
            # Digits of one fret number sit ~3px apart; separate beats on a
            # string are tens of px apart, so a small positive gap is safe.
            if abs(last.cy - g.bbox.cy) < 5 and -1.0 <= g.bbox.xmin - last.xmax <= 6.0:
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

    from .rhythm import parse_rhythm

    for line in lines:
        rows = string_rows(line.strings_path) if line.strings_path else list(DEFAULT_STRING_ROWS)
        rl = parse_rhythm(line.rhythm_paths)
        # Glyphs from the note voice: fret digits and rest symbols (rests are
        # drawn here too, taller than digits and centred on the stave).
        pairs = []
        for d, measure in line.note_paths:
            for sub in continuous_subpaths(d):
                pairs.append((sub, measure))
        all_glyphs = group_glyphs(pairs)
        digit_by_measure: Dict[int, List[Glyph]] = {}
        rest_by_measure: Dict[int, List[Tuple[float, Optional[Fraction]]]] = {}
        for g in all_glyphs:
            if looks_like_digit(g, rows):
                digit_by_measure.setdefault(g.measure, []).append(g)
            elif looks_like_rest(g):
                rest_by_measure.setdefault(g.measure, []).append(
                    (g.bbox.cx, rest_value(g)))

        for mnum in set(digit_by_measure) | set(rest_by_measure):
            mglyphs = digit_by_measure.get(mnum, [])
            measure = measures.setdefault(mnum, Measure(number=mnum, line=line.index))
            # form multi-digit frets
            notes: List[Note] = []
            for grp in _cluster_digit_glyphs(mglyphs):
                fret, dist, cx, cy = _fret_from_digits(grp, recog)
                if fret is None:
                    unrecognized += 1
                    continue
                s = nearest_string(cy, rows)
                if s is None:
                    unrecognized += 1
                    continue
                midi = None
                if s < len(open_midi) and open_midi[s] is not None:
                    midi = open_midi[s] + fret
                notes.append(Note(string=s, fret=fret, x=cx, midi=midi, confidence=dist))

            # group notes into beats by x proximity (chord = same x)
            notes.sort(key=lambda n: n.x)
            new_beats: List[Beat] = []
            for n in notes:
                if new_beats and abs(new_beats[-1].x - n.x) < 4.0:
                    new_beats[-1].notes.append(n)
                else:
                    new_beats.append(Beat(x=n.x, notes=[n]))
            # note durations from this line's rhythm voice
            for b in new_beats:
                b.duration = _beat_duration(b.x, rl)
            # rests carry their own duration from the rest glyph's shape; fall
            # back to the measure's shortest note value when a glyph is unclear
            grid = min((b.duration for b in new_beats if b.duration),
                       default=Fraction(1, 16))
            for rx, rdur in rest_by_measure.get(mnum, []):
                new_beats.append(Beat(x=rx, duration=rdur or grid, is_rest=True))
            measure.beats.extend(new_beats)

    bar = _timesig_whole(meta.time_signature)
    ordered = [measures[k] for k in sorted(measures)]
    for m in ordered:
        m.beats.sort(key=lambda b: b.x)
        pos = Fraction(0)
        total = Fraction(0)
        for b in m.beats:
            b.notes.sort(key=lambda n: n.string)
            b.position = pos
            if b.duration is not None:
                pos += b.duration
                total += b.duration
        m.duration_sum = total
        if bar is not None and any(b.duration for b in m.beats):
            m.rhythm_ok = (total == bar)
    return TabRecovery(meta=meta, measures=ordered, unrecognized=unrecognized)


def _timesig_whole(ts: Optional[str]) -> Optional[Fraction]:
    """A measure's length as a fraction of a whole note, e.g. '4/4' -> 1."""
    if not ts or "/" not in ts:
        return None
    try:
        num, den = ts.split("/")
        return Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return None


def _beat_duration(x: float, rl) -> Optional[Fraction]:
    from .rhythm import stem_duration
    if not rl.stems:
        return None
    stem = min(rl.stems, key=lambda s: abs(s.x - x))
    if abs(stem.x - x) <= 9.0:
        return stem_duration(stem, rl)
    return None
