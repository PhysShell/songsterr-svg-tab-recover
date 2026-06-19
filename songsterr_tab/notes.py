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
    looks_like_muted,
    looks_like_paren,
    looks_like_rest,
    looks_like_bar_rest,
    rest_value,
    bar_rest_value,
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
# 4-string bass in standard tuning, highest to lowest (G2 D2 A1 E1).
_BASS_OPEN_MIDI = [43, 38, 33, 28]


@dataclass
class Note:
    string: int          # 0 = highest string
    fret: Optional[int]   # None for a dead/muted ('x') note
    x: float
    midi: Optional[int] = None
    confidence: int = 0   # Hamming distance of the worst-matched digit
    small: bool = False   # rendered at reduced size => 32nd-note subdivision
    muted: bool = False   # dead note drawn as 'x' (no pitch)


@dataclass
class Beat:
    x: float
    notes: List[Note] = field(default_factory=list)
    duration: Optional[Fraction] = None   # as a fraction of a whole note
    position: Optional[Fraction] = None   # onset within the measure
    is_rest: bool = False
    let_ring: bool = False    # drawn parenthesised: a tied / let-ring note
    is_32nd: bool = False     # reduced-size note / slashed stem: a 32nd


@dataclass
class Measure:
    number: int
    line: int
    beats: List[Beat] = field(default_factory=list)
    # does the sum of beat durations equal the time signature?
    rhythm_ok: Optional[bool] = None
    duration_sum: Optional[Fraction] = None
    # a duration was inferred to satisfy the bar (forced beam-completion or a
    # sustained note extended to its proportional length) rather than read
    # straight from the rhythm voice
    rhythm_inferred: bool = False


@dataclass
class TabRecovery:
    meta: SongMeta
    measures: List[Measure]
    unrecognized: int = 0


def _open_string_midi(tuning: List[str], track: Optional[str] = None) -> List[Optional[int]]:
    """Best-effort MIDI for each open string given tuning letters.

    We keep the per-string octave of standard tuning and only shift the pitch
    class to the tuned note, choosing the nearest octave so e.g. a dropped low
    string stays below its neighbour.
    """
    # A bass sits an octave or two below a guitar. Prefer the instrument name,
    # which also catches 5-/6-string basses (their extra string would otherwise
    # push them past the "<= 4 strings" guess into guitar octaves); fall back to
    # the string count when the name is unknown.
    is_bass = "bass" in (track or "").lower() or len(tuning) <= 4
    refs = _BASS_OPEN_MIDI if is_bass else _STANDARD_OPEN_MIDI
    midis: List[Optional[int]] = []
    for i, name in enumerate(tuning[:6]):
        pc = _NOTE_TO_SEMITONE.get(name)
        if pc is None:
            midis.append(None)
            continue
        ref = refs[i] if i < len(refs) else refs[-1]
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
    open_midi = _open_string_midi(meta.tuning, meta.track)

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
        muted_by_measure: Dict[int, List[Glyph]] = {}
        rest_by_measure: Dict[int, List[Tuple[float, Optional[Fraction]]]] = {}
        paren_by_measure: Dict[int, List[float]] = {}
        for g in all_glyphs:
            if looks_like_digit(g, rows):
                digit_by_measure.setdefault(g.measure, []).append(g)
            elif looks_like_muted(g, rows):
                muted_by_measure.setdefault(g.measure, []).append(g)
            elif looks_like_rest(g):
                rest_by_measure.setdefault(g.measure, []).append(
                    (g.bbox.cx, rest_value(g)))
            elif looks_like_bar_rest(g):
                rest_by_measure.setdefault(g.measure, []).append(
                    (g.bbox.cx, bar_rest_value(g, rows)))
            elif looks_like_paren(g):
                paren_by_measure.setdefault(g.measure, []).append(g.bbox.cx)

        for mnum in set(digit_by_measure) | set(rest_by_measure) | set(muted_by_measure):
            mglyphs = digit_by_measure.get(mnum, [])
            measure = measures.setdefault(mnum, Measure(number=mnum, line=line.index))
            # form multi-digit frets
            notes: List[Note] = []
            # dead / muted 'x' notes: a string position, no pitch
            for g in muted_by_measure.get(mnum, []):
                s = nearest_string(g.bbox.cy, rows)
                if s is not None:
                    notes.append(Note(string=s, fret=None, x=g.bbox.cx,
                                      muted=True))
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
                # Songsterr draws 32nd-note frets at reduced size.
                small = all(g.bbox.height < 8.5 for g in grp)
                notes.append(Note(string=s, fret=fret, x=cx, midi=midi,
                                  confidence=dist, small=small))

            # group notes into beats by x proximity (chord = same x)
            notes.sort(key=lambda n: n.x)
            new_beats: List[Beat] = []
            for n in notes:
                if new_beats and abs(new_beats[-1].x - n.x) < 4.0:
                    new_beats[-1].notes.append(n)
                else:
                    new_beats.append(Beat(x=n.x, notes=[n]))
            # note durations from this line's rhythm voice; flag 32nds from the
            # reduced note size or the slash drawn across their stem
            for b in new_beats:
                b.duration = _beat_duration(b.x, rl)
                b.is_32nd = any(n.small for n in b.notes) or has_slash(b.x, rl)
            # rests carry their own duration from the rest glyph's shape; fall
            # back to the measure's shortest note value when a glyph is unclear
            grid = min((b.duration for b in new_beats if b.duration),
                       default=Fraction(1, 16))
            for rx, rdur in rest_by_measure.get(mnum, []):
                new_beats.append(Beat(x=rx, duration=rdur or grid, is_rest=True))
            # a note flanked by parenthesis glyphs is a let-ring / tied note
            for px in paren_by_measure.get(mnum, []):
                near = min((b for b in new_beats if not b.is_rest),
                           key=lambda b: abs(b.x - px), default=None)
                if near is not None and abs(near.x - px) < 14.0:
                    near.let_ring = True
            measure.beats.extend(new_beats)

    bar = _timesig_whole(meta.time_signature)
    line_bars = {ln.index: (measure_boundaries(ln.strings_path) if ln.strings_path else [])
                 for ln in lines}

    # A measure printed on a *fully rendered* stave but holding no glyphs is a
    # silent bar (a whole rest), so emit it rather than leave a hole. Lines with
    # no strings path never drew their content (e.g. a partial capture), so we
    # don't presume their measures are silent.
    if bar is not None:
        for line in lines:
            if not line.strings_path:
                continue
            for _x, num in line.measure_numbers:
                if num not in measures:
                    measures[num] = Measure(number=num, line=line.index,
                                            beats=[Beat(x=0.0, duration=bar, is_rest=True)])

    ordered = [measures[k] for k in sorted(measures)]
    for m in ordered:
        m.beats.sort(key=lambda b: b.x)
        if bar is not None:
            _resolve_stemless(m, bar)
            _complete_thirty_seconds(m, bar)
            _complete_beams(m, bar)
            _extend_sustained(m, bar, line_bars.get(m.line, []))
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


_CLEAN_DURATIONS = (
    Fraction(1, 16), Fraction(1, 8), Fraction(3, 16), Fraction(1, 4),
    Fraction(3, 8), Fraction(1, 2), Fraction(3, 4), Fraction(1),
)


def _extend_sustained(m: "Measure", bar: Fraction, bars: List[float]) -> None:
    """Recover a sustained note read short (e.g. a half note that has no beam,
    whose value the rhythm voice never spelled out).

    A note's x-position is proportional to its onset within the measure, so the
    span to the next onset estimates its real duration. When a measure underruns
    and exactly one beat's span -- given the whole shortfall -- lands on a clean
    note value, extend it. The geometry independently confirms the held length,
    which keeps this honest rather than a blind fit."""
    beats = m.beats
    if not beats or not bars:
        return
    total = sum((b.duration for b in beats if b.duration), Fraction(0))
    deficit = bar - total
    if deficit < Fraction(1, 8):            # ignore sub-eighth noise
        return
    x0 = max((b for b in bars if b < beats[0].x - 2), default=None)
    x1 = min((b for b in bars if b > beats[-1].x + 2), default=None)
    if x0 is None or x1 is None or x1 - x0 < 50:
        return
    # A let-ring / tied note is held across the bar; its drawn x-span is
    # compressed and doesn't reflect the real length, so let it absorb the
    # shortfall directly when there is exactly one.
    rings = [i for i, b in enumerate(beats)
             if b.let_ring and b.duration is not None
             and b.duration + deficit in _CLEAN_DURATIONS]
    if len(rings) == 1:
        beats[rings[0]].duration += deficit
        m.rhythm_inferred = True
        return

    width = x1 - x0
    hits = []
    for i, b in enumerate(beats):
        if b.duration is None:
            continue
        next_x = beats[i + 1].x if i + 1 < len(beats) else x1
        span = (next_x - b.x) / width            # proportional duration
        extended = b.duration + deficit
        if extended in _CLEAN_DURATIONS and abs(float(extended) - span) < 0.06:
            hits.append(i)
    if len(hits) == 1:
        beats[hits[0]].duration += deficit
        m.rhythm_inferred = True


def _resolve_stemless(m: "Measure", bar: Fraction) -> None:
    """A note with no rhythm stem nearby is a whole/half note (open noteheads
    carry no stem). Give such beats the measure's remaining duration when that
    lands on a clean value -- a lone held note becomes a whole note, a held note
    beside a rest a half note, etc."""
    nones = [b for b in m.beats if b.duration is None and b.notes]
    if not nones:
        return
    known = sum((b.duration for b in m.beats if b.duration is not None), Fraction(0))
    remaining = bar - known
    if remaining <= 0:
        return
    share = remaining / len(nones)
    if share in _CLEAN_DURATIONS:
        for b in nones:
            b.duration = share


def _complete_thirty_seconds(m: "Measure", bar: Fraction) -> None:
    """Apply the 32nd reading when it makes the bar balance exactly.

    A 32nd note (reduced size / slashed stem) pairs with a dotted-16th to fill
    an eighth (1/32 + 3/32 = 1/8) -- the fine analogue of the dotted-8th + 16th
    gallop. The rhythm voice abbreviates this to a slash and under-renders the
    secondary beams, so the pair reads too long. Set each 32nd to 1/32 and the
    longer note right after it to a dotted-16th, but only if the whole measure
    then sums to the bar -- otherwise the finer subdivision is under-determined
    (no augmentation dots survive in the render) and we leave it to the
    sum-closing fallbacks, keeping just the `is_32nd` flag."""
    beats = m.beats
    if not any(b.is_32nd for b in beats):
        return
    trial = [b.duration for b in beats]
    for i, b in enumerate(beats):
        if not b.is_32nd:
            continue
        trial[i] = Fraction(1, 32)
        j = i + 1
        if j < len(beats) and not beats[j].is_rest \
                and trial[j] is not None and trial[j] > Fraction(3, 32):
            trial[j] = Fraction(3, 32)
    if sum((d for d in trial if d), Fraction(0)) != bar:
        return
    for b, d in zip(beats, trial):
        b.duration = d
    m.rhythm_inferred = True


def _complete_beams(m: "Measure", bar: Fraction) -> None:
    """Resolve the 8th/16th ambiguity of beamed notes from their context.

    A note's second (16th) beam is sometimes a stub Songsterr doesn't draw as
    its own segment, so the note reads as an 8th. Such a note is flanked by
    16ths or by a dotted-8th (a dotted-8th in a beam group is always completed
    by a 16th: 3/16 + 1/16 = one beat). When a measure overruns by whole 16ths
    and *every* candidate must be demoted to absorb the surplus exactly, the
    correction is forced -- there is no choice of which note to change -- so we
    apply it. Ambiguous cases (more candidates than the surplus needs) are left
    alone and the measure stays flagged."""
    beats = m.beats
    durs = [b.duration for b in beats]
    surplus = sum((d for d in durs if d), Fraction(0)) - bar
    if surplus <= 0 or surplus % Fraction(1, 16) != 0:
        return
    need = int(surplus / Fraction(1, 16))
    cands = []
    for i, b in enumerate(beats):
        if b.is_rest or durs[i] != Fraction(1, 8):
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(beats) and durs[j] in (Fraction(1, 16), Fraction(3, 16)) \
                    and abs(beats[i].x - beats[j].x) < 70:
                cands.append(i)
                break
    if need == 0 or need != len(cands):
        return
    for i in cands:
        beats[i].duration = Fraction(1, 16)
    m.rhythm_inferred = True


def _timesig_whole(ts: Optional[str]) -> Optional[Fraction]:
    """A measure's length as a fraction of a whole note, e.g. '4/4' -> 1."""
    if not ts or "/" not in ts:
        return None
    try:
        num, den = ts.split("/")
        return Fraction(int(num), int(den))
    except (ValueError, ZeroDivisionError):
        return None


def has_slash(x: float, rl) -> bool:
    from .rhythm import has_slash as _hs
    return _hs(x, rl)


def _beat_duration(x: float, rl) -> Optional[Fraction]:
    from .rhythm import stem_duration
    if not rl.stems:
        return None
    stem = min(rl.stems, key=lambda s: abs(s.x - x))
    if abs(stem.x - x) <= 9.0:
        return stem_duration(stem, rl)
    return None
