#!/usr/bin/env python3
"""make_region_map.py — build a lossless region-ID map for a coloring page.

Part of the region-map coloring engine.
The visible artwork stays the ORIGINAL traced SVG; this tool derives the
coloring geometry from a black/white raster of that same SVG (produced by
rasterize_svg.swift in this script's directory, via WebKit), so regions
align pixel-for-pixel with the line art.

Pipeline:
  raster PNG -> binarize (L<128 = ink) -> run-length two-pass union-find
  labeling of white pixels -> fillable regions = enclosed white components
  with area >= MIN_AREA plus border-touching white (scene backgrounds)
  with area >= BG_MIN_AREA -> stable IDs 1..N assigned largest-first ->
  emit a lossless RGB PNG where id = R*65536 + G*256 + B, plus a JSON
  sidecar for the manifest.

Backgrounds are fillable: sky/ground touch the image border but are real
coloring regions; tiny border slivers (< BG_MIN_AREA) stay ID 0 like ink.

Pure Python + Pillow only, ~0.2 s per 1024x1536 page. Usage:
  python3 make_region_map.py <raster.png> <out-regions.png> <out.json> \
      --id <page_id> --svg <svg-file-name> --region-map <map-file-name>
"""

import json
import sys
from array import array

from PIL import Image

INK_THRESHOLD = 128   # pixels darker than this are ink (non-fillable)
MIN_AREA = 200        # enclosed white components smaller than this stay 0
BG_MIN_AREA = 5000    # border-touching white (backgrounds) below this stay 0
BAND = (6, 64)        # expected region-count design band


def load_gray(img):
    gray = img.convert("L")
    return gray.tobytes(), gray.size[0], gray.size[1]


def label_runs(data, w, h):
    """Run-length two-pass union-find labeling of white pixels.

    Returns (rows_runs, parent, area, border) where rows_runs[y] is a list
    of (x0, x1, run_id) and parent/area/border are per-run_id arrays
    (index 0 unused). Roots after find() are the connected components.
    """
    parent = array("i", [0])
    area = array("L", [0])
    border = array("B", [0])

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    rows_runs = []
    prev = []
    for y in range(h):
        row = y * w
        cur = []
        x = 0
        while x < w:
            if data[row + x] >= INK_THRESHOLD:
                x0 = x
                while x + 1 < w and data[row + x + 1] >= INK_THRESHOLD:
                    x += 1
                rid = len(parent)
                parent.append(rid)
                area.append(x - x0 + 1)
                border.append(1 if (y == 0 or y == h - 1
                                    or x0 == 0 or x == w - 1) else 0)
                for (p0, p1, pid) in prev:
                    if p0 <= x and x0 <= p1:      # 4-connected overlap
                        r1 = find(rid)
                        r2 = find(pid)
                        if r1 != r2:
                            parent[r2] = r1
                            area[r1] += area[r2]
                            border[r1] |= border[r2]
                            area[r2] = 0
                            border[r2] = 0
                cur.append((x0, x, rid))
                x += 1
            else:
                x += 1
        rows_runs.append(cur)
        prev = cur

    # Fold non-root runs into their root.
    for rid in range(1, len(parent)):
        r = find(rid)
        if r != rid:
            area[r] += area[rid]
            border[r] |= border[rid]
    return rows_runs, parent, area, border, find


def main():
    args = sys.argv[1:]
    if len(args) < 9:
        print(__doc__)
        return 1
    in_path, out_png, out_json = args[0], args[1], args[2]
    opts = dict(zip(args[3::2], args[4::2]))
    page_id = opts["--id"]
    svg_name = opts["--svg"]
    map_name = opts["--region-map"]

    data, w, h = load_gray(Image.open(in_path))
    rows_runs, parent, area, border, find = label_runs(data, w, h)

    # Fillable: enclosed white >= MIN_AREA, or background-sized border white.
    candidates = []
    for rid in range(1, len(parent)):
        if parent[rid] != rid:
            continue
        if border[rid]:
            if area[rid] >= BG_MIN_AREA:
                candidates.append(rid)
        elif area[rid] >= MIN_AREA:
            candidates.append(rid)
    candidates.sort(key=lambda r: area[r], reverse=True)
    region_of_root = {r: i + 1 for i, r in enumerate(candidates)}

    # Encode the map: id = R*65536 + G*256 + B (lossless RGB PNG).
    rgb = bytearray(3 * w * h)
    for y, runs in enumerate(rows_runs):
        row = y * w
        for (x0, x1, rid) in runs:
            rid = region_of_root.get(find(rid), 0)
            if rid == 0:
                continue
            pixel = bytes(((rid >> 16) & 0xFF, (rid >> 8) & 0xFF, rid & 0xFF))
            rgb[3 * (row + x0):3 * (row + x1) + 3] = pixel * (x1 - x0 + 1)
    Image.frombytes("RGB", (w, h), bytes(rgb)).save(out_png, optimize=False)

    total = w * h
    ink = sum(1 for v in data if v < INK_THRESHOLD)
    micro = sum(area[r] for r in range(1, len(parent))
                if parent[r] == r and not border[r] and area[r] < MIN_AREA)
    stats = {
        "id": page_id,
        "svg": svg_name,
        "regionMap": map_name,
        "regionCount": len(candidates),
        "mapSize": [w, h],
        "version": 1,
    }
    with open(out_json, "w") as f:
        json.dump(stats, f, indent=2)
        f.write("\n")

    areas = [area[r] for r in candidates]
    lo, hi = BAND
    print("regions=%d (band %d-%d: %s)"
          % (len(candidates), lo, hi,
             "OK" if lo <= len(candidates) <= hi else "OUT OF BAND"))
    print("largest=%d smallest=%d ink=%.3f micro_share=%.5f"
          % (max(areas) if areas else 0, min(areas) if areas else 0,
             ink / total, micro / total))
    print("map=%s json=%s (%dx%d)" % (out_png, out_json, w, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
