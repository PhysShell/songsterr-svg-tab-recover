# songsterr-svg-tab-recover

Reverse-layout parser that recovers guitar **tablature from a Songsterr-rendered
SVG page**.

A Songsterr tab page is not source data — it is the *final vector rendering* of a
tab that the React app already laid out. The musical model is gone; what's left
is a soup of `<path d="M 156.25 5.04 ...">`. The catch: **fret numbers are not
`<text>`** — the layout engine baked them into Bézier outlines. So we can't read
them as text, and naive OCR is overkill.

This tool does geometric recovery instead:

```
Rendered SVG  ->  line/stave geometry  ->  glyph shapes  ->  note events  ->  JSON
```

> **Note on the "proper" path.** If you have a Songsterr Plus account, the
> *officially supported* route is to download the revision as Guitar Pro / MIDI
> and parse that (e.g. with PyGuitarPro / music21). That keeps real durations and
> semantics that the renderer threw away. This project is for the case where all
> you have is the rendered DOM. Don't use it to circumvent paid downloads.

## The key trick: fret digits are font glyphs, not OCR

Songsterr draws fret numbers with a fixed font, so **every instance of a digit
shares the same outline up to translation/scale**. That makes recognition
*deterministic structural matching*, not fuzzy OCR:

1. Split each `data-notes-measure` path into continuous subpaths (one per `M`).
2. Regroup subpaths into glyphs — a digit's counter (the hole in `0/6/8/9`) is a
   separate subpath that *x-overlaps* its outer contour, while neighbouring
   digits don't overlap. Grouping on x-overlap reunites a glyph with its holes
   without merging neighbours.
3. Rasterize each glyph to a scale-normalised 16×16 bitmap.
4. Match against labeled templates by Hamming distance.

On the bundled fixture this matches **908/908 fret digits with zero Hamming
distance** — i.e. pixel-identical to the templates.

## Install

```bash
pip install -r requirements.txt          # runtime
pip install -r requirements-dev.txt      # + pytest, cairosvg (PNG overlays)
```

## Usage

```bash
# 1. Inspect: song metadata + per-line geometry  -> out/meta.json, out/lines.json
python -m songsterr_tab inspect fixtures/speed-demon.sample.html --out out/

# 2. Notes: recover string/fret/midi note events  -> out/notes.json
python -m songsterr_tab notes   fixtures/speed-demon.sample.html --out out/

# 3. Overlay: debug SVG with recovered frets drawn on the stave
python -m songsterr_tab overlay fixtures/speed-demon.sample.html --out out/ --line 0
```

`inspect` on the bundled fixture prints:

```
title:          Speed Demon
artist:         Dance Gavin Dance
track:          Andrew Wells - Distortion Guitar
tempo:          147
timeSignature:  4/4
tuning:         E B G D A D
tab lines:      21
```

`notes.json` (1-based strings, MIDI resolved through the tuning):

```json
{
  "number": 2,
  "beats": [
    {"x": 162.5, "notes": [
      {"string": 1, "fret": 0, "midi": 64, "confidence": 0},
      {"string": 2, "fret": 0, "midi": 59, "confidence": 0},
      {"string": 3, "fret": 0, "midi": 55, "confidence": 0}
    ]},
    {"x": 299.5, "notes": [{"string": 2, "fret": 3, "midi": 62, "confidence": 0}]}
  ]
}
```

`confidence` is the worst per-digit Hamming distance (0 = exact match).

## Verifying the result

Render the debug overlay and look at it — the boxes must sit on the right string
lines and the printed numbers must read correctly:

```bash
python -m songsterr_tab overlay fixtures/speed-demon.sample.html --out out/ --line 0
python -c "import cairosvg; cairosvg.svg2png(url='out/debug-line-000.svg', \
  write_to='out/line0.png', output_width=3000, background_color='#111')"
```

## Two kinds of export (important!)

A Songsterr page can be saved two very different ways, and only one contains
the tab:

| What you saved | Contains | Use |
|---|---|---|
| **Rendered DOM** — DevTools `copy(document.documentElement.outerHTML)` *after* the tab draws | the tablature **SVG** (`data-notes-measure`, `tab-strings-path`) | `notes` / `overlay` recover the actual notes |
| **Page source** — *View Source* / `Ctrl+U` | a `<script id="state">` metadata blob, **no notes** (the app fetches them later) | `inspect` reports metadata + which track/revision IDs to use |

`inspect` auto-detects which one you gave it. On a page-source file it prints
the song / revision / track metadata (including each track's tuning) and
explains how to grab the rendered DOM instead:

```
python -m songsterr_tab inspect fixtures/speed-demon.source.html --out out/
# NOTE: this is the page *source* ... it contains metadata but NO note data.
# songId: 659270   revisionId: 2597654
# partId 0: Andrew Wells - Distortion Guitar  [tuning: E B G D A D]
```

## Architecture

```
songsterr_tab/
  geometry.py   SVG path -> subpaths, bbox, polyline sampling, even-odd raster
  parse.py      HTML -> SongMeta + TabLine[] (viewBox, strings path, note paths,
                measure numbers, text labels); barline extraction
  glyphs.py     glyph grouping, string mapping, DigitRecognizer (template match)
  notes.py      digits -> multi-digit frets -> chords/beats -> measures + MIDI
  debug.py      debug overlay SVG
  cli.py        inspect / notes / overlay subcommands
tools/
  generate_templates.py   learn labeled digit templates from a fixture
templates/
  digits.json   labeled 16x16 glyph templates
fixtures/
  speed-demon.sample.html  Dance Gavin Dance - Speed Demon (rendered tab page)
tests/          pytest suite
```

### Regenerating templates

Templates are learned from a fixture and labeled by cluster frequency (verified
by eye). To rebuild:

```bash
python -m tools.generate_templates fixtures/speed-demon.sample.html templates/digits.json
```

## Status & scope

Working and tested:

- Song metadata: title, artist, track, tempo, time signature, tuning.
- Stave geometry: string rows, measure boundaries, measure numbers.
- Fret recovery: string + fret + MIDI per note, chords grouped into beats,
  multi-digit frets supported.
- Debug overlay for visual verification.

Deliberately out of scope for now (clear next steps):

- **Rhythm / durations** — the beam/stem paths exist below the stave but their
  duration semantics still need geometric decoding. Without this, notes have
  pitch+position but no length.
- **Effects** — palm mute / harmonics (text) and slides / ties (effect curves).
- **MusicXML / GP5 export** — once durations land, the AST can export to
  MusicXML first (easy to eyeball in MuseScore) and GP5 later via PyGuitarPro.

The current template set covers the digits present in the bundled song
(`0 3 5 6 7 8 9`). Adding more fixtures extends coverage to `1 2 4` and beyond;
the recognizer is template-driven, so this is just data.
