# Architecture

Zaragoza PNOA-LiDAR height-above-ground explorer.

Two stages with a hard boundary between them: a **Python build pipeline** that
turns raw LiDAR into static assets, and a **static browser client** that does
all interaction. Nothing dynamic runs at request time — `serve` is a plain file
server, so the whole `site/` directory can go on any static host unchanged.

```
IGN WCS ──fetch──> zaragoza_pnoa/*.tif ──┬──tiles──> site/tiles/  (pictures, for looking)
                    (source of truth)     └──blob───> site/data/   (numbers, for computing)
                                                          │
                                                     browser: Leaflet + ray-caster
```

## Stage 1 — `pnoa_render.py`

Four phases, each a subcommand, each idempotent and independently re-runnable:

- **`fetch`** (`pnoa_render.py:69`) — pulls a 14.8 × 13.8 km window from two WCS
  endpoints in 2–4 km chunks and mosaics them into three GeoTIFFs in EPSG:25830.
  This is the only network step; everything downstream is offline. The per-layer
  axis-order quirk (`mdsn_*` advertise `y x`) is encoded in the `LAYERS` table
  rather than handled at the call site.
- **`load_utm`** (`:104`) — the shared reader. Upsamples the 5 m terrain to the
  2.5 m object grid so the render path has one grid to think about.
- **`tiles`** (`:229`) — composes four RGBA images in UTM (`render_layers`,
  `:167`), then does **one** warp per layer into a Web-Mercator mosaic snapped to
  a z16 tile boundary, and slices tiles out by array indexing. Lower zooms come
  from repeated 2× alpha-weighted box downsampling (`downsample2`, `:307`).
  Warping per tile instead would re-read a 33 Mpx source several thousand times;
  snapping the mosaic to a multiple of 2^(ZMAX−ZMIN) makes every zoom level
  pixel-aligned by construction rather than by resampling.
- **`blob`** (`:341`) — exports the same rasters again, this time as data rather
  than pictures.

## The deliberate split: tiles vs. blob

The same source rasters ship **twice**, in two representations, because they
answer different questions.

Tiles are for looking: colour is baked in at build time, resolution is whatever
the zoom needs, and the browser never sees a height value. The blob is for
computing: `objects.png` carries building height in R and canopy height in G at
native 2.5 m, `terrain.png` is 5 m greyscale offset by 150 m. PNG is doing
double duty as a compression format for numeric data — 92% of the city is open
ground, so the filters take a 5920 × 5520 window to 7.4 MB. The client decodes
it through a canvas into flat `Uint8Array`s (`site/app.js:66`).

This is why the map and the analysis can't disagree: they're the same bytes,
rendered twice.

## Why the ray-casting is client-side

The alternative was precomputing a horizon raster server-side and shipping it as
another tile layer. But there are four free parameters — azimuth, sun altitude,
eye height, range — and precomputing means a 4-D grid or a frozen answer.
Shipping 8 MB of surface model instead makes every parameter live, and a 2500 m
cast at 2.5 m steps × 3 azimuths across the solar disc is a few milliseconds.
The ±10° sweep chart is 41 of those and still redraws instantly.

## Coordinate systems

Three, and the seams are where bugs live:

- **EPSG:25830** — the data, and where all geometry and ray-casting happens.
- **EPSG:3857** — tiles and display only.
- **EPSG:4326** — the UI boundary (clicks in, coordinates out).

`site/app.js` carries its own Snyder forward/inverse UTM implementation (`:20`,
`:33`) rather than a projection library — it's 30 lines and agrees with pyproj to
0.2 mm. Separately, **grid convergence** (`:54`) is a physical correction, not a
projection detail: it's +1.4° here, and the whole exercise has a ±1° tolerance,
so "285° true" is 283.6° on the grid.

## Sampling contract

`sample()` (`site/app.js:95`) reads two grids at different pitches without
resampling them together, and **returns `null` outside the window rather than
clamping** — clamping to the edge pixel silently manufactures a clear horizon for
any ray that leaves the data, which is exactly the failure mode that looks like a
great observing spot. The truncation flag propagates up to a warning row in the
readout.

Two constants encode measured findings rather than preference: `STEP = 2.5`
(native pitch — decimating to 5 m cost ~1.2° mean error, p90 ~2.5°, whichever way
the cells were pooled) and `D0 = 10` (starting at 5 m lets the observer's own
cell dominate).

## Client structure

`site/app.js` is flat and dependency-free apart from vendored Leaflet —
projection → surface model → ray-caster → map → readout → charts, in that order,
no framework. State is two variables: `S` (the surface model) and `last` (the
clicked point, so parameter edits re-run without a re-click). The charts are
hand-drawn canvas; the profile plots curvature-corrected heights specifically so
the eye ray is a straight line and you can read the clearance geometrically.
