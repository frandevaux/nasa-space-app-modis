/*
 * Daily forecast of the hotspot model, as used by the map, the timeline and the calendar.
 * Forecast days are the predicted dates AFTER the last observed day: when both exist, the real data wins.
 */
import type { FireWindow } from './geo';
import { dayFromIso } from './time';
import type { EventInfo, FireInfo, Prediction, Region } from './types';

/**
 * Forecast colour scale (yellow), so estimates never look like the historical record (orange).
 * Map colours use the size of each predicted fire (hotspots), never the model score.
 */
export const PRED_SIZE_LABELS = ['1', '2–3', '4–9', '10+'];
export const PRED_BG = ['#FBF6D9', '#F9EB9C', '#F5DA55', '#EBC21F', '#C99A06'];

/** Level 0–4 of a predicted count relative to the busiest forecast day (0 = none). */
export function predLevel(n: number, max: number): number {
  return n <= 0 ? 0 : 1 + Math.min(3, Math.floor((n / Math.max(1, max)) * 3.999));
}

const CELL = 0.1;            // degrees, spatial index cell
const RADIUS_M = 500 * Math.SQRT2; // half the diagonal of a 1 km cell, as the pipeline (pred/src/08)

export interface ForecastEvent { id: string; start: string; end: string; nFires: number; km2: number; conf: number; lat: number; lon: number }

export interface Forecast {
  p: Prediction;
  /** First and last forecast day (absolute day indices); first > last observed day. */
  from: number;
  to: number;
  events: ForecastEvent[];
  /** Predicted fires as FireInfo, so the historical fire tools (index, reading, GeoJSON) work on them. */
  fires: FireInfo[];
  /** Index into p.dates of an absolute day (-1 if it is not a forecast day). */
  dateIndex: (day: number) => number;
}

export function buildForecast(p: Prediction | null, lastDataDay: number): Forecast | null {
  if (!p || !p.dates.length) { return null; }
  const days = p.dates.map(dayFromIso);
  const future = days.filter((d) => d > lastDataDay);
  if (!future.length) { return null; }
  const pos = new Map(days.map((d, i) => [d, i]));
  const E = p.events;
  const events = E.id.map((id, j) => ({ id, start: E.start[j], end: E.end[j], nFires: E.nFires[j], km2: E.km2[j], conf: E.conf[j], lat: E.lat[j], lon: E.lon[j] }));
  const eventInfo: EventInfo[] = events.map((e) => ({
    id: e.id, start: e.start, end: e.end, days: (Date.parse(`${e.end}:00Z`) - Date.parse(`${e.start}:00Z`)) / 86400000,
    nFires: e.nFires, km2: e.km2, polyKm2: e.km2, pa: false, forest: false, bufferKm: 1, conf: e.conf,
  }));
  const F = p.fires;
  const fires: FireInfo[] = F.id.map((id, j) => {
    const ring = F.ring[j];
    const xs = ring.map((c) => c[0]);
    const ys = ring.map((c) => c[1]);
    const ev = eventInfo[F.ev[j]] ?? null;
    return {
      id, start: `${p.dates[F.d[j]]}T12:00`, conf: F.conf[j],
      // Predicted hotspots have no sensor: they are counted as nV so "hotspots" = nM + nV keeps working.
      n: F.n[j], nM: 0, nV: F.n[j], sats: 'Pronóstico', km2: F.km2[j], polyKm2: F.polyKm2[j],
      pa: false, paName: '', forest: false, event: ev, lon: F.lon[j], lat: F.lat[j],
      day: dayFromIso(p.dates[F.d[j]]), ring, bbox: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)],
    };
  });
  return {
    p,
    from: Math.min(...future),
    to: Math.max(...future),
    events,
    fires,
    dateIndex: (day) => (day > lastDataDay ? pos.get(day) ?? -1 : -1),
  };
}

/** Does the model cover this region? 'partial' for the country (it covers some provinces only). */
export function coverageOf(f: Forecast | null, region: Region): 'full' | 'partial' | 'none' {
  if (!f) { return 'none'; }
  const prov = region.kind === 'province' ? region.id : region.province;
  if (region.kind === 'country') { return f.p.coverage.regions.length ? 'partial' : 'none'; }
  return prov && f.p.coverage.regions.includes(prov) ? 'full' : 'none';
}

/** Predicted fires on a forecast day in a region (null = not covered or not a forecast day). */
export function forecastFires(f: Forecast | null, region: Region, day: number): number | null {
  if (!f || coverageOf(f, region) === 'none') { return null; }
  const i = f.dateIndex(day);
  if (i < 0) { return null; }
  return f.p.counts[region.id]?.fires[i] ?? 0;
}

/* ------------------------------------------------------------------ map window */

/** Predicted fires of forecast days [from, to] with their fade (1 = the cursor day), like sliceFires. */
export function forecastFireWindow(f: Forecast, from: number, to: number): FireWindow {
  const out: FireWindow = { fires: [], f: [] };
  const span = Math.max(1, to - from);
  for (const fire of f.fires) {
    if (fire.day < Math.max(from, f.from) || fire.day > to) { continue; }
    out.fires.push(fire);
    out.f.push(1 - 0.8 * ((to - fire.day) / span));
  }
  return out;
}

export interface ForecastWindow { f: Forecast; idx: number[]; fade: number[]; cells: Map<string, number[]> }

/** Predicted hotspots of forecast days [from, to], faded towards `from` (1 = the cursor day). */
export function forecastWindow(f: Forecast, from: number, to: number): ForecastWindow {
  const H = f.p.hotspots;
  const idx: number[] = [];
  const fade: number[] = [];
  const cells = new Map<string, number[]>();
  const span = Math.max(1, to - from);
  for (let i = 0; i < H.d.length; i++) {
    const day = dayFromIso(f.p.dates[H.d[i]]);
    if (day < Math.max(from, f.from) || day > to) { continue; }
    const k = idx.length;
    idx.push(i);
    fade.push(1 - 0.8 * ((to - day) / span));
    const key = `${Math.floor(H.lat[i] / CELL)}:${Math.floor(H.lon[i] / CELL)}`;
    const c = cells.get(key);
    if (c) { c.push(k); } else { cells.set(key, [k]); }
  }
  return { f, idx, fade, cells };
}

export function forecastToGeoJSON(w: ForecastWindow | null): GeoJSON.FeatureCollection {
  const H = w?.f.p.hotspots;
  return {
    type: 'FeatureCollection',
    features: !w || !H ? [] : w.idx.map((i, k) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [H.lon[i], H.lat[i]] },
      // n = hotspots of the predicted fire this cell belongs to (drives the colour, not the model score).
      properties: { n: w.f.p.fires.n[H.fire[i]] ?? 1, f: w.fade[k], r: RADIUS_M },
    })),
  };
}

export interface ForecastReading { n: number; event: ForecastEvent | null; fire: FireInfo | null }

/**
 * Predicted cells covering the point, and the fire / event they belong to (the most recent day, then the
 * largest fire). The model's probability is NOT used: it is the score of cells that already passed the 0.8
 * threshold, so it is always ≥ 80 % and cannot be compared with the historical confidence.
 */
export function readForecast(w: ForecastWindow | null, lat: number, lon: number): ForecastReading {
  if (!w) { return { n: 0, event: null, fire: null }; }
  const H = w.f.p.hotspots;
  const kx = 111320 * Math.cos((lat * Math.PI) / 180);
  const ky = 110540;
  const cy = Math.floor(lat / CELL);
  const cx = Math.floor(lon / CELL);
  let n = 0;
  let best = -1;
  let bestKey = -1;
  for (let a = -1; a <= 1; a++) {
    for (let b = -1; b <= 1; b++) {
      for (const k of w.cells.get(`${cy + a}:${cx + b}`) ?? []) {
        const i = w.idx[k];
        const dx = (H.lon[i] - lon) * kx;
        const dy = (H.lat[i] - lat) * ky;
        if (dx * dx + dy * dy > RADIUS_M * RADIUS_M) { continue; }
        n += 1;
        const key = w.fade[k] * 1000 + (w.f.fires[H.fire[i]]?.n ?? 0);
        if (H.fire[i] >= 0 && key > bestKey) { bestKey = key; best = H.fire[i]; }
      }
    }
  }
  const fire = best >= 0 ? w.f.fires[best] : null;
  const ev = fire ? w.f.p.fires.ev[best] : -1;
  return { n, fire, event: ev >= 0 ? w.f.events[ev] : null };
}
