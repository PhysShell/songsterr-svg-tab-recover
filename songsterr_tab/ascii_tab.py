"""Render recovered notes as a human-readable ASCII tab.

This is a positional rendering (one column per recovered beat) -- it shows the
frets on the right strings in the right order, but spacing is not proportional
to duration (rhythm recovery is a separate, later step).
"""
from __future__ import annotations

from typing import List

from .notes import TabRecovery


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
            # one column per beat; column width fits the widest fret in it
            for beat in m.beats:
                frets = {note.string: note.fret for note in beat.notes}
                colw = max((len(str(f)) for f in frets.values()), default=1)
                for s in range(n_strings):
                    cell = str(frets[s]) if s in frets else "-"
                    rows[s] += "-" + cell.rjust(colw, "-")
            for s in range(n_strings):
                rows[s] += "-|"
        # measure-number ruler
        ruler = " " * (width + 1)
        out.append(ruler + "  ".join(f"m{m.number}" for m in chunk))
        out.extend(rows)
        out.append("")
    return "\n".join(out)
