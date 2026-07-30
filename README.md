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

Open WCS, no registration. Both services declare `AccessConstraints: CC BY 4.0
scne.es` in their `GetCapabilities`:

| layer | endpoint | coverage | res |
|---|---|---|---|
| terrain (bare earth) | `servicios.idee.es/wcs-inspire/mdt` | `Elevacion25830_5` | 5 m |
| building height AGL | `wcs-mds.idee.es/mds` | `mdsn_e025` | 2.5 m |
| vegetation height AGL | `wcs-mds.idee.es/mds` | `mdsn_v025` | 2.5 m |

Caveats worth knowing before you trust a number: heights are quantised to whole
metres, and the MDS service states its products are generated from the **first**
PNOA-LiDAR coverage (roughly 2009–2015), so buildings put up since are missing
and every tree has grown. Treat a margin under about 1° as inconclusive, and go
stand there.

## Licence and attribution

Three separate licences apply to different parts of this repository.

**Code** — `pnoa_render.py`, `site/app.js`, `site/style.css`, `site/index.html`
— is MIT, see [LICENSE](LICENSE).

**Elevation data** under `site/tiles/` and `site/data/` is derived from IGN
PNOA-LiDAR products, CC BY 4.0. Because it is mosaicked, reprojected and
recoloured rather than served as supplied, IGN's derived-work attribution
formula applies, and it must stay legible near the data:

> Obra derivada de MDT05 y MDS-LiDAR (PNOA), CC BY 4.0 scne.es

**Leaflet 1.9.4** under `site/vendor/` is BSD-2-Clause, © Volodymyr Agafonkin
and CloudMade — see [site/vendor/LICENSE-leaflet.txt](site/vendor/LICENSE-leaflet.txt).

The optional OSM base layer displays tiles from `tile.openstreetmap.org`: data
© OpenStreetMap contributors, available under the
[ODbL](https://opendatacommons.org/licenses/odbl/). No OSM-derived data is
redistributed here — the layer is off by default and fetches tiles only when
selected, which keeps it inside the
[OSMF tile usage policy](https://operations.osmfoundation.org/policies/tiles/).
