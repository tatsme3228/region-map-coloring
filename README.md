# region-map-coloring

A build-time toolchain for the **region-map coloring engine** — the technique
that lets a children's coloring app answer "which area did the child tap?"
with one exact integer lookup, with no flood fill at runtime, ever.

The core idea: keep the **original SVG as the immutable visual authority**
(displayed, never converted), and derive from it a **lossless region-ID
raster** at build time (`id = R*65536 + G*256 + B` in an RGB PNG). At runtime
you decode that PNG once, and every tap resolves in O(1) by reading one
pixel. Region labeling uses a **run-length two-pass union-find** instead of
per-pixel BFS — it labels a 1024x1536 page in ~0.1-0.2 s (roughly 100x
faster on the machine this was developed on; timings are indicative, not
benchmarks).

Everything is local: Python 3 + Pillow, and one Swift file that uses macOS
WebKit to rasterize the SVG pixel-faithfully. No API keys, no network, no
paid services.

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

- macOS (the rasterizer shells out to WebKit/AppKit via `swiftc`)
- Python 3 with Pillow (`pip3 install pillow`) — nothing else

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
