# region-map-coloring

A build-time toolchain for the **region-map coloring engine** — the technique
that lets a children's coloring app answer "which area did the child tap?"
with one exact integer lookup, with no flood fill at runtime, ever.

The core idea: keep the **original SVG as the immutable visual authority**
(displayed, never converted), and derive from it a **lossless region-ID
raster** at build time. Every fillable area in that raster is painted with a
color that silently *is* its integer ID — the PNG is a lookup table, not a
picture:

```
region_id = (R << 16) | (G << 8) | B
```

At runtime you decode that PNG once, and every tap resolves in O(1) by
reading one pixel. Region labeling uses a **run-length two-pass union-find**
instead of per-pixel BFS — it labels a 1024x1536 page in ~0.1-0.2 s (roughly
100x faster on the machine this was developed on; timings are indicative, not
benchmarks).

Everything is local and offline. The region-mapping core is pure Python 3 +
Pillow and runs anywhere; the bundled SVG rasterizer is one Swift file using
macOS WebKit — a faithful default, not a requirement (see Requirements).
No API keys, no network, no paid services.

## What's in the box

| Path | Role |
|---|---|
| `scripts/rasterize_svg.swift` | WebKit SVG -> exact-pixel PNG at the viewBox size (the same rasterization the fidelity reference uses) |
| `scripts/make_region_map.py` | binarize -> run-length union-find labeling -> lossless region-ID PNG + JSON sidecar |
| `scripts/onboard_page.py` | one-command page onboarding: rasterize (cached) + map + manifest upsert + QA stats, exit 1 out of band |
| `SKILL.md` | the engine playbook: core principles, thresholds, runtime integration checklist, QA gate, pitfalls |
| `references/ENGINE-BLUEPRINT.md` | reference implementation map (file roles, manifest schema, test templates, porting order) |
| `sample/balloon-lineart.svg` | original thick-outline line art so the quickstart runs out of the box |

## Requirements

**Portable core (any OS):** Python 3 with Pillow (`pip3 install pillow`).
`make_region_map.py` consumes a black/white raster of the SVG at 1:1 with its
viewBox — any faithful rasterizer can produce that.

**macOS default rasterizer:** `scripts/rasterize_svg.swift` (compiled on
demand with `swiftc`) rasterizes via WebKit because it mirrors the reference
renderer the fidelity gate was validated against. It is a proven choice, not
a dependency.

On other platforms, rasterize with your own tool into a folder as
`<stem>.png` (keep the size equal to the viewBox) and pass
`--fallback-dir`. Examples:

```bash
resvg -w 512 -h 768 sample/balloon-lineart.svg my-rasters/balloon-lineart.png
# or rsvg-convert -w 512 -h 768 ... -o my-rasters/balloon-lineart.png
# or inkscape --export-type=png --export-width=512 --export-height=768 ...
# or a headless-browser screenshot at the exact viewBox size
```

## Quickstart

```bash
mkdir -p out/pages
printf '{"pages": []}\n' > out/content-manifest.json
python3 scripts/onboard_page.py balloon-lineart --title "Party Balloon" \
    --svg-dir sample --pages-dir out/pages \
    --manifest out/content-manifest.json --category sample
```

The onboarding tool compiles the rasterizer on first use (into a local
`.regionmap-cache/bin`), rasterizes the SVG, builds
`out/pages/balloon-lineart-regions.png`, upserts the manifest entry with the
region count, and prints QA stats. Exit code is non-zero if the page's
region count is out of the design band (6-64) — bad pages fail loudly
instead of silently shipping uncolorable art.

No `swiftc` on your machine? Same command plus `--fallback-dir
my-rasters` (see Requirements): the tool skips the WebKit step with a
one-line note and uses your raster — or tells you plainly, with no stack
trace, when no raster is available.

Open the region-map PNG in any viewer and you'll see the trick: every
fillable area is a unique flat color, because the RGB channels *are* the
region ID.

## QA gates (why you can trust a page this tool accepts)

- **Band check**: region count must fall inside 6-64; the CLI exits 1
  otherwise.
- **Thresholds**: ink = gray < 128; enclosed white >= 200 px2 becomes a
  region; border-touching white (sky/ground) >= 5000 px2 becomes a fillable
  background — tiny slivers stay ID 0 like ink.
- **Stable IDs**: regions are numbered largest-first, so drafts survive
  re-onboarding when counts match; the runtime guard is manifest
  `regionCount` == decoded count, else stale drafts are refused, not
  corrupted.
- **Semantic vs byte parity**: WebKit anti-aliasing is not bit-deterministic
  across processes (on a real page ~414 of 1.57M pixels may land on the
  other side of the ink threshold between two runs). Region counts, probe
  IDs and band compliance are stable; raw PNG bytes are not. Assert
  semantics, not hashes.

## Verify it yourself (5 minutes)

1. Run the quickstart above; confirm `regionCount` in the manifest matches
   the printed stats and the PNG size equals the SVG viewBox size.
2. Bring one of your own closed-outline line-art SVGs: drop it in a folder
   and rerun with your stem. A page with hairline gaps between shapes will
   show up as a suspiciously low region count (one merged "room" of white) —
   that is the band gate doing its job.
3. Negative test: a single circle on white should exit non-zero (count out
   of band). The tool is telling you the truth about your art.

## License

MIT (see `LICENSE`) — covers this repository's code and documentation only.
No license is granted here to any artwork, coloring pages, or brand assets
of the app this engine was built for; the sample SVG in `sample/` was made
specifically for this repo and is included under the same MIT terms.
