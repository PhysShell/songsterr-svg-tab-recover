from songsterr_tab.geometry import continuous_subpaths
from songsterr_tab.glyphs import (
    group_glyphs,
    looks_like_digit,
    nearest_string,
)
from songsterr_tab.parse import parse_lines


def test_recognizer_has_all_song_digits(recog):
    labels = {t.label for t in recog.templates}
    assert {"0", "3", "5", "6", "7", "8", "9"} <= labels


def test_nearest_string():
    assert nearest_string(5.0) == 0     # high string row
    assert nearest_string(65.0) == 5    # low string row
    assert nearest_string(200.0) is None  # below the stave -> not a fret


def test_glyph_grouping_reunites_counters(html_src, recog):
    line = parse_lines(html_src)[0]
    pairs = []
    for d, measure in line.note_paths:
        for sub in continuous_subpaths(d):
            pairs.append((sub, measure))
    glyphs = [g for g in group_glyphs(pairs) if looks_like_digit(g)]
    assert glyphs
    # every digit glyph classifies cleanly
    for g in glyphs:
        label, dist = recog.classify(g.bitmap())
        assert label is not None
        assert dist <= recog.threshold
