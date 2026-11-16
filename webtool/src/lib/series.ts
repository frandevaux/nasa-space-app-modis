/* Aggregations of a region's daily series: monthly totals, climatology, levels and peak season. */
import type { SeriesJson } from './types';
import { MONTH_NAMES, monthFromIndex, monthOfDay } from './time';

/** nF = fires started that day (-1 = day not covered by the pipeline). */
export interface DayValue { nM: number; nV: number; km2: number; nF: number }

export interface RegionSeries {
  byDay: Map<number, DayValue>;
  /** Harmonized km² per month index (0 = Nov 2000) up to the last month with data. */
  monthKm2: Float64Array;
  monthNM: Int32Array;
  monthNV: Int32Array;
  lastMonth: number;
  /** km² thresholds for levels 1–4, for months and for days. */
  monthThresholds: number[];
  dayThresholds: number[];
  /** Per calendar month (0 = January): 25th / 50th / 75th percentile over complete years. */
  usual: { lo: number; hi: number; med: number }[];
  peakSeason: { from: number; to: number } | null;
}

function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) { return 0; }
  const pos = (sorted.length - 1) * q;
  const a = Math.floor(pos);
  const b = Math.min(sorted.length - 1, a + 1);
  return sorted[a] + (sorted[b] - sorted[a]) * (pos - a);
}

/** Level 1 = any activity; 2–4 = 50th, 80th and 95th percentile of active periods. */
export function thresholds(values: number[]): number[] {
  const nz = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (nz.length === 0) { return [Infinity, Infinity, Infinity, Infinity]; }
  return [1e-9, quantile(nz, 0.5), quantile(nz, 0.8), quantile(nz, 0.95)];
}

export function level(v: number, t: number[]): number {
  if (!(v > 0)) { return 0; }
  let n = 0;
  for (let i = 0; i < t.length; i++) { if (v >= t[i]) { n = i + 1; } }
  return n;
}

export function analyze(s: SeriesJson, lastMonth: number): RegionSeries {
  const N = lastMonth + 1;
  const monthKm2 = new Float64Array(N);
  const monthNM = new Int32Array(N);
  const monthNV = new Int32Array(N);
  const byDay = new Map<number, DayValue>();
  for (const [d, nM, nV, k, nF] of s.rows) {
    byDay.set(d, { nM, nV, km2: k, nF: nF ?? -1 });
    const m = monthOfDay(d);
    if (m >= 0 && m < N) {
      monthKm2[m] += k;
      monthNM[m] += nM;
      monthNV[m] += nV;
    }
  }
  // Climatology: complete calendar years only (2001 → last closed month)
  const perMonth: number[][] = Array.from({ length: 12 }, () => []);
  for (let i = 0; i < lastMonth; i++) {
    const { year, month0 } = monthFromIndex(i);
    if (year >= 2001) { perMonth[month0].push(monthKm2[i]); }
  }
  const usual = perMonth.map((v) => {
    const o = [...v].sort((a, b) => a - b);
    return { lo: quantile(o, 0.25), hi: quantile(o, 0.75), med: quantile(o, 0.5) };
  });
  return {
    byDay,
    monthKm2,
    monthNM,
    monthNV,
    lastMonth,
    monthThresholds: thresholds(Array.from(monthKm2)),
    dayThresholds: thresholds(s.rows.map((f) => f[3])),
    usual,
    peakSeason: peakSeason(perMonth),
  };
}

/** Contiguous (circular) block of months around the peak whose mean is ≥ 50 % of the peak. */
function peakSeason(perMonth: number[][]): { from: number; to: number } | null {
  const mean = perMonth.map((v) => (v.length ? v.reduce((a, b) => a + b, 0) / v.length : 0));
  const max = Math.max(...mean);
  if (!(max > 0)) { return null; }
  const peak = mean.indexOf(max);
  let from = peak;
  let to = peak;
  for (let k = 0; k < 5; k++) {
    const prev = (from + 11) % 12;
    if (mean[prev] >= 0.5 * max && prev !== to) { from = prev; } else { break; }
  }
  for (let k = 0; k < 5; k++) {
    const next = (to + 1) % 12;
    if (mean[next] >= 0.5 * max && next !== from) { to = next; } else { break; }
  }
  return { from, to };
}

export function peakSeasonLabel(t: { from: number; to: number } | null, short = false): string {
  if (!t) { return 'Sin actividad'; }
  const name = (m: number) => (short ? MONTH_NAMES[m].slice(0, 3).toLowerCase() + '.' : MONTH_NAMES[m].toLowerCase());
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  if (t.from === t.to) { return cap(name(t.from)); }
  return `${cap(name(t.from))} a ${name(t.to)}`;
}
