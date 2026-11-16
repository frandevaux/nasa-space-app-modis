'use client';
/*
 * Map view ("Mapa"), laid out like a data-analysis tool: square buttons open cards around the map.
 *   top-left  Ubicación: what is at the clicked point at the cursor time
 *   bottom-left Filtros: fires (main) or hotspots (VIIRS / MODIS / both)
 *   top-right Bitácora: field-log history of the region
 * plus an always-visible fire count (country / province) and the timeline.
 */
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Header from './Header';
import FieldLog from './FieldLog';
import DashMenu from './Dash';
import EntryForm from './EntryForm';
import Timeline, { type CellStyle } from './Timeline';
import { Icon } from './icons';
import { entryInRegion, getGeo, getMonthFires, getMonthHotspots, getPredictionGrid } from '@/lib/data';
import {
  buildIndex, firesToGeoJSON, hotspotsToGeoJSON, indexFires, locate, readFires, readPoint, sliceFires, sliceWindow,
  type FireIndex, type HotspotIndex, type Reading,
} from '@/lib/geo';
import { useBaseData, useEntries, useRegionSeries, useUrlState, type Sensor } from '@/lib/hooks';
import { level, thresholds, type RegionSeries } from '@/lib/series';
import {
  dateFromDay, dayFromIso, dayIndex, daysInMonth, fmtInt, fmtKm2, isoFromDay, localDateTime, MONTH_ABBR,
  monthFromIndex, monthIndex, monthOfDay, shortDate, ym,
} from '@/lib/time';
import { dayOfUnit, monthStartDay, unitOfDay, weekOfDay, windowOf, type Scale } from '@/lib/timescale';
import type { LogEntry, MonthFires, MonthHotspots, Region } from '@/lib/types';

const MapCanvas = dynamic(() => import('./MapCanvas'), { ssr: false });
const EMPTY_FIRES = firesToGeoJSON(null);
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
const PLAY_MS: Record<Scale, number> = { day: 700, week: 900, month: 1200 };
const LEVEL_BG = ['var(--lvl-0)', 'var(--lvl-1)', 'var(--lvl-2)', 'var(--lvl-3)', 'var(--lvl-4)'];

export default function MapView() {
  const base = useBaseData();
  const { regionId, month: urlMonth, day: urlDay, scale, view, sensor, hasMonth, update, query } = useUrlState(base?.lastMonth ?? null);
  const region: Region | null = base?.regionById.get(regionId) ?? base?.regionById.get('AR') ?? null;
  const series = useRegionSeries(region?.id ?? 'AR', base?.lastMonth ?? null);
  const { entries, add } = useEntries();

  const [locOpen, setLocOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [showLegend, setShowLegend] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [place, setPlace] = useState<{ id: string; name: string; province: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ lat: number; lon: number; key: string } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [index, setIndex] = useState<HotspotIndex | null>(null);
  const [hotspots, setHotspots] = useState<GeoJSON.FeatureCollection>(EMPTY);
  const [fireIndex, setFireIndex] = useState<FireIndex | null>(null);
  const [fireGeo, setFireGeo] = useState(EMPTY_FIRES);
  const [grid, setGrid] = useState<GeoJSON.FeatureCollection | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  /* --- time cursor --- */
  const lastMonth = base?.lastMonth ?? 0;
  const lastDay = base ? dayFromIso(base.meta.lastDate) : 0;
  const forecastMonths = useMemo(() => base?.forecastMonths ?? [], [base]);
  const maxMonth = forecastMonths.length ? forecastMonths[forecastMonths.length - 1] : lastMonth;
  const month = Math.max(0, Math.min(maxMonth, urlMonth ?? lastMonth));
  // Day the cursor points at (day / week scales). Without ?d= it is the latest day, or the 1st of the chosen month.
  const cursorDay = useMemo(() => {
    if (month > lastMonth) { return lastDay; }
    const { year, month0 } = monthFromIndex(month);
    if (urlDay && urlDay <= daysInMonth(month)) { return Math.min(lastDay, dayIndex(year, month0, urlDay)); }
    return !hasMonth || month === lastMonth ? lastDay : monthStartDay(month);
  }, [month, lastMonth, lastDay, urlDay, hasMonth]);

  const cursor = scale === 'month' ? month : unitOfDay(scale, cursorDay);
  const maxUnit = scale === 'month' ? maxMonth : unitOfDay(scale, lastDay);
  const nowUnit = scale === 'month' ? lastMonth : unitOfDay(scale, lastDay);
  const isForecast = scale === 'month' && month > lastMonth;
  const win = useMemo(() => {
    if (isForecast) { return null; }
    const w = windowOf(scale, cursor);
    return { ...w, to: Math.min(w.to, lastDay) };
  }, [scale, cursor, isForecast, lastDay]);

  const commit = useCallback((i: number) => {
    if (scale === 'month') { update({ m: i, d: null }); return; }
    const d = Math.max(0, Math.min(lastDay, dayOfUnit(scale, i)));
    update({ m: monthOfDay(d), d: dateFromDay(d).getUTCDate() });
  }, [scale, lastDay, update]);

  const changeScale = useCallback((z: Scale) => {
    // Keep the same moment when switching scales.
    if (z === 'month' || scale !== 'month') { update({ z }); return; }
    update({ z, m: monthOfDay(cursorDay), d: dateFromDay(cursorDay).getUTCDate() });
  }, [scale, cursorDay, update]);

  /* --- load the fires (always) and the hotspots (hotspot view) of the window, or the forecast grid --- */
  useEffect(() => {
    if (!base) { return; }
    let alive = true;
    if (win) {
      setGrid(null);
      const months: string[] = [];
      for (let m = monthOfDay(Math.max(0, win.from)); m <= monthOfDay(win.to); m++) { months.push(ym(m)); }
      const t = setTimeout(() => { if (alive) { setLoading(view === 'fires' ? 'Cargando incendios…' : 'Cargando hotspots…'); } }, 150);
      Promise.all([
        Promise.all(months.map(getMonthFires)),
        view === 'hotspots' ? Promise.all(months.map(getMonthHotspots)) : Promise.resolve([]),
      ]).then(([fm, hm]) => {
        clearTimeout(t);
        if (!alive) { return; }
        const fireMonths = fm.filter(Boolean) as MonthFires[];
        const fw = sliceFires(fireMonths, win.from, win.to, win.fade);
        setFireIndex(indexFires(fw));
        setFireGeo(firesToGeoJSON(fw));
        if (view === 'hotspots') {
          const byMonth = new Map(fireMonths.map((m) => [m.month, m]));
          const w = sliceWindow(hm.filter(Boolean) as MonthHotspots[], byMonth, win.from, win.to, win.fade, sensor);
          setIndex(buildIndex(w));
          setHotspots(hotspotsToGeoJSON(w));
        } else {
          setIndex(null);
          setHotspots(EMPTY);
        }
        setLoading(null);
      });
      return () => { alive = false; clearTimeout(t); };
    }
    setIndex(null);
    setHotspots(EMPTY);
    setFireIndex(null);
    setFireGeo(EMPTY_FIRES);
    setLoading(null);
    if (base.prediction?.grid) {
      getPredictionGrid(ym(month)).then((g) => {
        if (!alive || !g) { return; }
        const h = g.step / 2;
        setGrid({
          type: 'FeatureCollection',
          features: g.lat.map((la, i) => ({
            type: 'Feature',
            properties: { p: g.p[i] },
            geometry: { type: 'Polygon', coordinates: [[[g.lon[i] - h, la - h], [g.lon[i] + h, la - h], [g.lon[i] + h, la + h], [g.lon[i] - h, la + h], [g.lon[i] - h, la - h]]] },
          })),
        });
      });
    } else {
      setGrid(null);
    }
    return () => { alive = false; };
  }, [base, win, month, view, sensor]);

  /* --- play: one unit of the current scale per tick --- */
  useEffect(() => {
    if (!playing) { return; }
    const t = setTimeout(() => {
      if (cursor >= maxUnit) { setPlaying(false); } else { commit(cursor + 1); }
    }, PLAY_MS[scale]);
    return () => clearTimeout(t);
  }, [playing, cursor, maxUnit, scale, commit]);

  /* --- weekly totals for the week scale --- */
  const weeks = useMemo(() => {
    if (!series) { return null; }
    const n = weekOfDay(lastDay) + 1;
    const km2 = new Float64Array(n);
    series.byDay.forEach((v, d) => { const w = weekOfDay(d); if (w >= 0 && w < n) { km2[w] += v.km2; } });
    return { km2, t: thresholds(Array.from(km2)) };
  }, [series, lastDay]);

  const regionEntries = useMemo(() => (region ? entries.filter((e) => entryInRegion(e, region)) : []), [entries, region]);
  const readAt = useCallback((lat: number, lon: number): Reading => (
    view === 'fires' ? readFires(fireIndex, lat, lon) : readPoint(index, lat, lon)
  ), [view, fireIndex, index]);
  const reading = useMemo(() => (point ? readAt(point.lat, point.lon) : null), [readAt, point]);

  /* Country / province figures for the map label: the province of the clicked point, else of the selected region. */
  const provinceId = place?.province ?? (region?.kind === 'province' ? region.id : region?.province) ?? null;
  const countrySeries = useRegionSeries('AR', base?.lastMonth ?? null);
  const provinceSeries = useRegionSeries(provinceId ?? 'AR', base?.lastMonth ?? null);

  const onMapClick = useCallback(async (lat: number, lon: number) => {
    setPoint({ lat, lon });
    setLocOpen(true);
    const depts = await getGeo('departments');
    setPlace(locate<{ id: string; name: string; province: string }>(depts, lon, lat));
  }, []);

  /* Tooltip: updated straight in the DOM (no re-render per mousemove), kept inside the map and above the cards. */
  const onHover = useCallback((h: { lat: number; lon: number; x: number; y: number } | null) => {
    const tip = tipRef.current;
    if (!tip) { return; }
    const r = h ? readAt(h.lat, h.lon) : null;
    if (!h || !r || r.n === 0) { tip.hidden = true; return; }
    const [title, detail] = tip.children as unknown as HTMLElement[];
    if (view === 'fires' && r.fire) {
      title.textContent = `Incendio · ${Math.round(r.fire.conf)} % de confianza`;
      detail.textContent = `${localDateTime(r.fire.start)} · ${fmtInt(r.fire.n)} hotspots · ${fmtKm2(r.fire.km2)} km²${r.nFires > 1 ? ` · ${r.nFires} incendios superpuestos` : ''}`;
    } else {
      title.textContent = `${r.pct} % de confianza`;
      detail.textContent = `Confianza ${r.band} · ${r.n === 1 ? '1 hotspot cubre' : `${r.n} hotspots cubren`} este punto`;
    }
    tip.hidden = false;
    const box = tip.parentElement!.getBoundingClientRect();
    const w = tip.offsetWidth;
    const hgt = tip.offsetHeight;
    const left = h.x + 16 + w < box.width - 12 ? h.x + 16 : Math.max(12, h.x - 16 - w);
    const top = Math.min(Math.max(12, h.y - hgt / 2), box.height - hgt - 12);
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;
  }, [readAt, view]);

  const selectEntry = useCallback((e: LogEntry) => {
    setSelected(e.id);
    setPoint({ lat: e.lat, lon: e.lon });
    setLocOpen(true);
    setFocus({ lat: e.lat, lon: e.lon, key: e.id + Date.now() });
    const d = dayFromIso(e.date);
    update({ m: monthOfDay(d), d: dateFromDay(d).getUTCDate() });
    getGeo('departments').then((depts) => setPlace(locate<{ id: string; name: string; province: string }>(depts, e.lon, e.lat)));
  }, [update]);

  const padding = useMemo(() => ({ top: 90, bottom: 170, left: locOpen ? 440 : 90, right: logOpen ? 450 : 90 }), [locOpen, logOpen]);

  if (!base || !region) { return <div className="map"><p className="loading">Cargando datos…</p></div>; }

  const predictionFor = (m: number) => base.prediction?.regions[region.id]?.[ym(m)] ?? null;
  const prediction = isForecast ? predictionFor(month) : null;

  /* --- timeline cells --- */
  const cellStyle = (i: number): CellStyle => {
    if (scale === 'month') {
      if (i <= lastMonth) { return { bg: series ? LEVEL_BG[level(series.monthKm2[i], series.monthThresholds)] : LEVEL_BG[0] }; }
      const p = predictionFor(i);
      if (!p || !series) { return { bg: 'var(--surface)', className: 'is-forecast is-empty' }; }
      return { bg: level(p.km2, series.monthThresholds) >= 3 ? 'var(--warn)' : 'var(--forecast)', className: 'is-forecast' };
    }
    if (scale === 'week') {
      return { bg: weeks ? LEVEL_BG[level(weeks.km2[i] ?? 0, weeks.t)] : LEVEL_BG[0] };
    }
    return { bg: series ? LEVEL_BG[level(series.byDay.get(i)?.km2 ?? 0, series.dayThresholds)] : LEVEL_BG[0] };
  };

  /* --- figures of the current window (day scale: the selected day only) --- */
  const windowTotals = (s: RegionSeries | null) => {
    let km2 = 0;
    let fires = -1; // -1 = not covered by the pipeline
    if (s && win) {
      for (let d = scale === 'day' ? win.to : win.from; d <= win.to; d++) {
        const v = s.byDay.get(d);
        if (v) { km2 += v.km2; if (v.nF >= 0) { fires = Math.max(0, fires) + v.nF; } }
      }
    }
    return { km2, fires };
  };
  const winKm2 = windowTotals(series).km2;
  const firesLabel = (s: RegionSeries | null) => {
    if (isForecast) { return '—'; }
    if (!s) { return '…'; }
    const f = windowTotals(s).fires;
    return f < 0 ? 's/d' : `${fmtInt(f)} ${f === 1 ? 'foco' : 'focos'}`;
  };

  const { month0 } = monthFromIndex(scale === 'month' ? month : monthOfDay(cursorDay));
  const timelineSubtitle = isForecast
    ? (prediction ? `Pronóstico: ${fmtKm2(prediction.km2)} km²` : 'Pronóstico pendiente')
    : series ? `${fmtKm2(winKm2)} km² con fuego${cursor === nowUnit ? ' · último dato' : ''}` : '';
  const first = monthFromIndex(0);
  const rangeText = `${MONTH_ABBR[first.month0]} ${first.year} a ${shortDate(base.meta.lastDate)} · pronóstico a ${forecastMonths.length} meses`;
  const cursorYear = dateFromDay(cursorDay).getUTCFullYear();
  const years = Array.from({ length: monthFromIndex(maxMonth).year - 2000 + 1 }, (_, k) => monthFromIndex(maxMonth).year - k);

  /* --- Ubicación card --- */
  const fire = reading?.fire ?? null;
  const fireStart = fire ? (fire.event?.start ?? fire.start) : null;
  const fireEnd = fire ? (fire.event?.end ?? null) : null;
  const provinceName = (id: string | null | undefined) => (id ? base.regionById.get(id)?.name ?? '' : '');
  const placeName = place ? `${place.name}, ${provinceName(place.province)}` : 'Fuera de Argentina';
  const anyCard = locOpen || filtersOpen || logOpen;

  const setSensor = (s: Sensor) => update({ v: 'hotspots', s });

  return (
    <div className={`map ${showLegend ? 'map--legend' : ''}`}>
      <MapCanvas
        view={view}
        fires={fireGeo}
        selectedFire={fire?.id ?? null}
        hotspots={hotspots}
        predictionGrid={grid}
        region={region}
        showEntries
        entries={regionEntries}
        selectedEntry={selected}
        point={point}
        padding={padding}
        focus={focus}
        onClick={onMapClick}
        onHover={onHover}
        onEntryClick={selectEntry}
      />
      {loading && <div className="status" role="status">{loading}</div>}

      <Header
        view="map"
        regions={base.regions}
        region={region}
        year={scale === 'month' ? monthFromIndex(month).year : cursorYear}
        years={years}
        query={query}
        onRegion={(id) => update({ r: id })}
        onYear={(y) => {
          if (scale === 'month') { update({ m: Math.max(0, Math.min(maxMonth, monthIndex(y, month0))), d: null }); return; }
          const f = dateFromDay(cursorDay);
          const d = Math.max(0, Math.min(lastDay, dayIndex(y, f.getUTCMonth(), f.getUTCDate())));
          update({ m: monthOfDay(d), d: dateFromDay(d).getUTCDate() });
        }}
      />

      {/* Always-visible map label: top-right; while a card is open it moves as far left as possible below the navbar. */}
      <div className={`map-stat ${anyCard ? (locOpen ? 'map-stat--after-card' : 'map-stat--after-rail') : ''}`} aria-live="polite">
        <span>Argentina: {firesLabel(countrySeries)}</span>
        {provinceId && <span>{provinceName(provinceId)}: {firesLabel(provinceSeries)}</span>}
      </div>

      <div className="dash dash--top-left">
        <DashMenu label="Ubicación" icon={<Icon.pin />} corner="top-left" open={locOpen} onOpen={() => setLocOpen(true)} onClose={() => setLocOpen(false)} className="loc-card">
          {point ? (
            <>
              <h2 className="loc-card__place">{placeName}</h2>
              <dl className="loc-card__grid">
                <div><dt>Latitud</dt><dd>{point.lat.toFixed(3)}°</dd></div>
                <div><dt>Longitud</dt><dd>{point.lon.toFixed(3)}°</dd></div>
                <div>
                  <dt>Probabilidad de fuego</dt>
                  {/* Fixed width: an invisible "100%" reserves the widest possible value. */}
                  <dd className="loc-card__big metric-value"><span className="metric-sizer" aria-hidden="true">100%</span><span>{isForecast || !reading ? '—' : `${reading.pct}%`}</span></dd>
                </div>
                <div><dt>Hotspots</dt><dd className="loc-card__big">{isForecast || !reading ? '—' : fmtInt(reading.nModis + reading.nViirs)}</dd></div>
                <div><dt>Inicio del incendio</dt><dd>{fireStart ? localDateTime(fireStart) : '—'}</dd></div>
                <div><dt>Fin del incendio</dt><dd>{fireEnd ? localDateTime(fireEnd) : '—'}</dd></div>
              </dl>
            </>
          ) : (
            <p className="loc-card__hint">Tocá un punto del mapa.</p>
          )}
        </DashMenu>
      </div>

      <div className="dash dash--bottom-left">
        <DashMenu label="Visualización" icon={<Icon.filter />} corner="bottom-left" open={filtersOpen} onOpen={() => setFiltersOpen(true)} onClose={() => setFiltersOpen(false)} className="filter-card">
          <div className="panel__eyebrow">Filtrar por</div>
          <button type="button" className="toggle" aria-pressed={view === 'fires'} onClick={() => update({ v: 'fires' })}><span className="toggle__poly" aria-hidden="true" />Ver focos</button>
          <button type="button" className="toggle" aria-pressed={view === 'hotspots'} onClick={() => update({ v: 'hotspots' })}><span className="toggle__dot" aria-hidden="true" />Ver hotspots</button>
          <div className="segmented segmented--small" role="group" aria-label="Sensor de los hotspots">
            {([['viirs', 'VIIRS'], ['modis', 'MODIS'], ['both', 'Ambos']] as [Sensor, string][]).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={view === 'hotspots' && sensor === id} onClick={() => setSensor(id)}>{label}</button>
            ))}
          </div>
          <div className="panel__eyebrow filter-card__sep">Mapa</div>
          <button type="button" className="toggle" aria-pressed={showLegend} onClick={() => setShowLegend(!showLegend)}><span className="toggle__legend" aria-hidden="true" />Leyenda</button>
        </DashMenu>
      </div>

      <div className="dash dash--top-right">
        <DashMenu label="Bitácora" icon={<Icon.log />} corner="top-right" open={logOpen} onOpen={() => setLogOpen(true)} onClose={() => setLogOpen(false)} className="log-menu">
          <FieldLog entries={regionEntries} selected={selected} regionName={region.name} onSelect={selectEntry} onNew={() => setFormOpen(true)} />
        </DashMenu>
      </div>

      {showLegend && (
        <div className="legend">
          <div className="legend-box">
            <span>{view === 'fires' ? 'Incendios: confianza combinada MODIS + VIIRS' : 'Hotspots: confianza del incendio al que pertenecen'}</span>
            <div className="legend-box__bar" aria-hidden="true">
              {[0.2, 0.42, 0.66, 0.92].map((a) => <span key={a} style={{ background: `rgba(232,89,12,${a})` }} />)}
            </div>
            <div className="legend-box__ends"><span>Baja</span><span>Muy alta</span></div>
          </div>
        </div>
      )}

      <Timeline
        scale={scale}
        cursor={cursor}
        max={maxUnit}
        now={nowUnit}
        cellStyle={cellStyle}
        subtitle={timelineSubtitle}
        rangeText={rangeText}
        playing={playing}
        onCommit={commit}
        onScale={changeScale}
        onPlay={() => setPlaying(!playing)}
      />

      <div className="map__tip" aria-hidden="true" hidden ref={tipRef}><strong /><span /></div>

      {formOpen && (
        <EntryForm
          point={point}
          defaultDate={isForecast ? base.meta.lastDate : isoFromDay(cursorDay)}
          onClose={() => setFormOpen(false)}
          onSaved={(e) => { add(e); setFormOpen(false); setSelected(e.id); }}
        />
      )}
    </div>
  );
}
