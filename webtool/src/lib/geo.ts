/* Lightweight client-side geometry: fire / hotspot windows, spatial indexes, point readings and point-in-polygon. */
import type { EventInfo, FireInfo, MonthFires, MonthHotspots } from './types';
import { dayIndex } from './time';

const CELL = 0.1;            // degrees, spatial index cell
const COORD_SCALE = 10_000;  // fire rings are stored in 1e-4° integers

const monthStart = (ym: string) => {
  const [y, m] = ym.split('-').map(Number);
  return dayIndex(y, m - 1, 1);
};
const fadeOf = (abs: number, to: number, span: number, fade: boolean) => (fade ? 1 - 0.8 * ((to - abs) / span) : 1);

/* ------------------------------------------------------------------ fires */

/** Fires of a monthly file, decoded once per file (rings, bbox, events). */
const fireCache = new WeakMap<MonthFires, FireInfo[]>();
export function decodeFires(m: MonthFires): FireInfo[] {
  const cached = fireCache.get(m);
  if (cached) { return cached; }
  const E = m.events;
  const events: EventInfo[] = E.id.map((id, j) => ({
    id, start: E.start[j], end: E.end[j], days: E.days[j], nFires: E.nFires[j], km2: E.km2[j], polyKm2: E.polyKm2[j],
    pa: E.pa[j] === 1, forest: E.forest[j] === 1, bufferKm: E.bufferKm[j], conf: E.conf[j],
  }));
  const start = monthStart(m.month);
  const list: FireInfo[] = m.id.map((id, j) => {
    const g = m.geom[j];
    let x = Math.round(m.lon[j] * COORD_SCALE);
    let y = Math.round(m.lat[j] * COORD_SCALE);
    const ring: [number, number][] = [];
    let w = Infinity; let s = Infinity; let e = -Infinity; let n = -Infinity;
    for (let k = 0; k + 1 < g.length; k += 2) {
      x += g[k];
      y += g[k + 1];
      const lon = x / COORD_SCALE;
      const lat = y / COORD_SCALE;
      ring.push([lon, lat]);
      if (lon < w) { w = lon; } if (lon > e) { e = lon; }
      if (lat < s) { s = lat; } if (lat > n) { n = lat; }
    }
    if (ring.length) { ring.push(ring[0]); } else { w = e = m.lon[j]; s = n = m.lat[j]; }
    return {
      id, start: m.start[j], conf: m.conf[j], n: m.nh[j], nM: m.nM[j], nV: m.nV[j], sats: m.sats[j], km2: m.km2[j],
      polyKm2: m.polyKm2[j], pa: m.pa[j] === 1, paName: m.paName[j], forest: m.forest[j] === 1,
      event: events[m.event[j]] ?? null, lon: m.lon[j], lat: m.lat[j], day: start + m.d[j] - 1, ring, bbox: [w, s, e, n],
    };
  });
  fireCache.set(m, list);
  return list;
}

/** Fires that started inside [from, to] (absolute days), with their fade (1 = the cursor day). */
export interface FireWindow { fires: FireInfo[]; f: number[] }

export function sliceFires(months: MonthFires[], from: number, to: number, fade: boolean): FireWindow {
  const out: FireWindow = { fires: [], f: [] };
  const span = Math.max(1, to - from);
  for (const m of months) {
    for (const fire of decodeFires(m)) {
      if (fire.day < from || fire.day > to) { continue; }
      out.fires.push(fire);
      out.f.push(fadeOf(fire.day, to, span, fade));
    }
  }
  return out;
}

export interface FireIndex { win: FireWindow; cells: Map<string, number[]> }

export function indexFires(win: FireWindow): FireIndex {
  const cells = new Map<string, number[]>();
  win.fires.forEach((fire, i) => {
    const [w, s, e, n] = fire.bbox;
    for (let cy = Math.floor(s / CELL); cy <= Math.floor(n / CELL); cy++) {
      for (let cx = Math.floor(w / CELL); cx <= Math.floor(e / CELL); cx++) {
        const k = `${cy}:${cx}`;
        const c = cells.get(k);
        if (c) { c.push(i); } else { cells.set(k, [i]); }
      }
    }
  });
  return { win, cells };
}

export interface Reading {
  /** Combined confidence of what covers the point, 0–100 (0 = nothing covers it). */
  pct: number;
  /** Fires view: fires whose polygon contains the point. Hotspots view: pixels covering the point. */
  n: number;
  nModis: number;
  nViirs: number;
  band: string;
  /** Strongest fire covering the point, and how many distinct fires cover it. */
  fire: FireInfo | null;
  nFires: number;
}

function bandOf(pr: number) {
  return pr >= 0.85 ? 'muy alta' : pr >= 0.6 ? 'alta' : pr >= 0.35 ? 'media' : pr >= 0.15 ? 'baja' : 'mínima';
}

/**
 * Fires view: confidence at a point = 1 − Π(1 − c_i · f_i) over the fires whose polygon contains it
 * (c = fire confidence, métrica de confidence; f = fade of older days). Nothing outside the polygons.
 */
export function readFires(idx: FireIndex | null, lat: number, lon: number): Reading {
  let q = 1;
  let best: FireInfo | null = null;
  let bestV = 0;
  let n = 0;
  let nModis = 0;
  let nViirs = 0;
  const cand = idx?.cells.get(`${Math.floor(lat / CELL)}:${Math.floor(lon / CELL)}`) ?? [];
  for (const i of cand) {
    const fire = idx!.win.fires[i];
    const [w, s, e, nn] = fire.bbox;
    if (lon < w || lon > e || lat < s || lat > nn) { continue; }
    if (fire.ring.length < 4 || !inRing(lon, lat, fire.ring)) { continue; }
    const v = (fire.conf / 100) * idx!.win.f[i];
    q *= 1 - v;
    n += 1;
    nModis += fire.nM;
    nViirs += fire.nV;
    if (v > bestV) { bestV = v; best = fire; }
  }
  const pr = 1 - q;
  return { pct: Math.round(pr * 100), n, nModis, nViirs, band: bandOf(pr), fire: best, nFires: n };
}

/* ------------------------------------------------------------------ hotspots */

/**
 * Hotspots of a window of days (may span two monthly files).
 * `f` = fade 0–1 (1 = the cursor day); `fi` = the hotspot's fire, when its fire file is loaded.
 */
export interface WindowHotspots extends MonthHotspots { f: number[]; fi: (FireInfo | null)[] }

/** `sensor`: keep only MODIS (s = 0) or VIIRS (s = 1) hotspots, or both. */
export function sliceWindow(
  months: MonthHotspots[], fireMonths: Map<string, MonthFires>, from: number, to: number, fade: boolean,
  sensor: 'both' | 'modis' | 'viirs' = 'both',
): WindowHotspots {
  const out: WindowHotspots = { month: '', n: 0, lat: [], lon: [], s: [], p: [], r: [], d: [], f: [], fi: [] };
  const span = Math.max(1, to - from);
  for (const h of months) {
    const fm = fireMonths.get(h.month);
    const fires = fm ? decodeFires(fm) : [];
    const start = monthStart(h.month);
    for (let i = 0; i < h.n; i++) {
      const abs = start + h.d[i] - 1;
      if (abs < from || abs > to) { continue; }
      if ((sensor === 'viirs' && h.s[i] !== 1) || (sensor === 'modis' && h.s[i] === 1)) { continue; }
      out.lat.push(h.lat[i]);
      out.lon.push(h.lon[i]);
      out.s.push(h.s[i]);
      out.p.push(h.p[i]);
      out.r.push(h.r[i]);
      out.d.push(abs);
      out.f.push(fadeOf(abs, to, span, fade));
      out.fi.push(h.fire && h.fire[i] >= 0 ? fires[h.fire[i]] ?? null : null);
      out.n += 1;
    }
  }
  return out;
}

export interface HotspotIndex { data: WindowHotspots; cells: Map<string, number[]> }

export function buildIndex(h: WindowHotspots): HotspotIndex {
  const cells = new Map<string, number[]>();
  for (let i = 0; i < h.n; i++) {
    const k = `${Math.floor(h.lat[i] / CELL)}:${Math.floor(h.lon[i] / CELL)}`;
    const c = cells.get(k);
    if (c) { c.push(i); } else { cells.set(k, [i]); }
  }
  return { data: h, cells };
}

/**
 * Hotspots view: only the pixels that cover the point (circle of radius r_i, radio de píxel) count.
 * Each hotspot carries the confidence of its fire; hotspots of the same fire are not independent
 * evidence (métrica de confidence), so each fire counts once and distinct fires / unlinked hotspots combine with 1 − Π(1 − c·f).
 */
export function readPoint(idx: HotspotIndex | null, lat: number, lon: number): Reading {
  let q = 1;
  let n = 0;
  let nModis = 0;
  let nViirs = 0;
  const perFire = new Map<FireInfo, number>();
  let best: FireInfo | null = null;
  let bestV = 0;
  if (idx) {
    const h = idx.data;
    const cy = Math.floor(lat / CELL);
    const cx = Math.floor(lon / CELL);
    const kx = 111320 * Math.cos((lat * Math.PI) / 180);
    const ky = 110540;
    for (let a = -1; a <= 1; a++) {
      for (let b = -1; b <= 1; b++) {
        const c = idx.cells.get(`${cy + a}:${cx + b}`);
        if (!c) { continue; }
        for (const i of c) {
          const dx = (h.lon[i] - lon) * kx;
          const dy = (h.lat[i] - lat) * ky;
          if (dx * dx + dy * dy > h.r[i] * h.r[i]) { continue; }
          const v = (h.p[i] / 100) * h.f[i];
          const fire = h.fi[i];
          if (fire) {
            perFire.set(fire, Math.max(perFire.get(fire) ?? 0, v));
            if (v > bestV) { bestV = v; best = fire; }
          } else {
            q *= 1 - v;
          }
          n += 1;
          if (h.s[i] === 1) { nViirs += 1; } else { nModis += 1; }
        }
      }
    }
  }
  perFire.forEach((v) => { q *= 1 - v; });
  const pr = 1 - q;
  return { pct: Math.round(pr * 100), n, nModis, nViirs, band: bandOf(pr), fire: best, nFires: perFire.size };
}

/* ------------------------------------------------------------------ GeoJSON for MapLibre */

export function firesToGeoJSON(win: FireWindow | null): { polygons: GeoJSON.FeatureCollection; points: GeoJSON.FeatureCollection } {
  const polygons: GeoJSON.Feature[] = [];
  const points: GeoJSON.Feature[] = [];
  win?.fires.forEach((fire, i) => {
    const properties = { id: fire.id, conf: fire.conf, f: win.f[i], km2: fire.km2 };
    if (fire.ring.length >= 4) {
      polygons.push({ type: 'Feature', properties, geometry: { type: 'Polygon', coordinates: [fire.ring] } });
    }
    points.push({ type: 'Feature', properties, geometry: { type: 'Point', coordinates: [fire.lon, fire.lat] } });
  });
  return { polygons: { type: 'FeatureCollection', features: polygons }, points: { type: 'FeatureCollection', features: points } };
}

export function hotspotsToGeoJSON(h: WindowHotspots | null): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  if (h) {
    for (let i = 0; i < h.n; i++) {
      features.push({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [h.lon[i], h.lat[i]] },
        properties: { p: h.p[i], r: h.r[i], s: h.s[i], f: h.f[i] },
      });
    }
  }
  return { type: 'FeatureCollection', features };
}

/* ------------------------------------------------------------------ point in polygon */
function inRing(x: number, y: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) { inside = !inside; }
  }
  return inside;
}

function inPolygon(x: number, y: number, poly: number[][][]): boolean {
  if (!inRing(x, y, poly[0])) { return false; }
  for (let k = 1; k < poly.length; k++) { if (inRing(x, y, poly[k])) { return false; } }
  return true;
}

/** Which feature of `fc` (departments, provinces) contains the point. */
export function locate<P = Record<string, unknown>>(fc: GeoJSON.FeatureCollection | null, lon: number, lat: number): P | null {
  if (!fc) { return null; }
  for (const f of fc.features) {
    const g = f.geometry;
    if (g.type === 'Polygon' && inPolygon(lon, lat, g.coordinates as number[][][])) { return f.properties as P; }
    if (g.type === 'MultiPolygon') {
      for (const poly of g.coordinates as number[][][][]) {
        if (inPolygon(lon, lat, poly)) { return f.properties as P; }
      }
    }
  }
  return null;
}
