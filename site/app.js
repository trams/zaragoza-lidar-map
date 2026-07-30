/* Zaragoza PNOA-LiDAR height explorer.
 *
 * Tiles are pre-rendered by pnoa_render.py. The sightline tool ray-casts in
 * the browser against the surface model in site/data/, which carries object
 * heights at their native 2.5 m and terrain at 5 m.
 */

// --- ETRS89 <-> UTM zone 30N (Snyder), the CRS the rasters live in --------
const A = 6378137.0, F = 1 / 298.257222101;
const E2 = F * (2 - F), EP2 = E2 / (1 - E2), K0 = 0.9996;
const LON0 = -3 * Math.PI / 180, FE = 500000;
const D2R = Math.PI / 180, R2D = 180 / Math.PI;

function meridian(phi) {
  return A * ((1 - E2 / 4 - 3 * E2 * E2 / 64 - 5 * E2 ** 3 / 256) * phi
    - (3 * E2 / 8 + 3 * E2 * E2 / 32 + 45 * E2 ** 3 / 1024) * Math.sin(2 * phi)
    + (15 * E2 * E2 / 256 + 45 * E2 ** 3 / 1024) * Math.sin(4 * phi)
    - (35 * E2 ** 3 / 3072) * Math.sin(6 * phi));
}

function toUTM(lat, lon) {
  const phi = lat * D2R, lam = lon * D2R;
  const N = A / Math.sqrt(1 - E2 * Math.sin(phi) ** 2);
  const T = Math.tan(phi) ** 2, C = EP2 * Math.cos(phi) ** 2;
  const a = (lam - LON0) * Math.cos(phi), a2 = a * a;
  const x = FE + K0 * N * (a + (1 - T + C) * a2 * a / 6
    + (5 - 18 * T + T * T + 72 * C - 58 * EP2) * a2 * a2 * a / 120);
  const y = K0 * (meridian(phi) + N * Math.tan(phi) * (a2 / 2
    + (5 - T + 9 * C + 4 * C * C) * a2 * a2 / 24
    + (61 - 58 * T + T * T + 600 * C - 330 * EP2) * a2 * a2 * a2 / 720));
  return [x, y];
}

function fromUTM(x, y) {
  const m = y / K0, e1 = (1 - Math.sqrt(1 - E2)) / (1 + Math.sqrt(1 - E2));
  const mu = m / (A * (1 - E2 / 4 - 3 * E2 * E2 / 64 - 5 * E2 ** 3 / 256));
  const p = mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * Math.sin(2 * mu)
    + (21 * e1 * e1 / 16 - 55 * e1 ** 4 / 32) * Math.sin(4 * mu)
    + (151 * e1 ** 3 / 96) * Math.sin(6 * mu);
  const C = EP2 * Math.cos(p) ** 2, T = Math.tan(p) ** 2;
  const N = A / Math.sqrt(1 - E2 * Math.sin(p) ** 2);
  const R = A * (1 - E2) / (1 - E2 * Math.sin(p) ** 2) ** 1.5;
  const d = (x - FE) / (N * K0), d2 = d * d;
  const lat = p - (N * Math.tan(p) / R) * (d2 / 2
    - (5 + 3 * T + 10 * C - 4 * C * C - 9 * EP2) * d2 * d2 / 24
    + (61 + 90 * T + 298 * C + 45 * T * T - 252 * EP2 - 3 * C * C) * d2 ** 3 / 720);
  const lon = LON0 + (d - (1 + 2 * T + C) * d2 * d / 6
    + (5 - 2 * C + 28 * T - 3 * C * C + 8 * EP2 + 24 * T * T) * d2 * d2 * d / 120)
    / Math.cos(p);
  return [lat * R2D, lon * R2D];
}

/* Grid north is not true north: at Zaragoza the convergence is about +1.4 deg,
 * which is larger than the tolerance this whole exercise cares about. */
function convergence(lat, lon) {
  return Math.atan(Math.tan((lon + 3) * D2R) * Math.sin(lat * D2R)) * R2D;
}

// --- surface model -------------------------------------------------------
const R_EFF = 6371000 / (1 - 0.13);      // inflated for standard refraction
const SUN_SEMI = 0.26;                   // solar semi-diameter, degrees
const STEP = 2.5;                        // ray step, the native raster pitch
const D0 = 10;                           // ignore the first few metres
let S = null;                            // {meta, ter, bld, veg}

/* Decode a PNG into a plain byte array, one entry per pixel per channel. */
async function decode(url, channels) {
  const img = new Image();
  img.src = url;
  await img.decode();
  const cv = document.createElement('canvas');
  cv.width = img.width; cv.height = img.height;
  const cx = cv.getContext('2d', { willReadFrequently: false });
  cx.drawImage(img, 0, 0);
  const d = cx.getImageData(0, 0, img.width, img.height).data;
  const n = img.width * img.height;
  const out = channels.map(() => new Uint8Array(n));
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < channels.length; k++) out[k][i] = d[i * 4 + channels[k]];
  }
  return out;
}

async function loadSurface() {
  const meta = await (await fetch('data/surface.json')).json();
  const [[bld, veg], [ter]] = await Promise.all([
    decode('data/objects.png', [0, 1]),
    decode('data/terrain.png', [0]),
  ]);
  S = { meta, ter, bld, veg };
}

/* Nearest-neighbour sample. Returns null outside the window rather than
 * clamping to the edge, which would manufacture a clear horizon.
 * Objects and terrain sit on different grids (2.5 m and 5 m). */
function sample(x, y) {
  const m = S.meta, o = m.objects, t = m.terrain;
  const c = Math.round((x - m.originX) / o.res);
  const r = Math.round((m.originY - y) / o.res);
  if (c < 0 || r < 0 || c >= o.width || r >= o.height) return null;
  const i = r * o.width + c;
  const tc = Math.min(t.width - 1, Math.round((x - m.originX) / t.res));
  const tr = Math.min(t.height - 1, Math.round((m.originY - y) / t.res));
  const b = S.bld[i], v = S.veg[i];
  return {
    terrain: S.ter[tr * t.width + tc] + m.terrainOffset,
    building: b, vegetation: v,
    object: Math.max(b, v),
    kind: b >= v ? (b >= 1 ? 'building' : 'ground') : 'vegetation',
  };
}

/* Cast one ray. Returns the limiting elevation angle plus the samples the
 * profile chart draws. */
function cast(x, y, gridAz, eyeZ, range, keep, useVeg) {
  const s = Math.sin(gridAz * D2R), c = Math.cos(gridAz * D2R);
  let best = -90, bestD = 0, bestHit = null, truncated = false;
  const prof = keep ? [] : null;
  for (let d = D0; d <= range; d += STEP) {
    const p = sample(x + d * s, y + d * c);
    if (!p) { truncated = true; break; }
    const drop = d * d / (2 * R_EFF);
    const h = useVeg === false ? p.building : p.object;
    const ang = Math.atan2(p.terrain + h - eyeZ - drop, d) * R2D;
    if (ang > best) { best = ang; bestD = d; bestHit = p; }
    if (prof) prof.push({ d, drop, ...p });
  }
  return { angle: best, dist: bestD, hit: bestHit, truncated, prof };
}

/* Worst case across the solar disc: the sun is 0.52 deg wide, so an
 * obstruction just off-axis still eats part of it. */
function horizonAt(x, y, az, eyeZ, range, useVeg) {
  const conv = convergence(...fromUTM(x, y));
  let worst = null, prof = null;
  for (const off of [-SUN_SEMI, 0, SUN_SEMI]) {
    const r = cast(x, y, az + off - conv, eyeZ, range, off === 0, useVeg);
    if (off === 0) prof = r.prof;
    if (!worst || r.angle > worst.angle) worst = r;
  }
  return { ...worst, prof, conv };
}

// --- map -----------------------------------------------------------------
const CENTER = [41.6520, -0.8809];
const map = L.map('map', { center: CENTER, zoom: 14, zoomControl: true });

function layer(name, opts) {
  return L.tileLayer(`tiles/${name}/{z}/{x}/{y}.png`, Object.assign({
    minZoom: 11, maxZoom: 19, maxNativeZoom: 16, minNativeZoom: 12,
    tileSize: 256, attribution: 'PNOA LiDAR &copy; Instituto Geogr&aacute;fico Nacional',
  }, opts || {}));
}

const heightL = layer('height');
const terrainL = layer('terrain');
const buildingsL = layer('buildings');
const vegL = layer('vegetation');
const osm = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
});

heightL.addTo(map);
L.control.layers(
  { 'Height above ground': heightL, 'Terrain relief': terrainL, 'OSM (online)': osm },
  { 'Buildings only': buildingsL, 'Vegetation only': vegL },
  { collapsed: false }
).addTo(map);

L.Icon.Default.prototype.options.imagePath = 'vendor/images/';

let marker = null, rayLine = null, hitDot = null;

map.on('click', e => { if (S) run(e.latlng.lat, e.latlng.lng); });

// --- readout -------------------------------------------------------------
const $ = id => document.getElementById(id);
const num = id => parseFloat($(id).value);
let last = null;

function run(lat, lon) {
  last = [lat, lon];
  const [x, y] = toUTM(lat, lon);
  const here = sample(x, y);
  if (!here) { $('status').textContent = 'Outside the data window.'; return; }

  const az = num('az'), alt = num('alt'), range = num('range');
  const eyeZ = here.terrain + num('eye');
  const r = horizonAt(x, y, az, eyeZ, range);
  const bare = horizonAt(x, y, az, eyeZ, range, false);
  const margin = alt - r.angle;

  if (marker) map.removeLayer(marker);
  marker = L.marker([lat, lon]).addTo(map);
  const g = (az - r.conv) * D2R;
  const end = fromUTM(x + range * Math.sin(g), y + range * Math.cos(g));
  if (rayLine) map.removeLayer(rayLine);
  rayLine = L.polyline([[lat, lon], end], {
    color: margin > 0 ? '#f2a33c' : '#e06c6c', weight: 2, opacity: .9, dashArray: '6 5',
  }).addTo(map);
  if (hitDot) map.removeLayer(hitDot);
  if (r.dist) {
    const h = fromUTM(x + r.dist * Math.sin(g), y + r.dist * Math.cos(g));
    hitDot = L.circleMarker(h, { radius: 5, color: '#e06c6c', weight: 2, fill: false })
      .addTo(map);
  }

  $('status').hidden = true;
  $('result').hidden = false;
  $('horizon').textContent = `${r.angle.toFixed(2)}° horizon`;
  const m = $('margin');
  m.textContent = margin > 0 ? `sun clears it by ${margin.toFixed(2)}°`
    : `sun is blocked by ${(-margin).toFixed(2)}°`;
  m.className = margin > 0 ? 'ok' : 'no';

  const rows = [
    ['Position', `${lat.toFixed(5)}, ${lon.toFixed(5)}`],
    ['Ground elevation', `${here.terrain.toFixed(0)} m`],
    ['Over your head', here.object < 1 ? 'open sky'
      : `${here.object} m of ${here.kind}`],
    ['Limiting obstruction', !r.dist ? 'none'
      : r.hit.object < 1 ? `bare terrain @ ${r.dist} m`
        : `${r.hit.kind}, ${r.hit.object} m tall @ ${r.dist} m`],
    ['Ignoring vegetation', `${bare.angle.toFixed(2)}°`],
    ['Grid convergence', `${r.conv.toFixed(2)}° (grid az ${(az - r.conv).toFixed(1)}°)`],
  ];
  if (r.truncated) rows.push(['Warning', 'ray leaves the data window']);
  $('facts').innerHTML = rows
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');

  drawProfile(r, eyeZ, alt, range);
  drawSweep(x, y, az, alt, eyeZ, range);
}

// --- charts --------------------------------------------------------------
function axes(c, w, h, pad) {
  c.clearRect(0, 0, w, h);
  c.strokeStyle = '#2e3440'; c.lineWidth = 1;
  c.beginPath();
  c.moveTo(pad.l, pad.t); c.lineTo(pad.l, h - pad.b); c.lineTo(w - pad.r, h - pad.b);
  c.stroke();
  c.fillStyle = '#949cad'; c.font = '10px system-ui';
}

function drawProfile(r, eyeZ, alt, range) {
  const cv = $('profile'), c = cv.getContext('2d');
  const w = cv.width, h = cv.height, pad = { l: 42, r: 10, t: 12, b: 22 };
  axes(c, w, h, pad);
  const p = r.prof || [];
  if (!p.length) return;

  // curvature-corrected heights, so the eye ray plots as a straight line
  const tops = p.map(s => s.terrain + s.object - s.drop);
  const sunEnd = eyeZ + range * Math.tan(alt * D2R);
  const zmin = Math.min(eyeZ - 5, ...p.map(s => s.terrain - s.drop)) - 2;
  const zmax = Math.max(sunEnd, ...tops) + 5;
  const X = d => pad.l + (d / range) * (w - pad.l - pad.r);
  const Y = z => h - pad.b - ((z - zmin) / (zmax - zmin)) * (h - pad.t - pad.b);

  const band = (vals, fill) => {
    c.beginPath(); c.moveTo(X(p[0].d), Y(zmin));
    p.forEach((s, i) => c.lineTo(X(s.d), Y(vals[i])));
    c.lineTo(X(p[p.length - 1].d), Y(zmin)); c.closePath();
    c.fillStyle = fill; c.fill();
  };
  band(tops, '#3b4152');
  band(p.map(s => s.terrain - s.drop), '#5a6172');

  // buildings and canopy, coloured like the map
  p.forEach((s, i) => {
    if (s.object < 1) return;
    c.strokeStyle = s.kind === 'vegetation' ? '#7fbf4a' : '#e8944a';
    c.lineWidth = Math.max(1, (w - pad.l - pad.r) / p.length);
    c.beginPath();
    c.moveTo(X(s.d), Y(s.terrain - s.drop)); c.lineTo(X(s.d), Y(tops[i]));
    c.stroke();
  });

  // the sun's lower limb, and the limiting sightline
  c.setLineDash([5, 4]); c.lineWidth = 1.5; c.strokeStyle = '#f2a33c';
  c.beginPath(); c.moveTo(X(0), Y(eyeZ)); c.lineTo(X(range), Y(sunEnd)); c.stroke();
  c.strokeStyle = '#e06c6c';
  c.beginPath();
  c.moveTo(X(0), Y(eyeZ));
  c.lineTo(X(range), Y(eyeZ + range * Math.tan(r.angle * D2R)));
  c.stroke();
  c.setLineDash([]);

  c.fillStyle = '#949cad'; c.font = '10px system-ui';
  for (let d = 0; d <= range; d += 500) {
    c.fillText(`${d}`, X(d) - 8, h - pad.b + 12);
  }
  for (let k = 0; k < 4; k++) {
    const z = zmin + (zmax - zmin) * k / 3;
    c.fillText(`${z.toFixed(0)} m`, 4, Y(z) + 3);
  }
}

function drawSweep(x, y, az, alt, eyeZ, range) {
  const cv = $('sweep'), c = cv.getContext('2d');
  const w = cv.width, h = cv.height, pad = { l: 42, r: 10, t: 12, b: 22 };
  axes(c, w, h, pad);
  const pts = [];
  for (let a = az - 10; a <= az + 10.001; a += 0.5) {
    pts.push([a, horizonAt(x, y, a, eyeZ, range).angle]);
  }
  const amax = Math.max(alt * 1.5, ...pts.map(p => p[1])) + 1;
  const X = a => pad.l + ((a - az + 10) / 20) * (w - pad.l - pad.r);
  const Y = v => h - pad.b - (Math.max(v, 0) / amax) * (h - pad.t - pad.b);

  c.fillStyle = 'rgba(111,207,112,.14)';
  c.fillRect(pad.l, Y(alt), w - pad.l - pad.r, h - pad.b - Y(alt));
  c.strokeStyle = '#f2a33c'; c.setLineDash([5, 4]);
  c.beginPath(); c.moveTo(pad.l, Y(alt)); c.lineTo(w - pad.r, Y(alt)); c.stroke();
  c.setLineDash([]);

  c.strokeStyle = '#e6e9ef'; c.lineWidth = 1.5; c.beginPath();
  pts.forEach(([a, v], i) => (i ? c.lineTo(X(a), Y(v)) : c.moveTo(X(a), Y(v))));
  c.stroke();

  c.fillStyle = '#949cad'; c.font = '10px system-ui';
  for (let a = az - 10; a <= az + 10.001; a += 5) {
    c.fillText(`${a.toFixed(0)}°`, X(a) - 9, h - pad.b + 12);
  }
  c.fillText(`${alt.toFixed(0)}° sun`, 4, Y(alt) + 3);
  c.fillText('0', 4, h - pad.b + 3);
}

['az', 'alt', 'eye', 'range'].forEach(id =>
  $(id).addEventListener('change', () => last && run(...last)));

loadSurface().then(() => {
  $('status').textContent = 'Click anywhere on the map to cast a sightline.';
  fetch('tiles/meta.json').then(r => r.json()).then(m =>
    map.setMaxBounds(L.latLngBounds(m.bounds).pad(0.1))).catch(() => {});
}).catch(e => {
  $('status').textContent = 'Could not load the surface model: ' + e.message;
});
