from songsterr_tab.parse import measure_boundaries, parse_lines, parse_meta


def test_metadata(html_src):
    meta = parse_meta(html_src)
    assert meta.title == "Speed Demon"
    assert meta.artist == "Dance Gavin Dance"
    assert meta.track == "Andrew Wells - Distortion Guitar"
    assert meta.tempo == 147
    assert meta.time_signature == "4/4"
    assert meta.tuning == ["E", "B", "G", "D", "A", "D"]


def test_lines(html_src):
    lines = parse_lines(html_src)
    assert len(lines) == 21
    # lines are contiguous and ordered
    assert [ln.index for ln in lines] == list(range(21))
    first = lines[0]
    assert first.strings_path is not None
    assert first.viewbox[2] > 0  # has a width


def test_measure_boundaries(html_src):
    first = parse_lines(html_src)[0]
    bounds = measure_boundaries(first.strings_path)
    # the first line carries several barlines, strictly increasing in x
    assert len(bounds) >= 3
    assert bounds == sorted(bounds)
