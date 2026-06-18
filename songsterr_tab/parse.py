"""Parse a Songsterr-rendered tab page into structured geometry.

The page is a single flattened DOM string, but the parts we need are tagged
with stable ids / data-attributes, so targeted regex extraction is more robust
here than a full DOM walk (and keeps the tool dependency-light).
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def _text(html_src: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, html_src)
    return html.unescape(m.group(1)).strip() if m else None


@dataclass
class SongMeta:
    title: Optional[str] = None
    artist: Optional[str] = None
    track: Optional[str] = None
    tempo: Optional[int] = None
    time_signature: Optional[str] = None
    tuning: List[str] = field(default_factory=list)


def parse_meta(html_src: str) -> SongMeta:
    meta = SongMeta()
    meta.title = _text(html_src, r'id="song-ttl"[^>]*>([^<]+)<')
    meta.artist = _text(html_src, r'id="song-artist"[^>]*>([^<]+)<')
    track = _text(html_src, r'ZQQn2G_trackForPrint">\s*([^<]+?)\s*</div>')
    if track:
        meta.track = re.sub(r"^Track:\s*", "", track)

    tempo = _text(html_src, r'ai7mjG_tempoText">[^0-9]*([0-9]+)')
    if tempo:
        meta.tempo = int(tempo)

    sig1 = _text(html_src, r'id="0-0-0-sig1"[^>]*>([^<]+)<')
    sig2 = _text(html_src, r'id="0-0-0-sig2"[^>]*>([^<]+)<')
    if sig1 and sig2:
        meta.time_signature = f"{sig1}/{sig2}"

    # Tuning: the open-string note letters of the first rendered tab line,
    # ordered top (string 1 / highest) to bottom (string 6 / lowest).
    first_line = _first_tab_svg(html_src)
    src = first_line if first_line else html_src
    tuning = re.findall(r'class="-0AoUa_tuning">([A-G]#?)<', src)
    meta.tuning = tuning[:6]
    return meta


def _extract_balanced(src: str, start: int, tag: str = "svg") -> Tuple[str, int]:
    """Return the full ``<tag>...</tag>`` element beginning at ``start``."""
    open_re = re.compile(rf"<{tag}\b")
    close_re = re.compile(rf"</{tag}>")
    depth = 0
    i = start
    while i < len(src):
        o = open_re.search(src, i)
        c = close_re.search(src, i)
        if c is None:
            break
        if o is not None and o.start() < c.start():
            depth += 1
            i = o.end()
        else:
            depth -= 1
            i = c.end()
            if depth == 0:
                return src[start:i], i
    return src[start:], len(src)


def _first_tab_svg(html_src: str) -> Optional[str]:
    m = re.search(r'data-player-key="tab"[^>]*data-line="0"', html_src)
    if not m:
        return None
    svg_start = html_src.find("<svg", m.end())
    if svg_start < 0:
        return None
    svg, _ = _extract_balanced(html_src, svg_start, "svg")
    return svg


@dataclass
class TabLine:
    index: int
    viewbox: Tuple[float, float, float, float]
    strings_path: Optional[str]
    # (d, measure_number)
    note_paths: List[Tuple[str, int]] = field(default_factory=list)
    rhythm_paths: List[str] = field(default_factory=list)  # vENqEG_voice d-strings
    measure_numbers: List[Tuple[float, int]] = field(default_factory=list)  # (x, number)
    labels: List[Tuple[float, float, str]] = field(default_factory=list)  # (x, y, text)


def parse_lines(html_src: str) -> List[TabLine]:
    lines: List[TabLine] = []
    for m in re.finditer(r'data-player-key="tab"[^>]*data-line="(\d+)"', html_src):
        idx = int(m.group(1))
        svg_start = html_src.find("<svg", m.end())
        if svg_start < 0:
            continue
        svg, _ = _extract_balanced(html_src, svg_start, "svg")

        vb_m = re.search(r'viewBox="([\-0-9.]+)\s+([\-0-9.]+)\s+([\-0-9.]+)\s+([\-0-9.]+)"', svg)
        viewbox = tuple(float(vb_m.group(i)) for i in range(1, 5)) if vb_m else (0, 0, 0, 0)

        strings = None
        sm = re.search(r'<path d="([^"]+)"[^>]*data-testid="tab-strings-path"', svg)
        if sm:
            strings = sm.group(1)

        note_paths = [
            (d, int(num))
            for d, num in re.findall(
                r'<path d="([^"]+)"[^>]*data-notes-measure="(\d+)"', svg
            )
        ]

        rhythm_paths = re.findall(r'<path d="([^"]+)"[^>]*class="vENqEG_voice"', svg)

        measure_numbers = [
            (float(x), int(n))
            for x, n in re.findall(
                r'<text x="([\-0-9.]+)"[^>]*class="j6szJq_number">(\d+)<', svg
            )
        ]

        labels = [
            (float(x), float(y), html.unescape(t).strip())
            for x, y, t in re.findall(
                r'<text x="([\-0-9.]+)" y="([\-0-9.]+)"[^>]*>([^<]+)</text>', svg
            )
        ]

        lines.append(
            TabLine(
                index=idx,
                viewbox=viewbox,
                strings_path=strings,
                note_paths=note_paths,
                rhythm_paths=rhythm_paths,
                measure_numbers=measure_numbers,
                labels=labels,
            )
        )
    lines.sort(key=lambda ln: ln.index)
    return lines


def string_rows(strings_path: str) -> List[float]:
    """The 6 horizontal string-line y-positions, derived from the strings path.

    Horizontal segments are written as ``...,{y}H{x}``; the six most common y
    values (top to bottom) are the stave lines.  Falls back to the standard
    layout if the path is missing or malformed.
    """
    from collections import Counter

    ys = Counter(round(float(y), 1) for y in re.findall(r",([\-0-9.]+)H", strings_path))
    # the stave lines are the most frequently drawn horizontal y-values
    common = [y for y, _ in ys.most_common() if y > 0]  # drop y=0 framing artifact
    if len(common) >= 6:
        return sorted(common[:6])
    return [0.5, 12.5, 24.5, 36.5, 48.5, 60.5]


def measure_boundaries(strings_path: str) -> List[float]:
    """Vertical barlines (measure boundaries) are the ``v`` segments in the
    strings path: ``M{x},0.5v59.5``.  Return their sorted x positions."""
    xs = sorted(
        {round(float(x), 3) for x in re.findall(r'M([\-0-9.]+),0\.5v', strings_path)}
    )
    return xs
