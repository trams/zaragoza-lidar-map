# Zaragoza LiDAR height map

An interactive map of Zaragoza coloured by **height above ground** — buildings
and tree canopy, from Spanish PNOA-LiDAR — with a sightline tool for the total
solar eclipse of **12 August 2026**, when the sun sits at 6° altitude and 285°
azimuth and the horizon is decided by buildings and street trees rather than
terrain.

**Live: https://trams.github.io/zaragoza-lidar-map/**

Click anywhere on the map and it ray-casts toward the sun, reporting the horizon
angle, whether the sun clears it, the limiting obstruction, a cross-section of
the sightline, and how the horizon changes across ±10° of azimuth. Azimuth,
altitude, eye height and range are all editable, so the same map works for any
other low-sun event.

Layers: height above ground (buildings warm, canopy green, over a terrain
hillshade), terrain relief, and buildings / vegetation on their own. An OSM base
layer is available for orientation.

## Rebuilding

```
./pnoa_render.py fetch    # 14.8 x 13.8 km window -> zaragoza_pnoa/  (~5 min)
./pnoa_render.py tiles    # XYZ PNG tiles z12-z16 -> site/tiles/     (~20 min)
./pnoa_render.py blob     # surface model         -> site/data/
./pnoa_render.py serve    # http://localhost:8765
```

Requires `numpy`, `rasterio`, `pyproj`, `requests`, `Pillow`. The rendered site
under `site/` is committed so Pages can serve it; the source rasters are not,
since `fetch` re-downloads them.

See [architecture.md](architecture.md) for how the pieces fit together and why.

## Data

Open WCS, no registration, CC BY 4.0 — attribution to Instituto Geográfico
Nacional required:

| layer | endpoint | coverage | res |
|---|---|---|---|
| terrain (bare earth) | `servicios.idee.es/wcs-inspire/mdt` | `Elevacion25830_5` | 5 m |
| building height AGL | `wcs-mds.idee.es/mds` | `mdsn_e025` | 2.5 m |
| vegetation height AGL | `wcs-mds.idee.es/mds` | `mdsn_v025` | 2.5 m |

Caveats worth knowing before you trust a number: heights are quantised to whole
metres; the normalised models derive from the 2015–2021 LiDAR coverage, so
recent buildings may be missing and trees have grown since. Treat a margin under
about 1° as inconclusive, and go stand there.

## Licence

Code MIT. Elevation data © Instituto Geográfico Nacional (PNOA LiDAR), CC BY 4.0.
