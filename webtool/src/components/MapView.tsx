'use client';
/*
 * Map view ("Mapa"), laid out like a data-analysis tool: square buttons open cards around the map.
 *   top-left  Ubicación: what is at the clicked point at the cursor time
 *   bottom-left Filtros: fires (main) or hotspots (VIIRS / MODIS / both)
 *   top-right Bitácora: field-log history of the region
 * plus an always-visible fire count (country / province) and the timeline.
 * Forecast days (after the last observed day, day scale) show the model's predicted hotspots in yellow,
 * with a warning that they are estimates.
 */
import dynamic from 'next/dynamic';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Header from './Header';
import FieldLog from './FieldLog';
import DashMenu from './Dash';
import EntryForm from './EntryForm';
import Timeline, { type CellStyle } from './Timeline';
import { Icon } from './icons';
import { entryInRegion, getGeo, getMonthFires, getMonthHotspots } from '@/lib/data';
import {
  coverageOf, forecastFires, forecastFireWindow, forecastToGeoJSON, forecastWindow, PRED_BG, PRED_SIZE_LABELS, predLevel, readForecast, type ForecastWindow,
} from '@/lib/forecast';
import { isWave } from '@/lib/incidents';
import {
  buildIndex, firesToGeoJSON, hotspotsToGeoJSON, indexFires, locate, readFires, readPoint, sliceFires, sliceWindow,
  type FireIndex, type HotspotIndex, type Reading,
} from '@/lib/geo';
import { incidentParam, useBaseData, useEntries, useRegionSeries, useUrlState, type Sensor } from '@/lib/hooks';
import { level, thresholds, type RegionSeries } from '@/lib/series';
import {
  dateFromDay, dayFromIso, dayIndex, daysInMonth, fmtInt, fmtKm2, isoFromDay, localDate, localDateTime, MONTH_ABBR,
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
  const { regionId, month: urlMonth, day: urlDay, scale, view, sensor, point, hasMonth, update, query } = useUrlState(base?.lastMonth ?? null);
  const region: Region | null = base?.regionById.get(regionId) ?? base?.regionById.get('AR') ?? null;
  const series = useRegionSeries(region?.id ?? 'AR', base?.lastMonth ?? null);
  const { entries, add } = useEntries();

  // The selected point lives in the URL (?pt=) so the calendar can pick it up; its card starts open when there is one.
  const [locOpen, setLocOpen] = useState(point !== null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [showLegend, setShowLegend] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [place, setPlace] = useState<{ id: string; name: string; province: string } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<{ lat: number; lon: number; key: string } | null>(null);
  const [playing, setPlaying] = useState(false);
  const [index, setIndex] = useState<HotspotIndex | null>(null);
  const [hotspots, setHotspots] = useState<GeoJSON.FeatureCollection>(EMPTY);
  const [fireIndex, setFireIndex] = useState<FireIndex | null>(null);
  const [fireGeo, setFireGeo] = useState(EMPTY_FIRES);
  const [predWin, setPredWin] = useState<ForecastWindow | null>(null);
  const [predFireIndex, setPredFireIndex] = useState<FireIndex | null>(null);
  const [predFireGeo, setPredFireGeo] = useState(EMPTY_FIRES);
  const [creditsOpen, setCreditsOpen] = useState(false);
  const [loading, setLoading] = useState<string | null>(null);
  const tipRef = useRef<HTMLDivElement>(null);

  /* --- time cursor --- */
  const lastMonth = base?.lastMonth ?? 0;
  const lastDay = base ? dayFromIso(base.meta.lastDate) : 0;
  const forecast = base?.forecast ?? null;
  // The day scale continues into the forecast days; weeks and months stop at the last observed day.
  const maxDay = scale === 'day' && forecast ? forecast.to : lastDay;
  const maxMonth = monthOfDay(maxDay);
  const month = Math.max(0, Math.min(maxMonth, urlMonth ?? lastMonth));
  // Day the cursor points at (day / week scales). Without ?d= it is the latest day, or the 1st of the chosen month.
  const cursorDay = useMemo(() => {
    const { year, month0 } = monthFromIndex(month);
    if (urlDay && urlDay <= daysInMonth(month)) { return Math.min(maxDay, dayIndex(year, month0, urlDay)); }
    return !hasMonth || month === lastMonth ? lastDay : monthStartDay(month);
  }, [month, lastMonth, lastDay, maxDay, urlDay, hasMonth]);

  const maxUnit = scale === 'month' ? maxMonth : unitOfDay(scale, maxDay);
  const cursor = Math.min(maxUnit, scale === 'month' ? month : unitOfDay(scale, cursorDay));
  const nowUnit = scale === 'month' ? lastMonth : unitOfDay(scale, lastDay);
  const isForecast = scale === 'day' && cursorDay > lastDay;
  const win = useMemo(() => {
    const w = windowOf(scale, cursor);
    return { ...w, to: Math.min(w.to, isForecast ? maxDay : lastDay) };
  }, [scale, cursor, isForecast, lastDay, maxDay]);

  const commit = useCallback((i: number) => {
    if (scale === 'month') { update({ m: i, d: null }); return; }
    const d = Math.max(0, Math.min(maxDay, dayOfUnit(scale, i)));
    update({ m: monthOfDay(d), d: dateFromDay(d).getUTCDate() });
  }, [scale, maxDay, update]);

  const changeScale = useCallback((z: Scale) => {
    // Keep the same moment when switching scales.
    if (z === 'month' || scale !== 'month') { update({ z }); return; }
    update({ z, m: monthOfDay(cursorDay), d: dateFromDay(cursorDay).getUTCDate() });
  }, [scale, cursorDay, update]);

  /* --- load the fires (always) and the hotspots (hotspot view) of the window; forecast days: predicted hotspots --- */
  useEffect(() => {
    if (!base) { return; }
    if (isForecast && forecast) {
      // Predicted fires (outlines) and hotspots of the forecast days up to the cursor (earlier forecast days fade out).
      const from = Math.max(forecast.from, win.from);
      const fw = forecastFireWindow(forecast, from, win.to);
      setPredFireIndex(indexFires(fw));
      setPredFireGeo(firesToGeoJSON(fw));
      setPredWin(forecastWindow(forecast, from, win.to));
      setIndex(null);
      setHotspots(EMPTY);
      setFireIndex(null);
      setFireGeo(EMPTY_FIRES);
      setLoading(null);
      return;
    }
    setPredWin(null);
    setPredFireIndex(null);
    setPredFireGeo(EMPTY_FIRES);
    let alive = true;
    const months: string[] = [];
    for (let m = monthOfDay(Math.max(0, win.from)); m <= monthOfDay(win.to); m++) { months.push(ym(m)); }
    const t = setTimeout(() => { if (alive) { setLoading(view === 'fires' ? 'Cargando fires…' : 'Cargando hotspots…'); } }, 150);
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
  }, [base, win, view, sensor, isForecast, forecast]);
  const predGeo = useMemo(() => forecastToGeoJSON(predWin), [predWin]);

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
  const reading = useMemo(() => (point && !isForecast ? readAt(point.lat, point.lon) : null), [readAt, point, isForecast]);
  /*
   * Forecast reading: predicted fire outlines (fires view) or predicted cells (hotspots view).
   * No percentage on purpose: the model only exports cells scoring ≥ 0.8, so its score is always 80–100 %
   * and would look far more certain than the historical confidence (median ≈ 48 % in Córdoba).
   * `n` = hotspots of the predicted fire under the point (its size, which also drives the colour).
   */
  const readPred = useCallback((lat: number, lon: number) => {
    if (view === 'fires') {
      const r = readFires(predFireIndex, lat, lon);
      return { covered: r.n > 0, n: r.fire?.n ?? 0, event: r.fire?.event ?? null, fire: r.fire };
    }
    const r = readForecast(predWin, lat, lon);
    return { covered: r.n > 0, n: r.fire?.n ?? r.n, event: r.event, fire: r.fire };
  }, [view, predFireIndex, predWin]);
  const predReading = useMemo(() => (point && isForecast ? readPred(point.lat, point.lon) : null), [point, isForecast, readPred]);

  /* Country / province figures for the map label: the province of the clicked point, else of the selected region. */
  const provinceId = place?.province ?? (region?.kind === 'province' ? region.id : region?.province) ?? null;
  const countrySeries = useRegionSeries('AR', base?.lastMonth ?? null);
  const provinceSeries = useRegionSeries(provinceId ?? 'AR', base?.lastMonth ?? null);

  const onMapClick = useCallback((lat: number, lon: number) => {
    update({ pt: { lat, lon } });
    setLocOpen(true);
  }, [update]);

  // Department / province of the selected point.
  useEffect(() => {
    if (!point) { setPlace(null); return; }
    let alive = true;
    getGeo('departments').then((depts) => {
      if (alive) { setPlace(locate<{ id: string; name: string; province: string }>(depts, point.lon, point.lat)); }
    });
    return () => { alive = false; };
  }, [point]);

  /* Tooltip: updated straight in the DOM (no re-render per mousemove), kept inside the map and above the cards. */
  const onHover = useCallback((h: { lat: number; lon: number; x: number; y: number } | null) => {
    const tip = tipRef.current;
    if (!tip) { return; }
    const [title, detail] = tip.children as unknown as HTMLElement[];
    if (h && isForecast) {
      // Forecast day: predicted fires / hotspots only.
      const fr = readPred(h.lat, h.lon);
      if (!fr.covered) { tip.hidden = true; return; }
      tip.classList.add('map__tip--forecast');
      const wave = fr.event && isWave(fr.event.start, fr.event.end);
      title.textContent = `Fire estimado · ${fr.n === 1 ? '1 hotspot' : `${fmtInt(fr.n)} hotspots`}`;
      detail.textContent = fr.fire
        ? `${fmtKm2(fr.fire.polyKm2)} km² · ${wave ? `parte de un firewave estimado del ${localDate(fr.event!.start)} al ${localDate(fr.event!.end)}` : localDate(fr.fire.start)}`
        : fr.event
        ? `${fr.n === 1 ? '1 hotspot estimado' : `${fr.n} hotspots estimados`} · ${isWave(fr.event.start, fr.event.end) ? 'firewave estimado' : 'fire estimado'} del ${localDate(fr.event.start)} al ${localDate(fr.event.end)}`
        : `${fr.n === 1 ? '1 hotspot estimado cubre' : `${fr.n} hotspots estimados cubren`} este punto`;
    } else {
    tip.classList.remove('map__tip--forecast');
    const r = h ? readAt(h.lat, h.lon) : null;
    if (!h || !r || r.n === 0) { tip.hidden = true; return; }
    if (view === 'fires' && r.fire) {
      title.textContent = `Fire · ${Math.round(r.fire.conf)} % de confianza`;
      const wave = r.fire.event && isWave(r.fire.event.start, r.fire.event.end) ? ' · parte de un firewave' : '';
      detail.textContent = `${localDateTime(r.fire.start)} · ${fmtInt(r.fire.n)} hotspots · ${fmtKm2(r.fire.km2)} km²${r.nFires > 1 ? ` · ${r.nFires} fires superpuestos` : ''}${wave}`;
    } else {
      title.textContent = `${r.pct} % de confianza`;
      detail.textContent = `Confianza ${r.band} · ${r.n === 1 ? '1 hotspot cubre' : `${r.n} hotspots cubren`} este punto`;
    }
    }
    if (!h) { return; }
    tip.hidden = false;
    const box = tip.parentElement!.getBoundingClientRect();
    const w = tip.offsetWidth;
    const hgt = tip.offsetHeight;
    const left = h.x + 16 + w < box.width - 12 ? h.x + 16 : Math.max(12, h.x - 16 - w);
    const top = Math.min(Math.max(12, h.y - hgt / 2), box.height - hgt - 12);
    tip.style.left = `${Math.round(left)}px`;
    tip.style.top = `${Math.round(top)}px`;
  }, [readAt, view, isForecast, readPred]);

  const selectEntry = useCallback((e: LogEntry) => {
    setSelected(e.id);
    setLocOpen(true);
    setFocus({ lat: e.lat, lon: e.lon, key: e.id + Date.now() });
    const d = dayFromIso(e.date);
    update({ pt: { lat: e.lat, lon: e.lon }, m: monthOfDay(d), d: dateFromDay(d).getUTCDate() });
  }, [update]);

  const padding = useMemo(() => ({ top: 90, bottom: 170, left: locOpen ? 440 : 90, right: logOpen ? 450 : 90 }), [locOpen, logOpen]);

  if (!base || !region) { return <div className="map"><p className="loading">Cargando datos…</p></div>; }

  const coverage = coverageOf(forecast, region);
  const predFires = (r: Region | null | undefined, d: number) => (r ? forecastFires(forecast, r, d) : null);

  /* --- timeline cells (forecast days in yellow, relative to the busiest forecast day of the region) --- */
  const predMax = forecast ? Math.max(1, ...(forecast.p.counts[region.id]?.fires ?? [0])) : 1;
  const cellStyle = (i: number): CellStyle => {
    if (scale === 'month') {
      return { bg: series ? LEVEL_BG[level(series.monthKm2[i], series.monthThresholds)] : LEVEL_BG[0] };
    }
    if (scale === 'week') {
      return { bg: weeks ? LEVEL_BG[level(weeks.km2[i] ?? 0, weeks.t)] : LEVEL_BG[0] };
    }
    if (i > lastDay) {
      const n = predFires(region, i);
      if (n === null) { return { bg: 'var(--surface)', className: 'is-forecast is-empty' }; }
      return { bg: PRED_BG[predLevel(n, predMax)], className: 'is-forecast' };
    }
    return { bg: series ? LEVEL_BG[level(series.byDay.get(i)?.km2 ?? 0, series.dayThresholds)] : LEVEL_BG[0] };
  };

  /* --- figures of the current window (day scale: the selected day only) --- */
  const windowTotals = (s: RegionSeries | null) => {
    let km2 = 0;
    let fires = -1; // -1 = not covered by the pipeline
    if (s && !isForecast) {
      for (let d = scale === 'day' ? win.to : win.from; d <= win.to; d++) {
        const v = s.byDay.get(d);
        if (v) { km2 += v.km2; if (v.nF >= 0) { fires = Math.max(0, fires) + v.nF; } }
      }
    }
    return { km2, fires };
  };
  const winKm2 = windowTotals(series).km2;
  const firesLabel = (s: RegionSeries | null, r: Region | null | undefined) => {
    if (isForecast) {
      const n = predFires(r, cursorDay);
      if (n === null) { return 'sin pronóstico'; }
      const partial = r && coverageOf(forecast, r) === 'partial' ? ` (solo ${forecast?.p.coverage.name})` : '';
      return `${fmtInt(n)} ${n === 1 ? 'fire estimado' : 'fires estimados'}${partial}`;
    }
    if (!s) { return '…'; }
    const f = windowTotals(s).fires;
    return f < 0 ? 's/d' : `${fmtInt(f)} ${f === 1 ? 'fire' : 'fires'}`;
  };

  const { month0 } = monthFromIndex(scale === 'month' ? month : monthOfDay(cursorDay));
  const cursorPred = isForecast ? predFires(region, cursorDay) : null;
  const timelineSubtitle = isForecast
    ? (cursorPred === null ? `Sin pronóstico para ${region.name}` : `Estimación: ${fmtInt(cursorPred)} ${cursorPred === 1 ? 'fire' : 'fires'} en ${region.name}`)
    : series ? `${fmtKm2(winKm2)} km² con fuego${cursor === nowUnit ? ' · último dato' : ''}` : '';
  const first = monthFromIndex(0);
  const rangeText = `${MONTH_ABBR[first.month0]} ${first.year} a ${shortDate(base.meta.lastDate)}`
    + (forecast ? ` · pronóstico al ${shortDate(isoFromDay(forecast.to))}${scale === 'day' ? '' : ' (escala Días)'}` : '');
  const cursorYear = dateFromDay(cursorDay).getUTCFullYear();
  const years = Array.from({ length: monthFromIndex(maxMonth).year - 2000 + 1 }, (_, k) => monthFromIndex(maxMonth).year - k);

  /* --- Ubicación card --- */
  const fire = reading?.fire ?? null;
  const ev = isForecast ? predReading?.event ?? null : fire?.event ?? null;
  const evStart = isForecast ? ev?.start ?? null : fire ? (fire.event?.start ?? fire.start) : null;
  const evEnd = ev?.end ?? null;
  const evWord = ev && isWave(ev.start, ev.end) ? 'del firewave' : 'del fire';
  // Firewave of the selected fire (several days): outlined on the map in the fires view.
  const selFire = isForecast ? predReading?.fire ?? null : fire;
  const waveId = view === 'fires' && selFire?.event && isWave(selFire.event.start, selFire.event.end) ? selFire.event.id : null;
  const fmtWhen = (s: string) => (isForecast ? localDate(s) : localDateTime(s));
  const provinceName = (id: string | null | undefined) => (id ? base.regionById.get(id)?.name ?? '' : '');
  const placeName = place ? `${place.name}, ${provinceName(place.province)}` : 'Fuera de Argentina';
  const anyCard = locOpen || filtersOpen || logOpen;
  const provinceRegion = provinceId ? base.regionById.get(provinceId) : null;

  const setSensor = (s: Sensor) => update({ v: 'hotspots', s });

  /* Link to the calendar: centered on the clicked place (its department) and on the fire event ("fire") there. */
  const incident = fire?.event ? { month: ym(monthOfDay(fire.day)), id: fire.event.id } : null;
  const calendarQuery = (() => {
    const q = new URLSearchParams(query);
    if (place) { q.set('r', place.id); }
    if (incident) { q.set('ev', incidentParam(incident)); } else { q.delete('ev'); }
    return q.toString();
  })();
  const incidentRef = fire?.event ? { id: fire.event.id, start: fire.event.start, end: fire.event.end } : null;

  return (
    <div className={`map ${showLegend ? 'map--legend' : ''}`}>
      <MapCanvas
        view={view}
        fires={fireGeo}
        selectedFire={(isForecast ? predReading?.fire?.id : fire?.id) ?? null}
        selectedWave={waveId}
        hotspots={hotspots}
        forecast={view === 'hotspots' ? predGeo : EMPTY}
        forecastFires={view === 'fires' ? predFireGeo : EMPTY_FIRES}
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
        otherQuery={calendarQuery}
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
        <span>Argentina: {firesLabel(countrySeries, base.regionById.get('AR'))}</span>
        {provinceId && <span>{provinceName(provinceId)}: {firesLabel(provinceSeries, provinceRegion)}</span>}
      </div>

      <div className="dash dash--top-left">
        <DashMenu label={isForecast ? 'Ubicación · estimación' : 'Ubicación'} icon={<Icon.pin />} corner="top-left" open={locOpen} onOpen={() => setLocOpen(true)} onClose={() => setLocOpen(false)} className={`loc-card ${isForecast ? 'loc-card--forecast' : ''}`}>
          {point ? (
            <>
              <h2 className="loc-card__place">{placeName}</h2>
              <dl className="loc-card__grid">
                <div><dt>Latitud</dt><dd>{point.lat.toFixed(3)}°</dd></div>
                <div><dt>Longitud</dt><dd>{point.lon.toFixed(3)}°</dd></div>
                {isForecast ? (
                  /* Forecast: size of the predicted fire, never the model score (see readPred). */
                  <>
                    <div><dt>Hotspots estimados</dt><dd className="loc-card__big">{predReading?.covered ? fmtInt(predReading.n) : '—'}</dd></div>
                    <div><dt>Superficie estimada</dt><dd className="loc-card__big">{predReading?.fire ? <>{fmtKm2(predReading.fire.polyKm2)}<small> km²</small></> : '—'}</dd></div>
                  </>
                ) : (
                  <>
                    <div>
                      <dt>Probabilidad de fuego</dt>
                      {/* Fixed width: an invisible "100%" reserves the widest possible value. */}
                      <dd className="loc-card__big metric-value"><span className="metric-sizer" aria-hidden="true">100%</span><span>{reading ? `${reading.pct}%` : '—'}</span></dd>
                    </div>
                    <div><dt>Hotspots</dt><dd className="loc-card__big">{reading ? fmtInt(reading.nModis + reading.nViirs) : '—'}</dd></div>
                  </>
                )}
                <div><dt>Inicio {evWord}</dt><dd>{evStart ? fmtWhen(evStart) : '—'}</dd></div>
                <div><dt>Fin {evWord}</dt><dd>{evEnd ? fmtWhen(evEnd) : '—'}</dd></div>
              </dl>
            </>
          ) : (
            <p className="loc-card__hint">Tocá un punto del mapa.</p>
          )}
        </DashMenu>
      </div>

      <div className="dash dash--bottom-left">
        <DashMenu label="Visualización" icon={<Icon.filter />} corner="bottom-left" open={filtersOpen} onOpen={() => setFiltersOpen(true)} onClose={() => setFiltersOpen(false)} className="filter-card">
          <div className="panel__eyebrow">Ver en el mapa</div>
          <button type="button" className="toggle" aria-pressed={view === 'fires'} onClick={() => update({ v: 'fires' })}><span className="toggle__poly" aria-hidden="true" />Ver fires</button>
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

      <div className="legend">
        {showLegend && (
          <div className={`legend-box ${isForecast ? 'legend-box--forecast' : ''}`}>
            <span>{isForecast ? 'Pronóstico: hotspots estimados por fire' : view === 'fires' ? 'Fires: confianza combinada MODIS + VIIRS' : 'Hotspots: confianza del fire al que pertenecen'}</span>
            <div className="legend-box__bar" aria-hidden="true">
              {(isForecast ? PRED_BG.slice(1) : [0.2, 0.42, 0.66, 0.92].map((a) => `rgba(232,89,12,${a})`)).map((c) => <span key={c} style={{ background: c }} />)}
            </div>
            {waveId && <div className="legend-box__wave"><span aria-hidden="true" />Firewave del fire seleccionado</div>}
            {isForecast
              ? <div className="legend-box__steps">{PRED_SIZE_LABELS.map((l) => <span key={l}>{l}</span>)}</div>
              : <div className="legend-box__ends"><span>Baja</span><span>Muy alta</span></div>}
          </div>
        )}
        {/* Data credits (replaces the map's bottom-right attribution button). */}
        <div className="credits">
          {creditsOpen && <span className="credits__text">Hotspots: NASA FIRMS · Fires, firewaves y pronóstico: equipo Firewall · Límites: IGN</span>}
          <button type="button" className="credits__btn" aria-expanded={creditsOpen} aria-label="Fuentes de los datos" onClick={() => setCreditsOpen(!creditsOpen)}>i</button>
        </div>
      </div>

      {isForecast && (
        <div className="forecast-alert" role="alert">
          <span className="note__bang" aria-hidden="true">!</span>
          <p>
            <strong>Cuidado: esto es una estimación.</strong>{' '}
            {coverage === 'none'
              ? `El modelo todavía no cubre ${region.name}; hoy solo pronostica ${forecast?.p.coverage.name}.`
              : `Son hotspots que el modelo predice para ${forecast?.p.coverage.name}, no detecciones satelitales. Puede haber fallas.`}
          </p>
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
          incident={isForecast ? null : incidentRef}
          defaultDate={isForecast ? base.meta.lastDate : isoFromDay(cursorDay)}
          onClose={() => setFormOpen(false)}
          onSaved={(e) => { add(e); setFormOpen(false); setSelected(e.id); }}
        />
      )}
    </div>
  );
}
