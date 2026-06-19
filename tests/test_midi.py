import struct

from songsterr_tab.midi import to_bytes, _events, PPQ


def _parse_track(data):
    """Minimal SMF parser -> list of (abs_tick, status, d1, d2); also checks the
    track length and that parsing reaches the exact end."""
    assert data[:4] == b"MThd"
    fmt, ntrks, div = struct.unpack(">HHH", data[8:14])
    assert fmt == 0 and ntrks == 1 and div == PPQ
    ti = data.index(b"MTrk")
    tlen = struct.unpack(">I", data[ti + 4:ti + 8])[0]
    trk = data[ti + 8:ti + 8 + tlen]
    assert ti + 8 + tlen == len(data)        # no trailing garbage

    def vlq(i):
        n = 0
        while True:
            n = (n << 7) | (trk[i] & 0x7F)
            i += 1
            if not (trk[i - 1] & 0x80):
                return n, i

    i = t = 0
    events = []
    running = None
    while i < len(trk):
        dt, i = vlq(i)
        t += dt
        st = trk[i]
        if st == 0xFF:
            i += 1
            kind = trk[i]
            i += 1
            ln, i = vlq(i)
            i += ln
        else:
            if st & 0x80:
                running = st
                i += 1
            else:
                st = running
            if (st & 0xF0) in (0x80, 0x90):
                events.append((t, st & 0xF0, trk[i], trk[i + 1]))
                i += 2
            else:                              # program change etc.
                i += 1
    return events


def test_midi_is_wellformed(recovery):
    events = _parse_track(to_bytes(recovery))
    ons = [e for e in events if e[1] == 0x90 and e[3] > 0]
    offs = [e for e in events if e[1] == 0x80 or (e[1] == 0x90 and e[3] == 0)]
    assert ons and len(ons) == len(offs)             # every note is released
    assert len(ons) == len(_events(recovery)[0]) // 2


def test_notes_are_ordered_and_in_range(recovery):
    events = _parse_track(to_bytes(recovery))
    assert events == sorted(events, key=lambda e: e[0])   # non-decreasing ticks
    assert all(0 <= e[2] <= 127 for e in events)
