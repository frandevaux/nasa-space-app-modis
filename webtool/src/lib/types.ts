/* Types for the static data built by scripts/build_data.py and for the field-log API. */

export type RegionKind = 'country' | 'province' | 'department';

export interface Region {
  id: string;            // 'AR' | 'pNN' | 'dNNNNN'
  kind: RegionKind;
  name: string;
  subtitle: string;
  bbox: [number, number, number, number]; // [west, south, east, north]
  children?: number;     // provinces of the country / departments of a province
  province?: string;     // parent province of a department
}

export interface Meta {
  generated: string;
  start: string;         // day 0 of the series
  lastDate: string;
  viirsStart: string;
  kModisToViirs: number;
  hotspots: number;
  months: Record<string, number>;
  source: string;
  /** Days covered by the preprocessing pipeline (fires / events with métrica de confidence confidence). */
  pipeline: { source: string; from: string; to: string; fires: number; events: number } | null;
  provisional: boolean;
}

/** Daily series row: [day since meta.start, MODIS count, VIIRS count, harmonized km², fires started (-1 = day not covered by the pipeline)] */
export type SeriesRow = [number, number, number, number, number?];

export interface SeriesJson {
  region: string;
  cols: string[];
  rows: SeriesRow[];
}

/** One month of hotspots, column-oriented (one index per hotspot). */
export interface MonthHotspots {
  month: string;
  n: number;
  lat: number[];
  lon: number[];
  s: number[];   // 0 MODIS, 1 VIIRS
  p: number[];   // confidence 0–100 (métrica de confidence: p(class)·w_sensor)
  r: number[];   // radius in m (pixel half-diagonal, radio de píxel)
  d: number[];   // day of month
  /** Row of each hotspot's fire in fires/<same month>.json (-1 = none, or the fire started the month before). */
  fire?: number[];
}

/** fires/<YYYY-MM>.json — fires (incendios, incendios) that started in the month, column-oriented. */
export interface MonthFires {
  month: string;
  n: number;
  id: string[];          // short id (12 hex of incendio_id)
  start: string[];       // UTC, YYYY-MM-DDTHH:MM
  d: number[];           // day of month (UTC)
  conf: number[];        // confidence 0–100 (métrica de confidence)
  nh: number[];          // hotspots
  nM: number[];
  nV: number[];
  sats: string[];
  km2: number[];         // Σ pixel area
  polyKm2: number[];     // polygon area
  pa: number[];          // 1 = in a protected area
  paName: string[];
  forest: number[];      // 1 = forest (MCD12Q1)
  lon: number[];         // centroid
  lat: number[];
  /** Outer ring in 1e-4° integers: first vertex relative to the centroid, then relative to the previous vertex. */
  geom: number[][];
  event: number[];       // row in `events` (-1 = none)
  events: EventTable;
}

/** Events (eventos, eventos) referenced by the fires of a month. */
export interface EventTable {
  id: string[];
  start: string[];
  end: string[];
  days: number[];
  nFires: number[];
  km2: number[];
  polyKm2: number[];
  pa: number[];
  forest: number[];
  bufferKm: number[];
  conf: number[];
}

export interface EventInfo {
  id: string; start: string; end: string; days: number; nFires: number; km2: number; polyKm2: number;
  pa: boolean; forest: boolean; bufferKm: number; conf: number;
}

export interface FireInfo {
  id: string; start: string; conf: number; n: number; nM: number; nV: number; sats: string; km2: number; polyKm2: number;
  pa: boolean; paName: string; forest: boolean; event: EventInfo | null;
  lon: number; lat: number;
  /** Absolute day index of the start (UTC). */
  day: number;
  ring: [number, number][];
  bbox: [number, number, number, number];
}

export type EntryKind = 'alert' | 'evacuation' | 'procedure' | 'control' | 'lesson';

/** Field-log entry written by firefighters / brigades. */
export interface LogEntry {
  id: string;
  date: string;          // YYYY-MM-DD of the event (not of the upload)
  kind: EntryKind;
  title: string;
  text: string;
  lesson?: string;
  author?: string;
  lat: number;
  lon: number;
  department?: string;
  province?: string;
  createdAt: string;     // ISO
}

/**
 * Precomputed forecast (delivered by the modelling team).
 * public/data/prediction/index.json
 */
export interface Prediction {
  model: string;
  generated: string;
  /** Forecast months, YYYY-MM, in order. */
  months: string[];
  /** Per region and month: expected burning area (km², VIIRS scale) and interval. */
  regions: Record<string, Record<string, { km2: number; lo?: number; hi?: number; prob?: number }>>;
  /** Optional probability grid per month for the map → public/data/prediction/<YYYY-MM>.json */
  grid?: boolean;
}

/** public/data/prediction/<YYYY-MM>.json */
export interface PredictionGrid {
  month: string;
  step: number;          // cell size in degrees
  lat: number[];         // cell centers
  lon: number[];
  p: number[];           // probability 0–100
}
