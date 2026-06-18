"""Geometry helpers for Songsterr SVG tab recovery.

The whole reverse-layout pipeline lives or dies on robust SVG path handling,
so we lean on ``svgpathtools`` (which correctly handles the nasty bits like
arc-flag packing) instead of hand-rolling a path parser.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from svgpathtools import Path, parse_path


@dataclass(frozen=True)
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def width(self) -> float:
        return self.xmax - self.xmin

    @property
    def height(self) -> float:
        return self.ymax - self.ymin

    @property
    def cx(self) -> float:
        return (self.xmin + self.xmax) / 2.0

    @property
    def cy(self) -> float:
        return (self.ymin + self.ymax) / 2.0

    def x_overlap(self, other: "BBox") -> float:
        return min(self.xmax, other.xmax) - max(self.xmin, other.xmin)


def subpath_bbox(sub: Path) -> BBox:
    xmin, xmax, ymin, ymax = sub.bbox()
    return BBox(xmin, ymin, xmax, ymax)


def continuous_subpaths(d: str) -> List[Path]:
    """Split a path ``d`` string into continuous subpaths (one per ``M``)."""
    return list(parse_path(d).continuous_subpaths())


def sample_polyline(sub: Path, n: int = 96) -> List[Tuple[float, float]]:
    """Approximate a subpath outline as a closed polyline of ``n`` points."""
    return [(sub.point(k / n).real, sub.point(k / n).imag) for k in range(n)]


def rasterize(polys: Sequence[Sequence[Tuple[float, float]]], box: BBox, size: int) -> List[int]:
    """Even-odd fill of one or more polygons into a ``size`` x ``size`` bitmap.

    Each row is returned as an integer bitmask (bit ``size-1`` == leftmost
    column) which makes Hamming-distance template matching cheap.
    """
    w = box.width or 1e-6
    h = box.height or 1e-6
    rows: List[int] = []
    for r in range(size):
        py = box.ymin + h * (r + 0.5) / size
        row = 0
        for col in range(size):
            px = box.xmin + w * (col + 0.5) / size
            inside = False
            for pts in polys:
                npts = len(pts)
                for i in range(npts):
                    ax, ay = pts[i]
                    bx, by = pts[(i + 1) % npts]
                    if (ay > py) != (by > py):
                        xint = ax + (py - ay) / (by - ay) * (bx - ax)
                        if px < xint:
                            inside = not inside
            row = (row << 1) | (1 if inside else 0)
        rows.append(row)
    return rows


def hamming(a: Sequence[int], b: Sequence[int]) -> int:
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))
