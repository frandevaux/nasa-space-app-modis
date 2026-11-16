'use client';
/* Shared hooks: URL state (region / month / day), region data and field-log entries. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { getEntries, getMeta, getPrediction, getRegions, getSeries } from './data';
import { analyze, type RegionSeries } from './series';
import { indexFromYm, ym } from './time';
import type { LogEntry, Meta, Prediction, Region } from './types';
import type { Scale } from './timescale';

export type Sensor = 'both' | 'modis' | 'viirs';

export const DEFAULT_REGION = 'AR';
/** Months shown after "now" when no forecast file is loaded yet. */
export const DEFAULT_FORECAST_HORIZON = 7;

/**
 * Region (?r=), month (?m=YYYY-MM), day of month (?d=), timeline scale (?z=day|week|month) and map view
 * (?v=fires|hotspots) and hotspot sensor (?s=modis|viirs, default both) live in the URL so that
 * the Map and Calendar views share the same selection and links can be shared.
 */
export function useUrlState(lastMonth: number | null) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const regionId = params.get('r') || DEFAULT_REGION;
  const m = params.get('m');
  const month = m ? indexFromYm(m) : lastMonth;
  const dayParam = params.get('d');
  const day = dayParam ? Number(dayParam) : null;
  const z = params.get('z');
  const scale: Scale = z === 'week' || z === 'month' ? z : 'day';
  const view: 'fires' | 'hotspots' = params.get('v') === 'hotspots' ? 'hotspots' : 'fires';
  const sp = params.get('s');
  const sensor: Sensor = sp === 'modis' || sp === 'viirs' ? sp : 'both';

  const update = useCallback(
    (patch: { r?: string; m?: number; d?: number | null; z?: Scale; v?: 'fires' | 'hotspots'; s?: Sensor }) => {
      const next = new URLSearchParams(params.toString());
      if (patch.r !== undefined) { next.set('r', patch.r); }
      if (patch.m !== undefined) { next.set('m', ym(patch.m)); }
      if (patch.z !== undefined) { next.set('z', patch.z); }
      if (patch.v !== undefined) { next.set('v', patch.v); }
      if (patch.s !== undefined) {
        if (patch.s === 'both') { next.delete('s'); } else { next.set('s', patch.s); }
      }
      if (patch.d !== undefined) {
        if (patch.d === null) { next.delete('d'); } else { next.set('d', String(patch.d)); }
      }
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );

  return { regionId, month, day, scale, view, sensor, hasMonth: m !== null, update, query: params.toString() };
}

export interface BaseData {
  meta: Meta;
  regions: Region[];
  regionById: Map<string, Region>;
  lastMonth: number;
  prediction: Prediction | null;
  /** Forecast month indices after lastMonth (from the prediction file, or a placeholder horizon). */
  forecastMonths: number[];
}

export function useBaseData(): BaseData | null {
  const [data, setData] = useState<BaseData | null>(null);
  useEffect(() => {
    let alive = true;
    Promise.all([getMeta(), getRegions(), getPrediction()]).then(([meta, regions, prediction]) => {
      if (!alive) { return; }
      const lastMonth = indexFromYm(meta.lastDate.slice(0, 7));
      const fromFile = (prediction?.months ?? []).map(indexFromYm).filter((i) => i > lastMonth);
      const forecastMonths = fromFile.length
        ? fromFile
        : Array.from({ length: DEFAULT_FORECAST_HORIZON }, (_, k) => lastMonth + 1 + k);
      setData({ meta, regions, regionById: new Map(regions.map((r) => [r.id, r])), lastMonth, prediction, forecastMonths });
    });
    return () => { alive = false; };
  }, []);
  return data;
}

export function useRegionSeries(regionId: string, lastMonth: number | null): RegionSeries | null {
  const [state, setState] = useState<{ id: string; s: RegionSeries } | null>(null);
  useEffect(() => {
    if (lastMonth === null) { return; }
    let alive = true;
    getSeries(regionId).then((json) => {
      if (alive) { setState({ id: regionId, s: analyze(json, lastMonth) }); }
    });
    return () => { alive = false; };
  }, [regionId, lastMonth]);
  return state && state.id === regionId ? state.s : null;
}

export function useEntries() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const reload = useCallback(() => { getEntries().then(setEntries); }, []);
  useEffect(() => { reload(); }, [reload]);
  const add = useCallback((e: LogEntry) => setEntries((prev) => [e, ...prev].sort((a, b) => b.date.localeCompare(a.date))), []);
  return useMemo(() => ({ entries, reload, add }), [entries, reload, add]);
}
