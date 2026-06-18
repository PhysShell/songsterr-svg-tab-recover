"""Render recovered notes as a human-readable ASCII tab.

Column width is proportional to each beat's recovered duration (a 16th note is
one unit wide), so the tab reads rhythmically.  Beats whose duration could not
be recovered fall back to one unit; rests render as dashes.
"""
from __future__ import annotations

from fractions import Fraction
from typing import List

from .notes import TabRecovery

_SIXTEENTH = Fraction(1, 16)


def _units(duration) -> int:
    if duration is None:
        return 1
    return max(1, round(duration / _SIXTEENTH))


def render_ascii(rec: TabRecovery, measures_per_row: int = 4) -> str:
    n_strings = len(rec.meta.tuning) or 6
    labels = rec.meta.tuning or ["E", "B", "G", "D", "A", "E"]
    width = max(len(s) for s in labels)
    labels = [s.rjust(width) for s in labels]

    out: List[str] = []
    header = f"{rec.meta.artist or ''} - {rec.meta.title or ''}".strip(" -")
    if header:
        out.append(header)
    sub = []
    if rec.meta.track:
        sub.append(rec.meta.track)
    if rec.meta.tempo:
        sub.append(f"{rec.meta.tempo} bpm")
    if rec.meta.time_signature:
        sub.append(rec.meta.time_signature)
    if rec.meta.tuning:
        sub.append("tuning " + " ".join(rec.meta.tuning))
    if sub:
        out.append(" | ".join(sub))
    out.append("")

    measures = rec.measures
    for start in range(0, len(measures), measures_per_row):
        chunk = measures[start:start + measures_per_row]
        rows = [f"{labels[s]}|" for s in range(n_strings)]
        for m in chunk:
            for beat in sorted(m.beats, key=lambda b: (b.position or 0, b.x)):
                frets = {note.string: note.fret for note in beat.notes}
                label_w = max((len(str(f)) for f in frets.values()), default=1)
                # cell is at least as wide as the fret label, and as wide as the
                # beat's duration so rhythm shows in the spacing
                cell_w = max(label_w, _units(beat.duration))
                for s in range(n_strings):
                    cell = str(frets[s]) if s in frets else "-"
                    rows[s] += "-" + cell.ljust(cell_w, "-")
            for s in range(n_strings):
                rows[s] += "-|"
        ruler = " " * (width + 1)
        out.append(ruler + "  ".join(f"m{m.number}" for m in chunk))
        out.extend(rows)
        out.append("")
    return "\n".join(out)
