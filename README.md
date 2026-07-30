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

### Vintage

Both the WCS capabilities and the [INSPIRE catalogue
record](https://www.idee.es/csw-inspire-idee/srv/spa/csw?Service=CSW&Request=GetRecordById&Version=2.0.2&outputSchema=http://www.isotc211.org/2005/gmd&elementSetName=full&id=spaignwcs_MDS)
state the surface models are `generados a partir del MDT-LIDAR 1ª cobertura`.
Cross-referencing the first-coverage flight-line shapefile for Aragón Norte
against this window, **every tile here was flown on one of two days: 21 January
2011 south of ~4614000 N, 23 January 2011 north of it**, with a narrow overlap
band between. (Zaragoza's second-coverage flight was 15 October 2016, but that
is not what these services serve.)

That date is the single biggest caveat in this tool, in three compounding ways,
all pointing the same direction:

- **Leaf-off.** A January flight sees deciduous street trees bare. Canopy
  heights from a leaf-off pass at 0.5 pts/m² tend to *under*-read the crown,
  and the model here treats vegetation as opaque regardless.
- **15 years of growth** between the flight and the August 2026 eclipse.
- **New construction** since 2011 is simply absent.

So the horizons this tool reports are **optimistic** — reality will be somewhat
worse, not better. Heights are also quantised to whole metres. Treat a margin
under about 1° as inconclusive, and go stand there.

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
