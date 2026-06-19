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
    # rest typing + forced beam-completion leave only a few odd measures
    assert len(ok) / len(checked) > 0.85


def test_beam_completion_is_forced_only(recovery):
    # every beam-completed measure now sums exactly to the bar
    completed = [m for m in recovery.measures if m.rhythm_inferred]
    for m in completed:
        assert m.rhythm_ok, m.number


def test_thirty_second_notes_detected(recovery):
    # 32nd-note frets are rendered at reduced size and flagged as such
    small = [n for m in recovery.measures for b in m.beats for n in b.notes if n.small]
    assert small


def test_let_ring_notes_absorb_the_bar(recovery):
    # a parenthesised let-ring note is held; its measure should still balance
    rings = [(m, b) for m in recovery.measures for b in m.beats if b.let_ring]
    assert rings
    for m, b in rings:
        assert m.rhythm_ok, m.number


def test_rest_durations_are_typed(recovery):
    # rests carry a real duration (8th / 16th), never left blank
    rests = [b for m in recovery.measures for b in m.beats if b.is_rest]
    assert rests
    assert all(b.duration is not None for b in rests)
    assert {b.duration for b in rests} <= {
        Fraction(1, 16), Fraction(1, 8), Fraction(1, 4)
    }


def test_positions_are_cumulative(recovery):
    for m in recovery.measures:
        pos = Fraction(0)
        for b in sorted(m.beats, key=lambda b: (b.position or 0, b.x)):
            if b.duration is not None and b.position is not None:
                assert b.position == pos
                pos += b.duration
