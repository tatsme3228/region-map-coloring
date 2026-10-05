# Engine Blueprint (reference implementation map)

Distilled from a shipping SwiftUI/iOS children's coloring app.
Adapt names to the target project; keep the responsibilities.

## File-role map

| Component | Responsibility |
|---|---|
| ArtworkImageService | Renders the ORIGINAL SVG for display (PocketSVG direct render); offscreen snapshots via `view.layer.render(in:)` (NEVER `drawHierarchy(afterScreenUpdates:)` inside SwiftUI body — SIGABRT); branch preference: region-map pages use the SVG overlay, legacy pages may use PNG |
| RegionMapLoader | Decodes `<stem>-regions.png` losslessly to `ids: [UInt32]` + `regionCount = maxID`; `regionIndex(atMapX:mapY:)` exact integer sample, nil outside or ID 0 |
| RegionFillRenderer | Builds the user-color bitmap from `regionIndex -> color` fills (async, only when fills change); fills multiply-composited over white UNDER the SVG |
| ColoringCanvasView | Dual stack: legacy vector-region stack OR region-map stack (`regionMapPage != nil`); ONE coordinate mapper (aspect-fit aware) for tap -> map coords; debug modes (SVG only / map visualized / fills only / composite / tap+ID) |
| ColoringSessionModel | `fills: [Int: Color]`-style state; undo/redo snapshots (cap ~50); reset undoable; persistence keyed by pageID; restore rejects mismatched `expectedRegionCount` and clears history (auto-discards stale drafts after re-onboarding) |
| ContentManifest / PageManifest | Page entries; `regionMap` + `regionCount` presence selects the region-map stack; count mismatch at load = graceful refusal, not a crash |

## Manifest schema (per page entry)

```json
{
  "id": "sample_balloon_lineart",
  "category": "sample",
  "svgFile": "balloon-lineart",
  "thumbnail": null,
  "title": "Party Balloon",
  "regionMap": "balloon-lineart-regions",
  "regionCount": 11
}
```

Assets per page: `Resources/Pages/<stem>.svg` (visual authority) +
`Resources/Pages/<stem>-regions.png` (geometry). Synchronized asset groups
mean no project-file edits when adding pages.

## Test templates

RegionMap contract (per pilot page, constants derived from the generated map):

- decodes at authored size (1024x1536) and count inside band 6-64;
- border rule: border pixels fillable-or-0; whole top row one sky ID, whole
  bottom row one ground ID, sides within {0, sky, ground}; corner tap = sky
  index 0 (not nil);
- known interior probes (region centroids from the build tool) resolve to
  distinct indices (`index = id - 1`);
- out-of-bounds and a known ink pixel return nil;
- manifest entry agrees with the bundled map (`regionMap`, `regionCount`).

Data-driven (covers every onboarding automatically):

- for EVERY manifest entry with `regionMap`: decode, assert authored size,
  assert `regionCount` equals decoded count and lies in band.

RenderSmoke snapshots:

- host the real canvas view in a shared UIWindow, pump the run loop ~3 s,
  snapshot to `/tmp/qa_canvas_<stem>.png`; assertions only guard non-empty
  PNG; humans eyeball line-art fidelity.

## Fidelity gate (per renderer, once)

- Reference: offscreen WKWebView renders the ORIGINAL SVG at the viewBox size
  (same WebKit engine as `rasterize_svg.swift`).
- Candidate: the app renderer's offscreen snapshot (`layer.render`).
- Compare: binarized ink mask pixel-diff; accept when worst channel delta is
  small (reference app passed with worst delta 8/255-scale units).
- Rerun only when the RENDERER changes — not per onboarded page.

## Porting order for a new app

1. Copy assets + manifest schema; wire `RegionMapLoader` (exact sampling).
2. Canvas stack + coordinate mapper + debug modes.
3. Session model (undo/redo/reset/persistence with count guard).
4. Tests from the templates above; snapshot smoke per page.
5. Fidelity gate once for the chosen SVG renderer.
6. Onboard pages with `onboard_page.py`.
