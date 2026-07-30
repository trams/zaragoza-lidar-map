#!/usr/bin/env python3
"""
PNOA-LiDAR height-above-ground renderer for Zaragoza (context.md, Idea 3).

Builds a browsable web map coloured by height above ground: buildings and
canopy over a terrain hillshade, plus a client-side sightline tool for the
2026-08-12 eclipse (sun at 6 deg altitude, 285 deg azimuth).

Data sources (open WCS, no registration, CC-BY Instituto Geografico Nacional):
  https://servicios.idee.es/wcs-inspire/mdt   Elevacion25830_5  terrain, 5 m
  https://wcs-mds.idee.es/mds                 mdsn_e025  building height AGL, 2.5 m
  https://wcs-mds.idee.es/mds                 mdsn_v025  vegetation height AGL, 2.5 m

Usage:
  ./pnoa_render.py fetch          download the raster window into zaragoza_pnoa/
  ./pnoa_render.py tiles          render XYZ PNG tiles into site/tiles/
  ./pnoa_render.py blob           export the surface model the browser ray-casts
  ./pnoa_render.py serve          static server on :8765
"""
import argparse, json, math, os, sys
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from rasterio.crs import CRS
import requests
from pyproj import Transformer

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "zaragoza_pnoa")
SITE = os.path.join(HERE, "site")

UTM = "EPSG:25830"                      # ETRS89 / UTM 30N
MERC = "EPSG:3857"
FWD = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)
INV = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)

# Window covering the Zaragoza urban area, snapped to 100 m.
WINDOW = (670000, 4607400, 684800, 4621200)     # x0, y0, x1, y1  (14.8 x 13.8 km)

LAYERS = {
    # name: (endpoint, coverageId, subset axis order, native resolution)
    # Axis order differs per layer: mds05/mdt are x-y, the mdsn_* normalised
    # models advertise EPSG:3042 with axisLabels "y x". Getting it wrong
    # silently returns a different window rather than an error.
    "mdt": ("https://servicios.idee.es/wcs-inspire/mdt", "Elevacion25830_5", "xy", 5.0),
    "bld": ("https://wcs-mds.idee.es/mds", "mdsn_e025", "yx", 2.5),
    "veg": ("https://wcs-mds.idee.es/mds", "mdsn_v025", "yx", 2.5),
}

ZMIN, ZMAX = 12, 16     # z16 is ~1.8 m/px at this latitude, just over native
TILE = 256


# --- fetching --------------------------------------------------------------
def wcs_get(layer, x0, y0, x1, y1):
    url, cov, order, _ = LAYERS[layer]
    sub = (f"subset=x({x0:.0f},{x1:.0f})&subset=y({y0:.0f},{y1:.0f})" if order == "xy"
           else f"subset=y({y0:.0f},{y1:.0f})&subset=x({x0:.0f},{x1:.0f})")
    q = (f"{url}?service=WCS&version=2.0.1&request=GetCoverage"
         f"&coverageId={cov}&format=image/tiff&{sub}")
    r = requests.get(q, timeout=600)
    r.raise_for_status()
    if r.content[:2] not in (b"II", b"MM"):
        raise RuntimeError(f"{layer}: server returned {r.content[:400]!r}")
    return r.content


def fetch(args):
    os.makedirs(RAW, exist_ok=True)
    x0, y0, x1, y1 = WINDOW
    print(f"window {x0},{y0} -> {x1},{y1}  ({(x1-x0)/1000:.1f} x {(y1-y0)/1000:.1f} km)")
    for layer, (_, _, _, res) in LAYERS.items():
        out = os.path.join(RAW, f"{layer}.tif")
        if os.path.exists(out) and not args.force:
            print(f"{out} exists, skipping")
            continue
        step = 4000.0 if res >= 5.0 else 2000.0
        nx, ny = int((x1 - x0) / res), int((y1 - y0) / res)
        mosaic = np.zeros((ny, nx), dtype="int16")
        tiles = [(tx, ty) for tx in np.arange(x0, x1, step)
                 for ty in np.arange(y0, y1, step)]
        for n, (tx, ty) in enumerate(tiles, 1):
            ex, ey = min(tx + step, x1), min(ty + step, y1)
            tmp = os.path.join(RAW, f".tile_{layer}.tif")
            with open(tmp, "wb") as f:
                f.write(wcs_get(layer, tx, ty, ex, ey))
            with rasterio.open(tmp) as s:
                a, b = s.read(1), s.bounds
                c0 = int(round((b.left - x0) / res))
                r0 = int(round((y1 - b.top) / res))
                mosaic[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = a
            os.remove(tmp)
            print(f"  {layer} {n}/{len(tiles)} {a.shape}", flush=True)
        with rasterio.open(out, "w", driver="GTiff", height=ny, width=nx, count=1,
                           dtype="int16", crs=UTM,
                           transform=from_origin(x0, y1, res, res),
                           compress="deflate", predictor=2) as d:
            d.write(mosaic, 1)
        print(f"wrote {out}  {mosaic.shape}  min={mosaic.min()} max={mosaic.max()}")


# --- shared raster loading -------------------------------------------------
def load_utm():
    """Terrain, building height and canopy height on the common 2.5 m grid."""
    out = {}
    for k in LAYERS:
        p = os.path.join(RAW, f"{k}.tif")
        if not os.path.exists(p):
            sys.exit(f"missing {p} - run 'fetch' first")
        with rasterio.open(p) as s:
            out[k] = (s.read(1).astype("float32"), s.transform, s.shape)
    fine = out["bld"][2]
    mdt = out["mdt"][0]
    # nearest-neighbour upsample of the 5 m terrain onto the 2.5 m grid
    mdt2 = np.repeat(np.repeat(mdt, 2, axis=0), 2, axis=1)[:fine[0], :fine[1]]
    bld = np.clip(out["bld"][0], 0, None)
    veg = np.clip(out["veg"][0], 0, None)
    return mdt2, bld, veg, out["bld"][1]


# --- colour ----------------------------------------------------------------
def ramp(stops):
    """Build a 256-entry RGB lookup table from (position, #rrggbb) stops."""
    pos = np.array([p for p, _ in stops], dtype="float64")
    cols = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in stops],
                    dtype="float64")
    t = np.linspace(0, 1, 256)
    return np.stack([np.interp(t, pos, cols[:, i]) for i in range(3)], 1).astype("uint8")

# Heights are quantised to whole metres by the source, so the ramps are keyed
# to storey counts rather than a smooth continuum.
BLD_RAMP = ramp([(0.00, "#4a2b2b"), (0.20, "#8f4436"), (0.40, "#cc6b3a"),
                 (0.60, "#eda352"), (0.80, "#f7d773"), (1.00, "#fff6cf")])
VEG_RAMP = ramp([(0.00, "#10300f"), (0.30, "#2f6b26"), (0.60, "#7fbf4a"),
                 (0.85, "#d3ea7a"), (1.00, "#f6ffd9")])
TER_RAMP = ramp([(0.00, "#2c4a63"), (0.25, "#5f7d6a"), (0.50, "#a09a6a"),
                 (0.75, "#c9a983"), (1.00, "#f4ece0")])
OBJ_MAX = 35.0      # metres; above this everything saturates


def smooth(a, k=3):
    """Cheap separable box blur. The source is quantised to whole metres, so
    hillshading it raw produces contour terracing rather than relief."""
    p = k // 2
    out = a.astype("float32")
    for axis in (0, 1):
        pad = np.pad(out, [(p, p) if i == axis else (0, 0) for i in (0, 1)], "edge")
        c = np.cumsum(pad, axis=axis)
        c = np.concatenate([np.zeros_like(np.take(c, [0], axis)), c], axis=axis)
        lo = np.take(c, range(0, out.shape[axis]), axis)
        hi = np.take(c, range(k, out.shape[axis] + k), axis)
        out = (hi - lo) / k
    return out


def hillshade(z, res, az=315.0, alt=45.0, zf=2.5):
    gy, gx = np.gradient(z * zf, res)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    a, e = math.radians(az), math.radians(alt)
    v = (math.sin(e) * np.cos(slope) +
         math.cos(e) * np.sin(slope) * np.cos(a - aspect))
    return np.clip(v, 0, 1)


def render_layers():
    """Compose the RGBA images that get sliced into tiles, in UTM space."""
    mdt, bld, veg, tf = load_utm()
    obj = np.maximum(bld, veg)
    sm = smooth(mdt, 5)
    shade = hillshade(sm, 2.5)

    valid = mdt > 0
    lo, hi = np.percentile(mdt[valid], [1, 99])
    ter8 = (np.clip((sm - lo) / max(hi - lo, 1), 0, 1) * 255).astype("uint8")

    def shaded(rgb, s, lo=0.35, hi=1.25):
        f = (lo + (hi - lo) * s)[..., None]
        return np.clip(rgb.astype("float32") * f, 0, 255).astype("uint8")

    imgs = {}

    # 1. combined height above ground: buildings warm, vegetation green,
    #    open ground carrying the terrain relief underneath
    i8 = (np.clip(obj / OBJ_MAX, 0, 1) * 255).astype("uint8")
    rgb = np.where((veg > bld)[..., None], VEG_RAMP[i8], BLD_RAMP[i8])
    base = shaded(TER_RAMP[ter8] * 0.30 + 18, shade, 0.5, 1.15)   # muted, so
    rgb = np.where((obj < 1.0)[..., None], base,                  # objects pop
                   shaded(rgb, shade, 0.6, 1.15))
    a = np.where(valid, 255, 0).astype("uint8")
    imgs["height"] = np.dstack([rgb, a])

    # 2. buildings only
    i8 = (np.clip(bld / OBJ_MAX, 0, 1) * 255).astype("uint8")
    rgb = shaded(BLD_RAMP[i8], shade, 0.6, 1.15)
    a = np.where(bld >= 1.0, 255, 0).astype("uint8")
    imgs["buildings"] = np.dstack([rgb, a])

    # 3. vegetation only
    i8 = (np.clip(veg / OBJ_MAX, 0, 1) * 255).astype("uint8")
    rgb = shaded(VEG_RAMP[i8], shade, 0.6, 1.15)
    imgs["vegetation"] = np.dstack([rgb, np.where(veg >= 1.0, 255, 0).astype("uint8")])

    # 4. terrain relief - the 40 m of relief the "flat city" premise misses
    rgb = shaded(TER_RAMP[ter8], shade, 0.45, 1.3)
    imgs["terrain"] = np.dstack([rgb, np.where(valid, 255, 0).astype("uint8")])

    return imgs, tf


# --- tiling ----------------------------------------------------------------
def merc_bounds(x, y, z):
    n = 2 ** z
    R = 20037508.342789244
    return (-R + 2 * R * x / n, R - 2 * R * (y + 1) / n,
            -R + 2 * R * (x + 1) / n, R - 2 * R * y / n)


def lonlat_to_tile(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    s = math.radians(lat)
    y = (1 - math.log(math.tan(s) + 1 / math.cos(s)) / math.pi) / 2 * n
    return int(x), int(y)


def tiles(args):
    """Reproject each rendered image once at the top zoom, then slice.

    Warping per tile would re-read the whole 33 Mpx source thousands of times;
    one warp into a tile-aligned mosaic plus 2x box-downsampling is minutes
    instead of hours, and it makes the zoom levels pixel-aligned by
    construction.
    """
    from PIL import Image
    imgs, tf = render_layers()
    x0, y0, x1, y1 = WINDOW
    (lon0, lat0), (lon1, lat1) = INV.transform(x0, y0), INV.transform(x1, y1)

    src_crs = CRS.from_string(UTM)
    dst_crs = CRS.from_string(MERC)

    # snap the mosaic to a tile boundary that survives every downsampling step
    span = 2 ** (ZMAX - ZMIN)
    tx0, ty1 = lonlat_to_tile(lon0, lat0, ZMAX)
    tx1, ty0 = lonlat_to_tile(lon1, lat1, ZMAX)
    tx0, ty0 = tx0 // span * span, ty0 // span * span
    tx1, ty1 = -(-(tx1 + 1) // span) * span - 1, -(-(ty1 + 1) // span) * span - 1
    nxt, nyt = tx1 - tx0 + 1, ty1 - ty0 + 1
    b0, b1 = merc_bounds(tx0, ty0, ZMAX), merc_bounds(tx1, ty1, ZMAX)
    px = (b0[2] - b0[0]) / TILE
    dtf = from_origin(b0[0], b0[3], px, px)
    print(f"mosaic {nxt}x{nyt} tiles at z{ZMAX} "
          f"({nxt*TILE}x{nyt*TILE} px, {px:.2f} m/px)")

    for name, img in imgs.items():
        mos = np.zeros((4, nyt * TILE, nxt * TILE), dtype="uint8")
        for band in range(4):
            reproject(img[:, :, band], mos[band],
                      src_transform=tf, src_crs=src_crs,
                      dst_transform=dtf, dst_crs=dst_crs,
                      resampling=Resampling.average)
        print(f"  {name}: warped", flush=True)

        total = 0
        for z in range(ZMAX, ZMIN - 1, -1):
            k = 2 ** (ZMAX - z)
            zx0, zy0 = tx0 // k, ty0 // k
            for iy in range(mos.shape[1] // TILE):
                for ix in range(mos.shape[2] // TILE):
                    t = mos[:, iy * TILE:(iy + 1) * TILE, ix * TILE:(ix + 1) * TILE]
                    if not t[3].any():
                        continue
                    d = os.path.join(SITE, "tiles", name, str(z), str(zx0 + ix))
                    os.makedirs(d, exist_ok=True)
                    save_png(t, os.path.join(d, f"{zy0 + iy}.png"))
                    total += 1
            print(f"  {name} z{z} ({total} tiles)", flush=True)
            if z > ZMIN:
                mos = downsample2(mos)
        print(f"{name}: {total} tiles")

    meta = {"bounds": [[lat0, lon0], [lat1, lon1]], "minzoom": ZMIN, "maxzoom": ZMAX,
            "objMax": OBJ_MAX}
    with open(os.path.join(SITE, "tiles", "meta.json"), "w") as f:
        json.dump(meta, f)


def save_png(t, path):
    """Palette-quantise before writing: hillshaded noise makes truecolour PNG
    tiles about three times larger for no visible gain."""
    from PIL import Image
    im = Image.fromarray(np.moveaxis(t, 0, -1), "RGBA")
    im.quantize(colors=255, method=Image.FASTOCTREE).save(path, optimize=True)


def downsample2(mos):
    """Alpha-weighted 2x box filter, so transparent pixels don't bleed in."""
    c, h, w = mos.shape
    q = mos[:, :h // 2 * 2, :w // 2 * 2].reshape(c, h // 2, 2, w // 2, 2)
    a = q[3].astype("float32")
    wsum = a.sum(axis=(1, 3))
    out = np.zeros((c, h // 2, w // 2), dtype="uint8")
    for band in range(3):
        v = (q[band].astype("float32") * a).sum(axis=(1, 3))
        out[band] = np.where(wsum > 0, v / np.maximum(wsum, 1), 0).round()
    out[3] = (wsum / 4).round()
    return out


# --- surface blob for the in-browser sightline tool ------------------------
TER_OFFSET = 150.0      # metres; terrain is stored as uint8 above this datum


def blob(args):
    """The surface model the browser ray-casts against, as two PNGs.

    Object heights stay at the native 2.5 m: decimating them to 5 m was tested
    against the full-resolution answer and cost ~1.2 deg mean error whichever
    way the cells were pooled, which is far too much when the whole question
    is a 6 deg threshold. PNG's filters exploit the 92% of the city that is
    open ground, so full resolution still fits in 8 MB.

    R = building height, G = vegetation height, both in whole metres.
    Terrain is natively 5 m and rides in its own greyscale PNG.
    """
    from PIL import Image
    mdt, bld, veg, _ = load_utm()
    os.makedirs(os.path.join(SITE, "data"), exist_ok=True)

    obj = np.dstack([np.clip(bld, 0, 255).astype("uint8"),
                     np.clip(veg, 0, 255).astype("uint8"),
                     np.zeros(bld.shape, "uint8")])
    po = os.path.join(SITE, "data", "objects.png")
    Image.fromarray(obj, "RGB").save(po, optimize=True)

    h, w = mdt.shape[0] // 2 * 2, mdt.shape[1] // 2 * 2
    ter = np.clip(np.rint(mdt[:h, :w].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))
                          - TER_OFFSET), 0, 255).astype("uint8")
    pt = os.path.join(SITE, "data", "terrain.png")
    Image.fromarray(ter, "L").save(pt, optimize=True)

    x0, y0, x1, y1 = WINDOW
    with open(os.path.join(SITE, "data", "surface.json"), "w") as f:
        json.dump({"originX": x0, "originY": y1, "terrainOffset": TER_OFFSET,
                   "objects": {"width": int(obj.shape[1]), "height": int(obj.shape[0]),
                               "res": 2.5},
                   "terrain": {"width": int(ter.shape[1]), "height": int(ter.shape[0]),
                               "res": 5.0}}, f)
    for p in (po, pt):
        print(f"wrote {p}  {os.path.getsize(p)/1e6:.1f} MB")


def serve(args):
    import http.server, socketserver, functools
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=SITE)
    with socketserver.TCPServer(("", args.port), h) as s:
        print(f"http://localhost:{args.port}/")
        s.serve_forever()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch"); f.add_argument("--force", action="store_true")
    f.set_defaults(fn=fetch)
    sub.add_parser("tiles").set_defaults(fn=tiles)
    sub.add_parser("blob").set_defaults(fn=blob)
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=serve)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
