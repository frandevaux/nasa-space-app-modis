/* Loading (with in-memory cache) of the files in public/data, plus the field-log API client. */
import type { LogEntry, Meta, MonthFires, MonthHotspots, Prediction, PredictionGrid, Region, SeriesJson } from './types';

const cache = new Map<string, Promise<unknown>>();

function load<T>(url: string, optional = false): Promise<T | null> {
  if (!cache.has(url)) {
    const p = fetch(url)
      .then((r) => {
        if (!r.ok) {
          if (optional || r.status === 404) { return null; }
          throw new Error(`${url}: ${r.status}`);
        }
        return r.json();
      })
      .catch((e) => {
        cache.delete(url);
        if (optional) { return null; }
        throw e;
      });
    cache.set(url, p);
  }
  return cache.get(url) as Promise<T | null>;
}

export const getMeta = () => load<Meta>('/data/meta.json') as Promise<Meta>;
export const getRegions = () => load<Region[]>('/data/regions.json') as Promise<Region[]>;
export const getGeo = (layer: 'provinces' | 'departments') =>
  load<GeoJSON.FeatureCollection>(`/data/geo/${layer}.json`) as Promise<GeoJSON.FeatureCollection>;

/** Regions without any hotspot have no file: they get an empty series. */
export async function getSeries(region: string): Promise<SeriesJson> {
  const s = await load<SeriesJson>(`/data/series/${region}.json`, true);
  return s ?? { region, cols: [], rows: [] };
}

export const getMonthHotspots = (ym: string) => load<MonthHotspots>(`/data/hotspots/${ym}.json`, true);
export const getMonthFires = (ym: string) => load<MonthFires>(`/data/fires/${ym}.json`, true);

export const getPrediction = () => load<Prediction>('/data/prediction/index.json', true);
export const getPredictionGrid = (ym: string) => load<PredictionGrid>(`/data/prediction/${ym}.json`, true);

/* --- Field log: own API, never cached --- */
export async function getEntries(): Promise<LogEntry[]> {
  const r = await fetch('/api/entries', { cache: 'no-store' });
  if (!r.ok) { return []; }
  return r.json();
}

export async function createEntry(data: Omit<LogEntry, 'id' | 'createdAt'>): Promise<LogEntry> {
  const r = await fetch('/api/entries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw new Error(e.error || 'No se pudo guardar el registro');
  }
  return r.json();
}

export function entryInRegion(e: LogEntry, region: Region): boolean {
  if (region.kind === 'country') { return true; }
  if (region.kind === 'province') { return e.province === region.id; }
  return e.department === region.id;
}
