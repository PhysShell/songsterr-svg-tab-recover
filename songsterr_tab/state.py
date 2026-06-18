"""Read Songsterr's pre-hydration page source (``<script id="state">``).

When you save a Songsterr page via *View Source* (rather than copying the
rendered DOM), you get the server-rendered HTML *before* the React app fetches
and draws the tab.  There is no tablature SVG yet -- but there is a Redux state
blob with rich metadata (song, revision, every track and its tuning).  This
module extracts that, and reports whether the note data is present (it usually
is not, in this kind of export).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .parse import SongMeta

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_to_name(midi: int, with_octave: bool = False) -> str:
    name = _NOTE_NAMES[midi % 12]
    return f"{name}{midi // 12 - 1}" if with_octave else name


@dataclass
class TrackInfo:
    part_id: int
    instrument: Optional[str]
    instrument_id: Optional[int]
    title: Optional[str]
    tuning_midi: List[int] = field(default_factory=list)
    is_drums: bool = False

    @property
    def tuning_names(self) -> List[str]:
        # state tuning is high-string-first; show top -> bottom
        return [midi_to_name(m) for m in self.tuning_midi]


@dataclass
class StateInfo:
    song_id: Optional[int]
    revision_id: Optional[int]
    prev_revision_id: Optional[int]
    title: Optional[str]
    artist: Optional[str]
    author: Optional[str]
    created_at: Optional[str]
    default_track: Optional[int]
    tracks: List[TrackInfo]
    has_note_data: bool

    def meta_for_track(self, part_id: int) -> SongMeta:
        track = next((t for t in self.tracks if t.part_id == part_id), None)
        return SongMeta(
            title=self.title,
            artist=self.artist,
            track=track.title if track else None,
            tempo=None,  # song tempo lives in the rendered score, not this blob
            time_signature=None,
            tuning=track.tuning_names if track else [],
        )


def extract_state(html_src: str) -> Optional[dict]:
    m = re.search(
        r'<script id="state" type="application/json">(.*?)</script>', html_src, re.S
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def parse_state(html_src: str) -> Optional[StateInfo]:
    state = extract_state(html_src)
    if not state:
        return None
    cur = (state.get("meta") or {}).get("current") or {}
    tracks = []
    for t in cur.get("tracks", []) or []:
        tracks.append(
            TrackInfo(
                part_id=t.get("partId"),
                instrument=t.get("instrument"),
                instrument_id=t.get("instrumentId"),
                title=t.get("title"),
                tuning_midi=list(t.get("tuning") or []),
                is_drums=bool(t.get("isDrums")),
            )
        )

    lines = (((state.get("part") or {}).get("lines") or {}).get("lines")) or []
    has_notes = bool(lines) or bool((state.get("part") or {}).get("current"))

    return StateInfo(
        song_id=cur.get("songId"),
        revision_id=cur.get("revisionId"),
        prev_revision_id=cur.get("prevRevisionId"),
        title=cur.get("title"),
        artist=cur.get("artist"),
        author=(cur.get("author") or {}).get("name"),
        created_at=cur.get("createdAt"),
        default_track=cur.get("defaultTrack"),
        tracks=tracks,
        has_note_data=has_notes,
    )


def has_rendered_tab(html_src: str) -> bool:
    """True if the HTML contains a rendered tablature SVG we can parse."""
    return "data-notes-measure" in html_src and "tab-strings-path" in html_src
