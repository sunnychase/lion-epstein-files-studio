// globe.js — the studio's globe on CesiumJS (vendored, no Cesium ion): Blue Marble base (NASA GIBS), Sentinel-2 cloudless imagery
// from level 6 (EOX), optional terrain (AWS terrain tiles), sun lighting and atmosphere. The data on it: every located place, airport
// and country in the page set, sized by the pages that mention it; arcs between located things that share a page (gold = a flight
// leg between airports); white dots for picture pages. Click a dot or an arc for the people and pages behind it.
'use strict';
const EOX_YEAR = 2025;
const EOX_URL = `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-${EOX_YEAR}/default/WGS84/{z}/{y}/{x}.jpg`;
const TERRARIUM = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png';
const GIBS_WMTS_3857 = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best';
const CREDITS = {
  gibs: 'Imagery: NASA GIBS / EOSDIS (Blue Marble)',
  eox: `EOxCloudless https://cloudless.eox.at by EOX IT Services GmbH (Contains modified Copernicus Sentinel data ${EOX_YEAR})`,
  terrain: 'Terrain: Mapzen / AWS Terrain Tiles (USGS SRTM, GMTED2010, 3DEP; NOAA ETOPO1; and others)',
};
const C = window.Cesium;
let viewer = null, rotating = true, rotateTick = null;
const GL_HELP = 'The globe needs WebGL 2 with graphics acceleration. Brave / Chrome: open brave://gpu (chrome://gpu) and look at "WebGL2"; if it says '
  + 'disabled or software, turn on "Use graphics acceleration when available" in Settings &rsaquo; System, and set "Override software rendering list" '
  + 'to Enabled in brave://flags, then relaunch. Firefox: about:config &rsaquo; webgl.force-enabled = true, then reload. Or open the studio from '
  + 'another machine on the network; the rest of the desk works here without it.';
function webglProblem() {
  const c = document.createElement('canvas');
  let gl = null;
  try { gl = c.getContext('webgl2', { failIfMajorPerformanceCaveat: false }); } catch (e) { gl = null; }
  if (gl) return null;
  const gl1 = (() => { try { return c.getContext('webgl'); } catch (e) { return null; } })();
  return `<b>${gl1 ? 'This browser has WebGL 1 only; the globe needs WebGL 2.' : 'This browser has no WebGL.'}</b><br><br>${GL_HELP}`;
}

const KIND_COLOR = { airport: '#ffd86b', country: '#5aa9e6', state: '#7bc96f', city: '#e08a7a', place: '#c45bd3' };

function terrariumProvider() {
  const N = 65, MAXL = 12;
  const cnv = document.createElement('canvas'); cnv.width = cnv.height = 256;
  const ctx = cnv.getContext('2d', { willReadFrequently: true });
  const flat = () => new Float32Array(N * N);
  return new C.CustomHeightmapTerrainProvider({
    width: N, height: N, tilingScheme: new C.WebMercatorTilingScheme(), credit: new C.Credit(CREDITS.terrain),
    callback: (x, y, level) => {
      if (level < 2 || level > MAXL) return flat();
      const url = TERRARIUM.replace('{z}', level).replace('{x}', x).replace('{y}', y);
      return fetch(url, { mode: 'cors' }).then(r => { if (!r.ok) throw new Error(r.status); return r.blob(); })
        .then(b => createImageBitmap(b)).then(bmp => {
          ctx.drawImage(bmp, 0, 0); bmp.close && bmp.close();
          const d = ctx.getImageData(0, 0, 256, 256).data; const out = new Float32Array(N * N);
          for (let j = 0; j < N; j++) {
            const py = Math.min(255, Math.round(j * 255 / (N - 1)));
            for (let i = 0; i < N; i++) {
              const px = Math.min(255, Math.round(i * 255 / (N - 1))); const k = (py * 256 + px) * 4;
              out[j * N + i] = d[k] * 256 + d[k + 1] + d[k + 2] / 256 - 32768;
            }
          }
          return out;
        }).catch(() => flat());
    },
  });
}

function makeViewer(box, msaa) {
  C.Ion.defaultAccessToken = 'unused-no-ion';
  const v = new C.Viewer(box, {
    baseLayer: false, baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false, navigationHelpButton: false,
    animation: false, timeline: false, fullscreenButton: false, infoBox: false, selectionIndicator: false, vrButton: false,
    terrainProvider: new C.EllipsoidTerrainProvider(), shouldAnimate: false, msaaSamples: msaa,
    contextOptions: { webgl: { alpha: false, preserveDrawingBuffer: false, powerPreference: msaa > 1 ? 'high-performance' : 'default', failIfMajorPerformanceCaveat: false } },
  });
  const s = v.scene;
  s.globe.baseColor = C.Color.fromCssColorString('#0a1424');
  s.globe.showGroundAtmosphere = true; s.globe.enableLighting = true; s.globe.dynamicAtmosphereLighting = true; s.globe.dynamicAtmosphereLightingFromSun = true;
  s.globe.atmosphereLightIntensity = 12.0;
  s.globe.lightingFadeOutDistance = 1.0e7; s.globe.lightingFadeInDistance = 2.0e7; s.globe.nightFadeOutDistance = 1.0e7; s.globe.nightFadeInDistance = 5.0e7;
  s.globe.maximumScreenSpaceError = 2.0; s.globe.tileCacheSize = 160;
  s.skyAtmosphere.show = true; s.fog.enabled = true; s.highDynamicRange = false; s.postProcessStages.fxaa.enabled = true;
  v.showRenderLoopErrors = false;
  // Blue Marble from GIBS's Web Mercator grid (standard 256 px power-of-two tiles; the EPSG:4326 "500m" set has 2, 3, 5, 10 ... columns
  // per level, which Cesium's geographic scheme cannot address: tiles landed off by a column and the outer ones came back 400)
  const base = new C.UrlTemplateImageryProvider({
    url: `${GIBS_WMTS_3857}/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg`,
    tilingScheme: new C.WebMercatorTilingScheme(), maximumLevel: 8, tileWidth: 256, tileHeight: 256, credit: new C.Credit(CREDITS.gibs),
  });
  s.imageryLayers.addImageryProvider(base);
  const eox = new C.UrlTemplateImageryProvider({ url: EOX_URL, tilingScheme: new C.GeographicTilingScheme(), maximumLevel: 15, tileWidth: 256, tileHeight: 256, credit: new C.Credit(CREDITS.eox) });
  s.imageryLayers.add(new C.ImageryLayer(eox, { minimumTerrainLevel: 6 }));
  v.camera.setView({ destination: C.Cartesian3.fromDegrees(-40, 30, 2.2e7) });
  // slow turn until the user takes the camera
  const stop = () => { rotating = false; const cb = document.querySelector('#gbrot'); if (cb) cb.checked = false; };
  const h = new C.ScreenSpaceEventHandler(s.canvas);
  h.setInputAction(stop, C.ScreenSpaceEventType.LEFT_DOWN); h.setInputAction(stop, C.ScreenSpaceEventType.WHEEL); h.setInputAction(stop, C.ScreenSpaceEventType.PINCH_START);
  h.setInputAction(click => onClick(v, click.position), C.ScreenSpaceEventType.LEFT_CLICK);
  rotateTick = s.postUpdate.addEventListener(() => { if (rotating) v.camera.rotate(C.Cartesian3.UNIT_Z, -0.0006); });
  return v;
}

function arcPositions(a, b, w) {
  // a great-circle arc lifted off the surface: height grows with the distance, so a short hop stays low and a transatlantic leg soars
  const A = C.Cartographic.fromDegrees(a.lon, a.lat), B = C.Cartographic.fromDegrees(b.lon, b.lat);
  const geo = new C.EllipsoidGeodesic(A, B); const dist = geo.surfaceDistance; const n = 40; const out = [];
  const lift = Math.min(1.2e6, 60000 + dist * 0.18);
  for (let i = 0; i <= n; i++) {
    const t = i / n; const p = geo.interpolateUsingFraction(t);
    out.push(C.Cartesian3.fromRadians(p.longitude, p.latitude, Math.sin(Math.PI * t) * lift + 3000));
  }
  return out;
}

function onClick(v, position) {
  const picked = v.scene.pick(position);
  const ent = picked && picked.id;
  if (!ent || !ent.properties) return;
  const kind = ent.properties.kind && ent.properties.kind.getValue();
  const data = ent.properties.data && ent.properties.data.getValue();
  if (!data) return;
  if (kind === 'photo') openPage(data.page_id);
  else if (kind === 'arc') arcSide(data);
  else globeSide(data);
}

async function drawGlobe() {
  const $ = s => document.querySelector(s);
  const f = byName($('#gbfocus').value); const lead = $('#gblead').value;
  if ($('#gblead').options.length <= 1) {
    const t = await api('/api/themes');
    t.themes.forEach(x => { const o = document.createElement('option'); o.value = x.theme; o.textContent = x.theme + ' (' + x.pages + ')'; $('#gblead').appendChild(o); });
  }
  const d = await api(`/api/globe?${f ? 'focus=' + f.id + '&' : ''}${lead ? 'lead=' + encodeURIComponent(lead) + '&' : ''}kind=${$('#gbkind').value}&min=${$('#gbmin').value}&photos=${$('#gbphotos').checked ? 1 : 0}`);
  if (!viewer) {
    const box = $('#globebox');
    const why = webglProblem();
    if (why) { box.innerHTML = `<div class="globe-nogl">${why}</div>`; GB = null; return; }
    try { viewer = makeViewer(box, 4); }
    catch (e1) {
      try { box.innerHTML = ''; viewer = makeViewer(box, 1); }
      catch (e2) { box.innerHTML = `<div class="globe-nogl"><b>The globe could not start in this browser.</b><br>${String(e2.message || e2).replace(/</g, '&lt;').slice(0, 400)}<br><br>${GL_HELP}</div>`; GB = null; return; }
    }
    GB = viewer;
  }
  viewer.scene.terrainProvider = $('#gbterrain').checked ? terrariumProvider() : new C.EllipsoidTerrainProvider();
  rotating = $('#gbrot').checked;
  const E = viewer.entities; E.removeAll();
  const byId = new Map(d.points.map(p => [p.id, p])); const maxn = Math.max(1, ...d.points.map(p => p.n));
  d.points.forEach((p, i) => {
    const size = 6 + 22 * Math.sqrt(p.n / maxn); const col = C.Color.fromCssColorString(KIND_COLOR[p.kind] || '#999');
    E.add({ position: C.Cartesian3.fromDegrees(p.lon, p.lat, 2000), point: { pixelSize: size, color: col.withAlpha(0.9), outlineColor: C.Color.BLACK.withAlpha(0.6), outlineWidth: 1.5, disableDepthTestDistance: Number.POSITIVE_INFINITY },
      label: i < 60 ? { text: p.name, font: `${11 + Math.round(6 * Math.sqrt(p.n / maxn))}px system-ui`, fillColor: C.Color.fromCssColorString('#e6e8ee'), outlineColor: C.Color.BLACK, outlineWidth: 3, style: C.LabelStyle.FILL_AND_OUTLINE, pixelOffset: new C.Cartesian2(0, -size / 2 - 8), verticalOrigin: C.VerticalOrigin.BOTTOM, disableDepthTestDistance: Number.POSITIVE_INFINITY, scaleByDistance: new C.NearFarScalar(1e6, 1.0, 2.5e7, 0.55) } : undefined,
      properties: { kind: 'point', data: p } });
  });
  const arcs = d.arcs.slice(0, +$('#gbarcs').value);
  arcs.forEach(a => {
    const A = byId.get(a.a), B = byId.get(a.b); if (!A || !B) return;
    const flight = A.kind === 'airport' && B.kind === 'airport';
    const col = flight ? C.Color.fromCssColorString('#ffd86b') : C.Color.fromCssColorString('#ff8c42');
    E.add({ polyline: { positions: arcPositions(A, B, a.w), width: Math.min(3, 0.8 + Math.log2(1 + a.w) * 0.45), material: new C.PolylineGlowMaterialProperty({ glowPower: 0.18, taperPower: 0.8, color: col.withAlpha(0.6) }), arcType: C.ArcType.NONE },
      properties: { kind: 'arc', data: { a: A, b: B, w: a.w, pages: a.pages } } });
  });
  let photos = 0; const seen = {};
  for (const ph of d.photos) {
    const P = byId.get(ph.entity_id); if (!P) continue;
    seen[ph.entity_id] = (seen[ph.entity_id] || 0) + 1; if (seen[ph.entity_id] > 6) continue;
    const ang = seen[ph.entity_id] * 1.05, r = 1.1;
    E.add({ position: C.Cartesian3.fromDegrees(P.lon + r * Math.cos(ang), P.lat + r * Math.sin(ang), 2000), point: { pixelSize: 5, color: C.Color.WHITE, outlineColor: C.Color.BLACK.withAlpha(0.7), outlineWidth: 1, disableDepthTestDistance: Number.POSITIVE_INFINITY },
      properties: { kind: 'photo', data: { page_id: ph.page_id, pdf_page: ph.pdf_page, bates: ph.bates, place: P.name } } }); photos++;
  }
  if (f && d.points.length) {
    const lons = d.points.map(p => p.lon), lats = d.points.map(p => p.lat);
    viewer.camera.flyTo({ destination: C.Rectangle.fromDegrees(Math.min(...lons) - 5, Math.min(...lats) - 5, Math.max(...lons) + 5, Math.max(...lats) + 5), duration: 1.6 });
    rotating = false; $('#gbrot').checked = false;
  }
  const side = $('#gbside'); side.style.display = 'block';
  side.innerHTML = `<div class="meta">${d.points.length} located things, ${arcs.length} arcs, ${photos} photo dots · page set: ${esc(d.note)}. Click a dot or an arc; drag to turn, scroll to zoom. Gold arcs join two airports on one page (a flight leg); orange arcs join places named on one page.</div>`;
}
window.drawGlobe = drawGlobe;
document.addEventListener('DOMContentLoaded', () => {
  const cb = document.querySelector('#gbrot'); if (cb) cb.addEventListener('change', () => { rotating = cb.checked; });
  const tb = document.querySelector('#gbterrain'); if (tb) tb.addEventListener('change', () => { if (viewer) viewer.scene.terrainProvider = tb.checked ? terrariumProvider() : new C.EllipsoidTerrainProvider(); });
});
