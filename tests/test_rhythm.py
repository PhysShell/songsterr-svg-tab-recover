from fractions import Fraction


def test_beats_have_durations(recovery):
    # the rhythm voice should give most beats a duration
    beats = [b for m in recovery.measures for b in m.beats]
    with_dur = [b for b in beats if b.duration is not None]
    assert len(with_dur) / len(beats) > 0.9


def test_durations_are_clean_note_values(recovery):
    allowed = {Fraction(1, 32), Fraction(1, 16), Fraction(1, 8), Fraction(1, 4),
               Fraction(1, 2), Fraction(1, 1),
               Fraction(3, 32), Fraction(3, 16), Fraction(3, 8), Fraction(3, 4)}
    for m in recovery.measures:
        for b in m.beats:
            if b.duration is not None:
                assert b.duration in allowed, (m.number, b.duration)


def test_some_measures_validate(recovery):
    checked = [m for m in recovery.measures if m.rhythm_ok is not None]
    ok = [m for m in checked if m.rhythm_ok]
    # first-pass rhythm: a meaningful fraction of measures sum to the bar
    assert len(ok) / len(checked) > 0.6


def test_positions_are_cumulative(recovery):
    for m in recovery.measures:
        pos = Fraction(0)
        for b in sorted(m.beats, key=lambda b: (b.position or 0, b.x)):
            if b.duration is not None and b.position is not None:
                assert b.position == pos
                pos += b.duration
