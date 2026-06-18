from collections import Counter


def test_full_recovery_counts(recovery):
    total = sum(len(b.notes) for m in recovery.measures for b in m.beats)
    assert len(recovery.measures) == 75
    assert total == 908
    assert recovery.unrecognized == 0


def test_all_glyphs_match_exactly(recovery):
    # Every fret digit should match a template with zero Hamming distance,
    # because Songsterr renders them from a fixed font.
    worst = max(
        n.confidence for m in recovery.measures for b in m.beats for n in b.notes
    )
    assert worst == 0


def test_only_expected_digits(recovery):
    frets = Counter(
        n.fret for m in recovery.measures for b in m.beats for n in b.notes
    )
    # Drop-tuned power-chord song: only these fret values appear.
    assert set(frets) == {0, 3, 5, 6, 7, 8, 9}


def test_measure_two_content(recovery):
    m2 = next(m for m in recovery.measures if m.number == 2)
    # open power chord on the top three strings, then 3, 5, 3 on string 2
    first = m2.beats[0]
    assert [(n.string, n.fret) for n in first.notes] == [(0, 0), (1, 0), (2, 0)]
    singles = [b.notes[0].fret for b in m2.beats[1:]]
    assert singles == [3, 5, 3]


def test_drop_d_low_string_midi(recovery):
    # Low string is tuned to D (drop D) -> open MIDI must be D2 = 38.
    for m in recovery.measures:
        for b in m.beats:
            for n in b.notes:
                if n.string == 5 and n.fret == 0:
                    assert n.midi == 38
                    return
