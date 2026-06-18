import os

from songsterr_tab.state import (
    has_rendered_tab,
    midi_to_name,
    parse_state,
)

ROOT = os.path.dirname(os.path.dirname(__file__))
SOURCE = os.path.join(ROOT, "fixtures", "speed-demon.source.html")
RENDERED = os.path.join(ROOT, "fixtures", "speed-demon.sample.html")


def _read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def test_midi_to_name():
    assert midi_to_name(64) == "E"
    assert midi_to_name(38) == "D"
    assert midi_to_name(38, with_octave=True) == "D2"


def test_detects_export_kind():
    assert has_rendered_tab(_read(RENDERED)) is True
    assert has_rendered_tab(_read(SOURCE)) is False


def test_parse_state_metadata():
    info = parse_state(_read(SOURCE))
    assert info is not None
    assert info.song_id == 659270
    assert info.revision_id == 2597654
    assert info.title == "Speed Demon"
    assert info.artist == "Dance Gavin Dance"
    # source export carries metadata but no note data
    assert info.has_note_data is False
    assert len(info.tracks) == 4


def test_state_track_tuning_names():
    info = parse_state(_read(SOURCE))
    guitar = next(t for t in info.tracks if t.part_id == 0)
    assert guitar.tuning_midi == [64, 59, 55, 50, 45, 38]
    assert guitar.tuning_names == ["E", "B", "G", "D", "A", "D"]
    drums = next(t for t in info.tracks if t.part_id == 2)
    assert drums.is_drums is True
