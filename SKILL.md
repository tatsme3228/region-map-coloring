---
name: region-map-coloring
description: Implements the region-map coloring engine for children's coloring apps: original SVG as immutable visual authority, lossless region-ID PNG as sole coloring geometry, exact integer tap lookup, fillable scene backgrounds, and one-command SVG onboarding (WebKit rasterize + run-length union-find, ~2 s per page). Use when building or porting a coloring app, importing SVG coloring pages, generating region maps, or when the user mentions coloring pages, fillable regions, bucket fill, or SVG onboarding. Expects closed-outline line-art SVGs as input (bring your own or generate separately).
---

# Region-Map Coloring Engine (Phase 2)

## Core principles

- VISIBLE ARTWORK and COLORING GEOMETRY are two different things.
  - Display: always the ORIGINAL SVG, rendered directly by a proven-faithful
    renderer (PocketSVG in the reference app). Never converted, never
    rasterized for display.
  - Geometry: an invisible lossless region-ID raster enabling exact pixel tap
    lookup. Produced at build time only.
- Encoding: `id = R*65536 + G*256 + B` in a lossless RGB PNG (no JPEG, no
  color management, no resampling). Fillable index = id - 1.
- Region 0 = ink + rejected slivers: taps there return nil.
- Sampling: exact integer pixels only; map touch coordinates back into map
  space first; never interpolate the map.
- Fills composite UNDER the opaque SVG line art (multiply over white), so
  slight overlap beneath strokes hides seams.
- Raster source for the map: derived FROM the SVG via WebKit rasterization
  (scripts/rasterize_svg.swift — same engine as the fidelity gate reference),
  so geometry aligns pixel-for-pixel with the line art. The SVG folder is the
  single source of truth.

## Why this wins (measured on the reference app)

- vs contour-reconstruction engines: nothing is rebuilt, so solid black eyes
  stay solid, thin strokes survive; taps are deterministic integer lookups.
- vs per-pixel BFS labeling: run-length two-pass union-find labels a
  1024x1536 page in 0.1-0.2 s (~100x faster), pure Python + Pillow.
- vs ad-hoc rasters: WebKit CLI rasterizes the SVG in ~1.2 s (cached); 3 pages
  onboarded in 2.2 s total with one command each.
- The pixel-diff fidelity gate validates the renderer ONCE (per renderer),
  not per page; per-page checks are band + map/manifest consistency.

## Onboarding workflow

```bash
python3 scripts/onboard_page.py <stem> --title "Display Title" \
    --svg-dir <dir-with-svgs> --pages-dir <app-pages-dir> \
    --manifest <ContentManifest.json> [--category animals] \
    [--cache-dir DIR] [--fallback-dir DIR]
```

Steps (all automated): ensure compiled rasterizer (`<cache-dir>/bin`,
swiftc if stale) -> WebKit-rasterize the SVG (cached, refreshed when the SVG
changes) -> copy SVG into pages dir -> build `<stem>-regions.png` via
`make_region_map.py` -> upsert manifest entry
(`id/category/svgFile/thumbnail/title/regionMap/regionCount`) -> print QA
stats -> exit 1 when out of band.

## Thresholds (proven defaults)

| Knob | Default | Meaning |
|---|---|---|
| INK_THRESHOLD | 128 | gray below = ink (ID 0) |
| MIN_AREA | 200 | enclosed white below stays 0 |
| BG_MIN_AREA | 5000 | border-touching white at/above = fillable background (sky/ground); below stays 0 (slivers) |
| BAND | 6-64 | expected region count; enforced by tool + tests |

IDs are assigned stable largest-first across enclosed + background groups, so
drafts survive re-onboarding only when counts match (runtime guard:
manifest `regionCount` must equal decoded map count, else the page refuses to
load stale drafts).

## Runtime integration checklist

See [references/ENGINE-BLUEPRINT.md](references/ENGINE-BLUEPRINT.md) for the
reference implementation map, manifest schema, and test templates. Summary:

- Loader decodes the PNG to `[UInt32]` ids once, off-main; `regionIndex(at:)`
  is an exact integer sample returning nil outside/ID 0.
- Canvas stack (bottom->top): white canvas, fill composite (multiply),
  original SVG overlay; debug modes: SVG only / map visualized / fills only /
  composite / tap+ID.
- Tap -> map coordinates through ONE coordinate mapper (aspect-fit aware).
- Session state: `regionIndex -> color` dict; undo/redo snapshots of that
  dict; reset clears; persistence keyed by pageID + expectedRegionCount.
- Fill bitmap rebuilt async only when fills change; cached per page.

## QA gate (every onboarding / engine change)

1. Onboard prints in-band counts; sanity ink diff WebKit-vs-clean <= ~0.02
   when a fallback raster exists (informational).
2. Unit suite green, including: map decodes at authored size; band; border
   rule (fillable-or-0; consistent sky top row / ground bottom row); known
   interior probes resolve to distinct indices; ink + out-of-bounds nil;
   data-driven test that EVERY manifest regionMap page decodes and matches
   its published regionCount.
3. Snapshot smoke tests write /tmp/qa_canvas_<stem>.png for eyeball check
   (line art intact, solid black elements solid).
4. Install into a booted simulator for a human trial.

## Pitfalls

- `drawHierarchy(afterScreenUpdates:)` inside a SwiftUI body causes
  AttributeGraph "setting value during update" SIGABRT — render snapshots
  with `view.layer.render(in: ctx.cgContext)` instead.
- macOS WebKit CLI sandboxes `loadFileURL` for plain binaries — inline the
  SVG text into HTML and use `loadHTMLString`, pinning the root `<svg>` to
  its viewBox px size via CSS.
- `takeSnapshot`/lockFocus resampling re-renders at display scale — resample
  2x->1x into an explicit-pixel `NSBitmapImageRep`.
- Never JPEG/interpolate/color-manage the map; nearest-neighbor only.
- Count fillable backgrounds in the band: pages with few enclosed regions gain
  sky/ground here, so a tight enclosed-only band upstream can still pass here.
