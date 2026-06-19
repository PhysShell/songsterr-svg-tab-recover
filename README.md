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

# 4. MIDI: export the recovered notes (pitch + rhythm)  -> out/tab.mid
python -m songsterr_tab midi    fixtures/speed-demon.rendered.html --out out/
```

The MIDI export turns the recovered model — pitches from string+fret over the
tuning, onsets and durations from the rhythm pass — into a standard format-0
file (480 PPQ, tempo + time signature, GM distortion guitar), with no
third-party dependency. Open it in any DAW or MuseScore to hear/verify the
recovery.

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

## From just the URL (headless render)

If you can't easily capture the rendered DOM (e.g. you're on a phone), let a
headless browser render the public page for you, scrolling so every
(virtualised) tab line draws, then parse it:

```bash
pip install playwright && python -m playwright install chromium
python -m tools.fetch_rendered \
    "https://www.songsterr.com/a/wsa/dance-gavin-dance-speed-demon-tab-s659270" \
    out/rendered.html
python -m songsterr_tab notes out/rendered.html --out out/ --ascii
```

This just renders the free page like any browser and reads the resulting SVG —
it does **not** touch Songsterr's protected note-data API. `--ascii` also writes
a readable `out/tab.txt`:

```
       m2  m3
E|-0-------|-0-0-0-0---------------|
B|-0-3-5-3-|-0-0-0-0-3-5-5-5-5-3-5-|
G|-0-------|-0-0-0-0---5-5-5-5-----|
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
- Stave geometry: string rows (derived per line), measure boundaries, numbers.
- Fret recovery: string + fret + MIDI per note, chords grouped into beats,
  multi-digit frets (the tens digit is no longer dropped). All ten digits 0-9.
- **Rhythm**: durations from the beam/stem voice (beam count -> 8th/16th/32nd,
  augmentation dots, plain quarters) plus rest glyphs detected in the note
  voice and typed by shape (taller two-hook glyph = 16th rest, shorter one-hook
  = 8th rest). Songsterr sometimes omits a note's secondary (16th) beam stub, so
  a 16th reads as an 8th; when a measure overruns by whole 16ths and *every*
  beamed 8th sitting next to a 16th/dotted-8th must be demoted to absorb the
  surplus exactly, the correction is forced (no choice of which note) and
  applied -- such measures are marked `beamCompleted`. Beat onsets are computed,
  and each measure carries a `rhythmOk` flag (do its durations sum to the time
  signature). The ASCII tab is spaced proportionally to duration.
- Debug overlay for visual verification.

Sustained and let-ring notes (a half note with no beam, or a tied note drawn
in parentheses, whose value the rhythm voice never spells out) are recovered
from x-geometry: a note's horizontal position is proportional to its onset
within the measure, so when a measure underruns and exactly one note -- a
let-ring note, or the one whose span to the next onset lands on a clean value
given the shortfall -- can absorb it, it is extended. Such measures are flagged
`rhythmInferred`.

32nd notes are drawn two ways the parser now reads: a reduced-size fret glyph
(note voice) and a diagonal slash abbreviating the secondary beams across the
stem (rhythm voice). Either flags the note `thirtySecond`. A 32nd pairs with a
dotted-16th to fill an eighth (1/32 + 3/32) -- the fine analogue of the
dotted-8th + 16th gallop -- and that pairing is applied when it makes the bar
balance exactly. Parentheses around a let-ring note are flagged `letRing`.

Rhythm status: on the bundled song **100/100 measures sum exactly to the bar**
(84 read straight from the geometry, 16 reconstructed via the gallop / 32nd /
let-ring / sustained-note rules). `rhythmOk` flags which measures balance and
`rhythmInferred` which used a reconstruction. Caveat: a few repeated 32nd riffs
balance through the sum-closing fallback rather than an exact subdivision (their
finer rhythm is under-determined once Songsterr drops the augmentation dots from
the render), so their `thirtySecond` flag is reliable even where the per-note
duration is approximate.

Still out of scope:

- **Effects** — palm mute / harmonics (text) and slides / ties (effect curves).
- **MusicXML / GP5 export** — the AST now has durations, so MusicXML export is
  the natural next milestone (eyeball in MuseScore), GP5 later via PyGuitarPro.
