from collections import Counter


def test_full_recovery_counts(recovery):
    total = sum(len(b.notes) for m in recovery.measures for b in m.beats)
    assert len(recovery.measures) == 76      # 75 with content + 1 silent bar
    assert total == 1123
    assert recovery.unrecognized == 0


def test_all_glyphs_match_exactly(recovery):
    # Every fret digit should match a template with zero Hamming distance,
    # because Songsterr renders them from a fixed font.
    worst = max(
        n.confidence for m in recovery.measures for b in m.beats for n in b.notes
    )
    assert worst == 0


def test_multi_digit_frets_recovered(recovery):
    frets = Counter(
        n.fret for m in recovery.measures for b in m.beats for n in b.notes
    )
    # The lead part runs into the teens/twenties -- tens digits must not be
    # dropped (the bug that made "10" read as "0").
    assert 1 in {int(d) for f in frets for d in str(f)}  # digit 1 appears
    assert max(frets) >= 15
    assert frets[10] > 0 and frets[12] > 0 and frets[15] > 0


def test_measure_two_content(recovery):
    m2 = next(m for m in recovery.measures if m.number == 2)
    note_beats = [b for b in m2.beats if b.notes]
    # open chord of fret 10 on the top three strings, then a single-note run
    first = note_beats[0]
    assert [(n.string, n.fret) for n in first.notes] == [(0, 10), (1, 10), (2, 10)]
    singles = [b.notes[0].fret for b in note_beats[1:]]
    assert singles == [12, 14, 13, 15, 12, 13, 14]


def test_drop_d_low_string_midi(recovery):
    # Low string is tuned to D (drop D) -> open MIDI must be D2 = 38.
    for m in recovery.measures:
        for b in m.beats:
            for n in b.notes:
                if n.string == 5 and n.fret == 0:
                    assert n.midi == 38
                    return
    raise AssertionError("expected at least one open low-D note")


def test_five_string_bass_stays_in_bass_octave():
    # A 5-string bass has five tuning letters, so a string-count guess alone
    # would mistake it for a guitar and resolve an octave or two too high. The
    # instrument name keeps every string -- including the low B -- in the bass
    # register (B-E-A-D-G, here highest string first).
    from songsterr_tab.notes import _open_string_midi
    midi = _open_string_midi(["G", "D", "A", "E", "B"], "Electric Bass (finger)")
    assert midi == [43, 38, 33, 28, 23]      # G2 D2 A1 E1 B0
