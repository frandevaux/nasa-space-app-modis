'use client';
/* Shared hooks: URL state (region / month / day), region data and field-log entries. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { getEntries, getMeta, getPrediction, getRegions, getSeries } from './data';
import { analyze, type RegionSeries } from './series';
import { dayFromIso, indexFromYm, ym } from './time';
import { buildForecast, type Forecast } from './forecast';
import type { LogEntry, Meta, Region } from './types';
import type { Scale } from './timescale';

export type Sensor = 'both' | 'modis' | 'viirs';
export interface Point { lat: number; lon: number }
/** A fire event (the UI calls it "incendio") by id, plus the monthly fire file where it was found. */
export interface IncidentRef { month: string; id: string }

const parsePoint = (v: string | null): Point | null => {
  const [lat, lon] = (v ?? '').split(',').map(Number);
  return v && Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : null;
};
const parseIncident = (v: string | null): IncidentRef | null => {
  const m = /^(\d{4}-\d{2}):([0-9a-z]+)$/.exec(v ?? '');
  return m ? { month: m[1], id: m[2] } : null;
};
export const incidentParam = (r: IncidentRef) => `${r.month}:${r.id}`;
export const pointParam = (p: Point) => `${p.lat.toFixed(4)},${p.lon.toFixed(4)}`;

export const DEFAULT_REGION = 'AR';

/**
 * Region (?r=), month (?m=YYYY-MM), day of month (?d=), timeline scale (?z=day|week|month) and map view
 * (?v=fires|hotspots), hotspot sensor (?s=modis|viirs, default both), the selected point (?pt=lat,lon) and
 * the fire event at that point (?ev=YYYY-MM:id) live in the URL so that
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
  const ptParam = params.get('pt');
  const evParam = params.get('ev');
  const point = useMemo(() => parsePoint(ptParam), [ptParam]);
  const incident = useMemo(() => parseIncident(evParam), [evParam]);

  const update = useCallback(
    (patch: { r?: string; m?: number; d?: number | null; z?: Scale; v?: 'fires' | 'hotspots'; s?: Sensor; pt?: Point | null; ev?: IncidentRef | null }) => {
      const next = new URLSearchParams(params.toString());
      if (patch.r !== undefined) { next.set('r', patch.r); }
      if (patch.m !== undefined) { next.set('m', ym(patch.m)); }
      if (patch.z !== undefined) { next.set('z', patch.z); }
      if (patch.v !== undefined) { next.set('v', patch.v); }
      if (patch.pt !== undefined) {
        if (patch.pt === null) { next.delete('pt'); } else { next.set('pt', pointParam(patch.pt)); }
      }
      if (patch.ev !== undefined) {
        if (patch.ev === null) { next.delete('ev'); } else { next.set('ev', incidentParam(patch.ev)); }
      }
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

  return { regionId, month, day, scale, view, sensor, point, incident, hasMonth: m !== null, update, query: params.toString() };
}

export interface BaseData {
  meta: Meta;
  regions: Region[];
  regionById: Map<string, Region>;
  lastMonth: number;
  /** Daily forecast after the last observed day (null if there is none). */
  forecast: Forecast | null;
}

export function useBaseData(): BaseData | null {
  const [data, setData] = useState<BaseData | null>(null);
  useEffect(() => {
    let alive = true;
    Promise.all([getMeta(), getRegions(), getPrediction()]).then(([meta, regions, prediction]) => {
      if (!alive) { return; }
      const lastMonth = indexFromYm(meta.lastDate.slice(0, 7));
      const forecast = buildForecast(prediction, dayFromIso(meta.lastDate));
      setData({ meta, regions, regionById: new Map(regions.map((r) => [r.id, r])), lastMonth, forecast });
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
