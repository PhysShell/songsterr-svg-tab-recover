"""Command-line entry point for the Songsterr SVG tab recoverer.

Usage:
    python -m songsterr_tab inspect fixtures/speed-demon.sample.html --out out/
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict

from .debug import overlay_line
from .glyphs import DEFAULT_TEMPLATES, DigitRecognizer
from .notes import recover
from .parse import measure_boundaries, parse_lines, parse_meta


def _meta_dict(meta):
    return {
        "title": meta.title,
        "artist": meta.artist,
        "track": meta.track,
        "tempo": meta.tempo,
        "timeSignature": meta.time_signature,
        "tuning": meta.tuning,
    }


def cmd_inspect(args) -> int:
    html_src = open(args.input, encoding="utf-8").read()
    os.makedirs(args.out, exist_ok=True)

    meta = parse_meta(html_src)
    lines = parse_lines(html_src)

    lines_json = []
    for ln in lines:
        bounds = measure_boundaries(ln.strings_path) if ln.strings_path else []
        lines_json.append({
            "index": ln.index,
            "viewBox": ln.viewbox,
            "measureNumbers": ln.measure_numbers,
            "barlineX": bounds,
            "noteMeasures": sorted({m for _, m in ln.note_paths}),
            "textLabels": ln.labels,
        })

    with open(os.path.join(args.out, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(_meta_dict(meta), fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "lines.json"), "w", encoding="utf-8") as fh:
        json.dump(lines_json, fh, ensure_ascii=False, indent=2)

    print(f"title:          {meta.title}")
    print(f"artist:         {meta.artist}")
    print(f"track:          {meta.track}")
    print(f"tempo:          {meta.tempo}")
    print(f"timeSignature:  {meta.time_signature}")
    print(f"tuning:         {' '.join(meta.tuning)}")
    print(f"tab lines:      {len(lines)}")
    print(f"-> {args.out}/meta.json, lines.json")
    return 0


def cmd_notes(args) -> int:
    html_src = open(args.input, encoding="utf-8").read()
    os.makedirs(args.out, exist_ok=True)
    recog = DigitRecognizer.load(args.templates)
    rec = recover(html_src, recog)

    payload = {
        "meta": _meta_dict(rec.meta),
        "unrecognized": rec.unrecognized,
        "measures": [
            {
                "number": m.number,
                "line": m.line,
                "beats": [
                    {
                        "x": round(b.x, 2),
                        "notes": [
                            {
                                "string": n.string + 1,  # 1-based for humans
                                "fret": n.fret,
                                "midi": n.midi,
                                "confidence": n.confidence,
                            }
                            for n in b.notes
                        ],
                    }
                    for b in m.beats
                ],
            }
            for m in rec.measures
        ],
    }
    out_path = os.path.join(args.out, "notes.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    total_notes = sum(len(b.notes) for m in rec.measures for b in m.beats)
    print(f"measures:       {len(rec.measures)}")
    print(f"beats:          {sum(len(m.beats) for m in rec.measures)}")
    print(f"notes:          {total_notes}")
    print(f"unrecognized:   {rec.unrecognized}")
    print(f"-> {out_path}")
    return 0


def cmd_overlay(args) -> int:
    html_src = open(args.input, encoding="utf-8").read()
    os.makedirs(args.out, exist_ok=True)
    recog = DigitRecognizer.load(args.templates)
    lines = parse_lines(html_src)
    if args.line is not None:
        lines = [ln for ln in lines if ln.index == args.line]
    written = 0
    for ln in lines:
        svg = overlay_line(ln, recog)
        path = os.path.join(args.out, f"debug-line-{ln.index:03d}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
        written += 1
    print(f"wrote {written} overlay SVG(s) -> {args.out}/debug-line-*.svg")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="songsterr_tab",
                                description="Recover tablature from Songsterr-rendered SVG.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("inspect", help="dump song metadata + line geometry")
    pi.add_argument("input")
    pi.add_argument("--out", default="out")
    pi.set_defaults(func=cmd_inspect)

    pn = sub.add_parser("notes", help="recover note events (string/fret) to JSON")
    pn.add_argument("input")
    pn.add_argument("--out", default="out")
    pn.add_argument("--templates", default=DEFAULT_TEMPLATES)
    pn.set_defaults(func=cmd_notes)

    po = sub.add_parser("overlay", help="render debug SVG overlays of recovered frets")
    po.add_argument("input")
    po.add_argument("--out", default="out")
    po.add_argument("--templates", default=DEFAULT_TEMPLATES)
    po.add_argument("--line", type=int, default=None, help="only this line index")
    po.set_defaults(func=cmd_overlay)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
