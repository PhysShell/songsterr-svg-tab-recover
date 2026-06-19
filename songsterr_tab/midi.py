"""Write recovered tablature to a Standard MIDI File (format 0).

No third-party dependency: a tab is a short, single-track sequence, so we emit
the handful of bytes directly. Beat positions/durations are fractions of a whole
note, which map cleanly onto MIDI ticks (a whole note = 4 * PPQ).
"""
from __future__ import annotations

from fractions import Fraction
from typing import List, Optional, Tuple

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


def _events(rec: TabRecovery) -> Tuple[List[Tuple[int, bytes]], Fraction]:
    """Absolute-time (tick, message) note events, plus the bar length in wholes."""
    bar = _timesig_whole(rec.meta.time_signature) or Fraction(1)
    events: List[Tuple[int, bytes]] = []
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
                events.append((on, bytes([0x90, n.midi, VELOCITY])))
                events.append((off, bytes([0x80, n.midi, 0])))
    return events, bar


def to_bytes(rec: TabRecovery) -> bytes:
    events, bar = _events(rec)
    # stable order: time, then note-offs before note-ons at the same tick
    events.sort(key=lambda e: (e[0], e[1][0] & 0xF0 == 0x90))

    track = bytearray()
    bpm = rec.meta.tempo or 120
    track += _vlq(0) + _meta(0x51, int(60_000_000 / bpm).to_bytes(3, "big"))
    num, den = (rec.meta.time_signature or "4/4").split("/")
    dd = max(0, int(den)).bit_length() - 1            # 4 -> 2, 8 -> 3
    track += _vlq(0) + _meta(0x58, bytes([int(num), dd, 24, 8]))
    track += _vlq(0) + bytes([0xC0, PROGRAM])         # program change

    prev = 0
    for tick, msg in events:
        track += _vlq(tick - prev) + msg
        prev = tick
    track += _vlq(0) + _meta(0x2F, b"")               # end of track

    header = b"MThd" + (6).to_bytes(4, "big") + \
        (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + PPQ.to_bytes(2, "big")
    return header + b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)


def write_midi(rec: TabRecovery, path: str) -> int:
    """Write a MIDI file; return the number of sounded notes."""
    data = to_bytes(rec)
    with open(path, "wb") as fh:
        fh.write(data)
    events, _ = _events(rec)
    return len(events) // 2       # one note-on + one note-off per note
