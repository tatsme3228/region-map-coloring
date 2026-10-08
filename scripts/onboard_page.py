#!/usr/bin/env python3
"""onboard_page.py — one-command SVG onboarding for the region-map engine.

Part of the region-map-coloring skill (Phase 2). The SVG folder is the
single source of truth. For each page stem this tool:

  1. rasterizes the ORIGINAL SVG with WebKit (rasterize_svg.swift in this
     script's directory, same engine as the renderer-fidelity gate
     reference) — cached in --cache-dir, refreshed when the SVG changes,
  2. copies the SVG into --pages-dir (visual authority, untouched),
  3. builds the lossless region-ID map (make_region_map.py, run-length
     two-pass union-find, ~0.2 s per 1024x1536 page),
  4. upserts the ContentManifest.json entry (regionMap + regionCount),
  5. prints QA stats; exits 1 when the region count is out of band 6-64.

Fallback: if WebKit rasterization fails and --fallback-dir is given with a
<stem>.png present, it is used instead (logged). On hosts without swiftc
the WebKit step is skipped entirely — supply rasters via --fallback-dir
(any faithful rasterizer works) or pre-place <stem>-raster.png in the cache.

Usage:
  python3 onboard_page.py <stem> --title "Display Title" \
      --svg-dir <dir-with-svgs> --pages-dir <dir> --manifest <json> \
      [--category animals] [--cache-dir DIR] [--fallback-dir DIR] \
      [<stem> --title "..." ...]
"""

import json
import os
import shutil
import subprocess
import sys

from PIL import Image

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAKE_MAP = os.path.join(SCRIPT_DIR, "make_region_map.py")
SRC = os.path.join(SCRIPT_DIR, "rasterize_svg.swift")

BAND = (6, 64)
INK_THRESHOLD = 128

VALUE_OPTS = {"--title", "--svg-dir", "--pages-dir", "--manifest",
              "--category", "--cache-dir", "--fallback-dir"}


def parse_args(argv):
    opts = {"category": "animals", "cache-dir": os.path.join(os.getcwd(), ".regionmap-cache")}
    stems, titles = [], []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in VALUE_OPTS:
            if tok == "--title":
                if not stems:
                    print("error: --title before any stem")
                    sys.exit(1)
                titles[-1] = argv[i + 1]
            else:
                opts[tok[2:]] = argv[i + 1]
            i += 2
        else:
            stems.append(tok)
            titles.append(None)
            i += 1
    for req in ("svg-dir", "pages-dir", "manifest"):
        if req not in opts:
            print(__doc__)
            sys.exit(1)
    return stems, titles, opts


def ensure_rasterizer(cache_dir):
    bin_path = os.path.join(cache_dir, "bin", "rasterize_svg")
    if os.path.exists(bin_path) and os.path.getmtime(bin_path) >= os.path.getmtime(SRC):
        return bin_path
    if shutil.which("swiftc") is None:
        print("note: no swiftc on PATH — using cached or fallback rasters only")
        return None
    os.makedirs(os.path.dirname(bin_path), exist_ok=True)
    print("building rasterizer...")
    subprocess.run(["swiftc", "-O", SRC, "-o", bin_path], check=True)
    return bin_path


def raster_path(stem, opts, bin_path):
    svg = os.path.join(opts["svg-dir"], stem + ".svg")
    cache = opts["cache-dir"]
    out = os.path.join(cache, stem + "-raster.png")
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(svg):
        return out
    if bin_path is not None:
        os.makedirs(cache, exist_ok=True)
        proc = subprocess.run([bin_path, opts["svg-dir"], cache, stem],
                              capture_output=True, text=True)
        if proc.returncode == 0 and os.path.exists(out):
            return out
        sys.stderr.write(proc.stderr)
    if opts.get("fallback-dir"):
        fallback = os.path.join(opts["fallback-dir"], stem + ".png")
        if os.path.exists(fallback):
            print("warning: WebKit raster unavailable for %s; using fallback raster" % stem)
            return fallback
    print("error: no raster for %s — pre-place %s with any rasterizer, "
          "or pass --fallback-dir <dir> containing %s.png"
          % (stem, out, stem))
    return None


def ink_share(path):
    data = Image.open(path).convert("L").tobytes()
    return sum(1 for v in data if v < INK_THRESHOLD) / len(data)


def onboard(stem, title, opts, bin_path):
    svg_src = os.path.join(opts["svg-dir"], stem + ".svg")
    if not os.path.exists(svg_src):
        print("error: missing %s" % svg_src)
        return False

    raster = raster_path(stem, opts, bin_path)
    if raster is None:
        print("error: no raster source for %s" % stem)
        return False

    # Informational sanity: WebKit raster vs fallback (clean) raster.
    if opts.get("fallback-dir"):
        clean = os.path.join(opts["fallback-dir"], stem + ".png")
        if os.path.exists(clean) and raster != clean:
            a, b = ink_share(raster), ink_share(clean)
            print("sanity: ink webkit=%.4f clean=%.4f (|d|=%.4f)"
                  % (a, b, abs(a - b)))

    # 1. SVG into the bundle (visual authority stays original).
    os.makedirs(opts["pages-dir"], exist_ok=True)
    shutil.copyfile(svg_src, os.path.join(opts["pages-dir"], stem + ".svg"))

    # 2. Region-ID map + sidecar.
    map_png = os.path.join(opts["pages-dir"], stem + "-regions.png")
    sidecar = os.path.join(opts["cache-dir"], stem + ".regions.json")
    page_id = "%s_%s" % (opts["category"], stem.replace("-", "_"))
    subprocess.run([sys.executable, MAKE_MAP, raster, map_png, sidecar,
                    "--id", page_id,
                    "--svg", stem + ".svg",
                    "--region-map", stem + "-regions"], check=True)
    with open(sidecar) as f:
        stats = json.load(f)
    count = stats["regionCount"]

    # 3. Manifest upsert.
    with open(opts["manifest"]) as f:
        manifest = json.load(f)
    entry = {
        "id": page_id,
        "category": opts["category"],
        "svgFile": stem,
        "thumbnail": None,
        "title": title,
        "regionMap": stem + "-regions",
        "regionCount": count,
    }
    pages = manifest["pages"]
    for i, existing in enumerate(pages):
        if existing["id"] == page_id:
            pages[i] = entry
            break
    else:
        pages.append(entry)
    with open(opts["manifest"], "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    lo, hi = BAND
    ok = lo <= count <= hi
    print("onboarded %s: regions=%d (band %d-%d: %s)"
          % (stem, count, lo, hi, "OK" if ok else "OUT OF BAND"))
    return ok


def main():
    stems, titles, opts = parse_args(sys.argv[1:])
    if not stems:
        print(__doc__)
        return 1
    bin_path = ensure_rasterizer(opts["cache-dir"])
    ok = True
    for stem, title in zip(stems, titles):
        ok = onboard(stem, title or stem.replace("-", " ").title(), opts, bin_path) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
