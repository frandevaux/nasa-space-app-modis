/*
 * "Fires" as the UI calls them = fire events of the pipeline (FEDS-style groups of fires).
 * Built on the client from a monthly fire file: one item per event, located at its largest fire
 * (preferring fires whose centroid falls inside their own outline), with that fire's day so the map
 * window at that date shows it.
 */
import { decodeFires, inPolygon } from './geo';
import { spansDays } from './time';
import type { EventInfo, FireInfo, MonthFires } from './types';

export interface Incident {
  month: string;      // monthly fire file the event was read from (YYYY-MM)
  event: EventInfo;
  lat: number;
  lon: number;
  day: number;        // absolute day of the representative fire
}

function toIncidents(month: string, fires: FireInfo[]): Incident[] {
  const best = new Map<string, { f: FireInfo; score: number }>();
  for (const f of fires) {
    if (!f.event) { continue; }
    const inside = f.ring.length < 4 || inPolygon(f.lon, f.lat, [f.ring]);
    const score = (inside ? 1e9 : 0) + f.km2;
    const cur = best.get(f.event.id);
    if (!cur || score > cur.score) { best.set(f.event.id, { f, score }); }
  }
  return [...best.values()]
    .map(({ f }) => ({ month, event: f.event!, lat: f.lat, lon: f.lon, day: f.day }))
    .sort((a, b) => a.event.start.localeCompare(b.event.start));
}

/** The event `id` among the fires of a monthly file (null if it is not there). */
export function findIncident(m: MonthFires, id: string): Incident | null {
  return toIncidents(m.month, decodeFires(m).filter((f) => f.event?.id === id))[0] ?? null;
}

/** Events with at least one fire (centroid) inside the feature (a department) in this monthly file. */
export function incidentsIn(m: MonthFires, feature: GeoJSON.Feature): Incident[] {
  const polys = feature.geometry.type === 'Polygon'
    ? [feature.geometry.coordinates as number[][][]]
    : feature.geometry.type === 'MultiPolygon' ? (feature.geometry.coordinates as number[][][][]) : [];
  let w = Infinity; let s = Infinity; let e = -Infinity; let n = -Infinity;
  for (const poly of polys) {
    for (const [x, y] of poly[0]) {
      if (x < w) { w = x; } if (x > e) { e = x; }
      if (y < s) { s = y; } if (y > n) { n = y; }
    }
  }
  const inside = decodeFires(m).filter((f) => (
    f.lon >= w && f.lon <= e && f.lat >= s && f.lat <= n && polys.some((p) => inPolygon(f.lon, f.lat, p))
  ));
  return toIncidents(m.month, inside);
}

/**
 * Events that span several (local) days are "firewaves"; single-day events are plain "fires".
 * start / end: UTC 'YYYY-MM-DDTHH:MM'.
 */
export const isWave = spansDays;

/** "firewave" / "fire", with the article for "del / de la". */
export function eventNoun(start: string, end: string): { noun: string; of: string } {
  return isWave(start, end) ? { noun: 'firewave', of: 'del' } : { noun: 'fire', of: 'del' };
}
