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
from .state import has_rendered_tab, parse_state


def _meta_dict(meta):
    return {
        "title": meta.title,
        "artist": meta.artist,
        "track": meta.track,
        "tempo": meta.tempo,
        "timeSignature": meta.time_signature,
        "tuning": meta.tuning,
    }


def _report_source_only(html_src, out_dir) -> int:
    """The file is page-source (pre-hydration): metadata only, no tab SVG."""
    info = parse_state(html_src)
    if info is None:
        print("This file has neither a rendered tablature SVG nor a Songsterr "
              "state blob -- it doesn't look like a Songsterr tab page.")
        return 2

    print("NOTE: this is the page *source* (View Source), captured before the")
    print("      app fetched the tab. It contains metadata but NO note data.")
    print()
    print(f"title:        {info.title}")
    print(f"artist:       {info.artist}")
    print(f"songId:       {info.song_id}")
    print(f"revisionId:   {info.revision_id}")
    print(f"author:       {info.author}")
    print(f"tracks:")
    for t in info.tracks:
        tuning = " ".join(t.tuning_names) if t.tuning_midi else "(none)"
        print(f"  partId {t.part_id}: {t.title}  [tuning: {tuning}]")
    print()
    print("To recover notes you need the *rendered DOM*, not the source:")
    print("  open the tab, wait for it to draw, then in DevTools run")
    print("  copy(document.documentElement.outerHTML)  (or right-click the")
    print("  <html> element -> Copy -> Copy outerHTML) and save that.")

    payload = {
        "kind": "source-only",
        "hasNoteData": info.has_note_data,
        "songId": info.song_id,
        "revisionId": info.revision_id,
        "title": info.title,
        "artist": info.artist,
        "author": info.author,
        "createdAt": info.created_at,
        "defaultTrack": info.default_track,
        "tracks": [
            {
                "partId": t.part_id,
                "title": t.title,
                "instrument": t.instrument,
                "instrumentId": t.instrument_id,
                "isDrums": t.is_drums,
                "tuningMidi": t.tuning_midi,
                "tuning": t.tuning_names,
            }
            for t in info.tracks
        ],
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\n-> {out_dir}/meta.json")
    return 0


def cmd_inspect(args) -> int:
    html_src = open(args.input, encoding="utf-8").read()
    os.makedirs(args.out, exist_ok=True)

    if not has_rendered_tab(html_src):
        return _report_source_only(html_src, args.out)

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
    if not has_rendered_tab(html_src):
        print("No rendered tablature SVG in this file -- nothing to recover.")
        print("(Looks like page source rather than the rendered DOM.)")
        print("Run `inspect` for details on what to export instead.")
        return 2
    recog = DigitRecognizer.load(args.templates)
    rec = recover(html_src, recog)

    payload = {
        "meta": _meta_dict(rec.meta),
        "unrecognized": rec.unrecognized,
        "measures": [
            {
                "number": m.number,
                "line": m.line,
                "rhythmOk": m.rhythm_ok,
                "rhythmInferred": m.rhythm_inferred,
                "durationSum": str(m.duration_sum) if m.duration_sum is not None else None,
                "beats": [
                    {
                        "x": round(b.x, 2),
                        "duration": str(b.duration) if b.duration is not None else None,
                        "position": str(b.position) if b.position is not None else None,
                        "rest": b.is_rest,
                        "letRing": b.let_ring,
                        "notes": [
                            {
                                "string": n.string + 1,  # 1-based for humans
                                "fret": "x" if n.muted else n.fret,
                                "midi": n.midi,
                                "confidence": n.confidence,
                                "thirtySecond": n.small,
                                "muted": n.muted,
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

    if args.ascii:
        from .ascii_tab import render_ascii
        tab_path = os.path.join(args.out, "tab.txt")
        with open(tab_path, "w", encoding="utf-8") as fh:
            fh.write(render_ascii(rec))

    total_notes = sum(len(b.notes) for m in rec.measures for b in m.beats)
    checked = [m for m in rec.measures if m.rhythm_ok is not None]
    ok = sum(1 for m in checked if m.rhythm_ok)
    print(f"measures:       {len(rec.measures)}")
    print(f"beats:          {sum(len(m.beats) for m in rec.measures)}")
    print(f"notes:          {total_notes}")
    print(f"unrecognized:   {rec.unrecognized}")
    if checked:
        print(f"rhythm valid:   {ok}/{len(checked)} measures sum to the time signature")
    print(f"-> {out_path}")
    if args.ascii:
        print(f"-> {os.path.join(args.out, 'tab.txt')}")
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


def cmd_midi(args) -> int:
    html_src = open(args.input, encoding="utf-8").read()
    os.makedirs(args.out, exist_ok=True)
    if not has_rendered_tab(html_src):
        print("No rendered tablature SVG in this file -- nothing to export.")
        return 2
    from .midi import write_midi
    recog = DigitRecognizer.load(args.templates)
    rec = recover(html_src, recog)
    out_path = os.path.join(args.out, "tab.mid")
    sounded = write_midi(rec, out_path)
    print(f"title:          {rec.meta.title}")
    print(f"tempo:          {rec.meta.tempo} bpm   timeSignature: {rec.meta.time_signature}")
    print(f"sounded notes:  {sounded}")
    print(f"-> {out_path}")
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
    pn.add_argument("--ascii", action="store_true", help="also write tab.txt (ASCII tab)")
    pn.set_defaults(func=cmd_notes)

    po = sub.add_parser("overlay", help="render debug SVG overlays of recovered frets")
    po.add_argument("input")
    po.add_argument("--out", default="out")
    po.add_argument("--templates", default=DEFAULT_TEMPLATES)
    po.add_argument("--line", type=int, default=None, help="only this line index")
    po.set_defaults(func=cmd_overlay)

    pm = sub.add_parser("midi", help="export recovered notes to a MIDI file")
    pm.add_argument("input")
    pm.add_argument("--out", default="out")
    pm.add_argument("--templates", default=DEFAULT_TEMPLATES)
    pm.set_defaults(func=cmd_midi)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
