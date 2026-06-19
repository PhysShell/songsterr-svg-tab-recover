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


def test_let_ring_ties_do_not_restrike():
    """A let-ring note continues the previous identical pitch instead of being
    struck again (Will Swan m81 whole chord let-ringing through m82)."""
    import os
    from songsterr_tab.notes import recover
    from songsterr_tab.glyphs import DigitRecognizer
    root = os.path.dirname(os.path.dirname(__file__))
    fx = os.path.join(root, "fixtures", "will-swan.rendered.html")
    if not os.path.exists(fx):
        import pytest; pytest.skip("will-swan fixture not present")
    rec = recover(open(fx, encoding="utf-8").read(),
                  DigitRecognizer.load(os.path.join(root, "templates", "digits.json")))
    events = _parse_track(to_bytes(rec))
    W = 1920
    # measure 81 starts at (81-1) whole notes; measure 82 one whole note later
    on82 = [e for e in events if e[0] == 81 * W and e[1] == 0x90 and e[3] > 0]
    assert not on82                                    # no fresh attack at m82
    # the chord struck at m81 holds for two whole notes (D2=38, A2=45)
    for pitch in (38, 45):
        on = [e for e in events if e[0] == 80 * W and e[2] == pitch and e[1] == 0x90 and e[3] > 0]
        off = [e for e in events if e[0] == 82 * W and e[2] == pitch and (e[1] == 0x80 or e[3] == 0)]
        assert on and off


def test_multi_track_combines_parts(recovery):
    """Several recoveries combine into a format-1 file: a conductor track plus
    one channel per part."""
    from songsterr_tab.midi import multi_to_bytes
    data = multi_to_bytes([recovery, recovery])
    import struct
    fmt, ntrks, _ = struct.unpack(">HHH", data[8:14])
    assert fmt == 1 and ntrks == 3          # conductor + 2 parts
    # each part lands on its own channel
    chans = set()
    pos = data.index(b"MTrk")
    for _ in range(ntrks):
        ln = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + ln]
        for k in range(len(body) - 1):
            if body[k] & 0xF0 in (0x90, 0x80) and body[k] & 0x80:
                chans.add(body[k] & 0x0F)
        pos += 8 + ln
    assert {0, 1} <= chans


def test_multi_track_rejects_overflow_and_empty(recovery):
    """One channel per part is the contract: more parts than melodic channels
    must fail loudly rather than wrap onto a shared channel, and an empty input
    raises instead of an opaque IndexError."""
    import pytest
    from songsterr_tab.midi import multi_to_bytes
    with pytest.raises(ValueError):
        multi_to_bytes([recovery] * 16)      # 16 > 15 melodic channels
    with pytest.raises(ValueError):
        multi_to_bytes([])
