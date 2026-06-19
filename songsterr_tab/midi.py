"""Write recovered tablature to a Standard MIDI File.

No third-party dependency: a tab is a short sequence, so we emit the bytes
directly. Beat positions/durations are fractions of a whole note, which map
cleanly onto MIDI ticks (a whole note = 4 * PPQ). A single track is written as a
format-0 file; several tracks (e.g. both guitars + bass) as a format-1 file with
a conductor track plus one channel per part.
"""
from __future__ import annotations

from fractions import Fraction
from typing import List, Optional, Sequence, Tuple

from .notes import TabRecovery, _timesig_whole

PPQ = 480                       # ticks per quarter note
_WHOLE = PPQ * 4                # ticks per whole note
VELOCITY = 88
PROGRAM = 30                    # General MIDI "Distortion Guitar"


def _vlq(n: int) -> bytes:
    """MIDI variable-length quantity."""
    if n < 0:
        raise ValueError("negative delta")
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def _meta(kind: int, data: bytes) -> bytes:
    return b"\xFF" + bytes([kind]) + _vlq(len(data)) + data


def _program_for(track_name: Optional[str]) -> int:
    """Best-effort General MIDI program from the track's instrument name."""
    name = (track_name or "").lower()
    if "bass" in name:
        return 33                # Electric Bass (finger)
    if "clean" in name:
        return 27                # Electric Guitar (clean)
    if "acoustic" in name or "nylon" in name:
        return 24                # Acoustic Guitar (nylon)
    return PROGRAM               # Distortion Guitar


def _spans(rec: TabRecovery) -> Tuple[List[List[int]], Fraction]:
    """Sounded notes as [on_tick, off_tick, pitch], with let-ring ties merged."""
    bar = _timesig_whole(rec.meta.time_signature) or Fraction(1)
    raw: List[List] = []
    for m in rec.measures:
        # measure numbers are 1-based and absolute, so gaps stay as silence
        start = (m.number - 1) * bar
        for b in m.beats:
            if b.is_rest or b.position is None or b.duration is None:
                continue
            on = int((start + b.position) * _WHOLE)
            off = on + max(1, int(b.duration * _WHOLE))
            for n in b.notes:
                if n.midi is None or not (0 <= n.midi <= 127):
                    continue
                raw.append([on, off, n.midi, b.let_ring])

    # A let-ring / tied note continues the same pitch instead of re-striking:
    # extend the note it picks up from rather than emit a fresh attack.
    raw.sort(key=lambda s: (s[0], s[2]))
    merged: List[List[int]] = []
    open_at = {}
    for on, off, pitch, let_ring in raw:
        idx = open_at.get(pitch)
        if let_ring and idx is not None and abs(merged[idx][1] - on) <= 2:
            merged[idx][1] = off
        else:
            open_at[pitch] = len(merged)
            merged.append([on, off, pitch])
    return merged, bar


def _channel_events(spans: Sequence[Sequence[int]], channel: int) -> List[Tuple[int, int, bytes]]:
    """(tick, is_note_on, message) events on a channel for the given spans."""
    ev: List[Tuple[int, int, bytes]] = []
    for on, off, pitch in spans:
        ev.append((on, 1, bytes([0x90 | channel, pitch, VELOCITY])))
        ev.append((off, 0, bytes([0x80 | channel, pitch, 0])))
    return ev


def _track_chunk(lead: bytes, events: List[Tuple[int, int, bytes]]) -> bytes:
    """An MTrk chunk: leading meta/program bytes (at delta 0) then timed events,
    note-offs before note-ons at a shared tick."""
    events = sorted(events, key=lambda e: (e[0], e[1]))
    track = bytearray(lead)
    prev = 0
    for tick, _on, msg in events:
        track += _vlq(tick - prev) + msg
        prev = tick
    track += _vlq(0) + _meta(0x2F, b"")               # end of track
    return b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)


def _header( fmt: int, ntrks: int) -> bytes:
    return (b"MThd" + (6).to_bytes(4, "big") + fmt.to_bytes(2, "big")
            + ntrks.to_bytes(2, "big") + PPQ.to_bytes(2, "big"))


def _tempo_meta(rec: TabRecovery) -> bytes:
    bpm = rec.meta.tempo or 120
    out = _vlq(0) + _meta(0x51, int(60_000_000 / bpm).to_bytes(3, "big"))
    num, den = (rec.meta.time_signature or "4/4").split("/")
    dd = max(0, int(den)).bit_length() - 1            # 4 -> 2, 8 -> 3
    out += _vlq(0) + _meta(0x58, bytes([int(num), dd, 24, 8]))
    return out


def to_bytes(rec: TabRecovery) -> bytes:
    """Single-track, format-0 file."""
    spans, _ = _spans(rec)
    lead = _tempo_meta(rec) + _vlq(0) + bytes([0xC0, _program_for(rec.meta.track)])
    track = _track_chunk(lead, _channel_events(spans, 0))
    return _header(0, 1) + track


def multi_to_bytes(recs: Sequence[TabRecovery]) -> bytes:
    """Format-1 file: a conductor track for tempo/metre, then one channel per
    part (channel 9 is skipped -- it is reserved for GM percussion)."""
    if len(recs) == 1:
        return to_bytes(recs[0])
    tracks = [_track_chunk(_tempo_meta(recs[0]) +
                           _vlq(0) + _meta(0x03, b"Conductor"), [])]
    channels = [c for c in range(16) if c != 9]
    for i, rec in enumerate(recs):
        ch = channels[i % len(channels)]
        spans, _ = _spans(rec)
        name = (rec.meta.track or f"Track {i + 1}").encode("utf-8", "replace")
        lead = (_vlq(0) + _meta(0x03, name)
                + _vlq(0) + bytes([0xC0 | ch, _program_for(rec.meta.track)]))
        tracks.append(_track_chunk(lead, _channel_events(spans, ch)))
    return _header(1, len(tracks)) + b"".join(tracks)


def write_midi(rec: TabRecovery, path: str) -> int:
    """Write a single-track MIDI file; return the number of sounded notes."""
    with open(path, "wb") as fh:
        fh.write(to_bytes(rec))
    return len(_spans(rec)[0])


def write_multi(recs: Sequence[TabRecovery], path: str) -> int:
    """Write a multi-track MIDI file; return the total number of sounded notes."""
    with open(path, "wb") as fh:
        fh.write(multi_to_bytes(recs))
    return sum(len(_spans(r)[0]) for r in recs)


# kept for the test-suite's note-count assertion
def _events(rec: TabRecovery) -> Tuple[List[Tuple[int, bytes]], Fraction]:
    spans, bar = _spans(rec)
    ev = [(t, m) for t, _o, m in _channel_events(spans, 0)]
    return ev, bar
