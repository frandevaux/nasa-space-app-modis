'use client';
/*
 * Calendar view ("Calendario"): eight fire seasons week by week, plus a week / month / season calendar.
 * Same dashboard system as the map: stacked square buttons on the left (place, selected date, field log). Everything is centered on the clicked date and on the place / fire picked
 * here or on the map (?pt=, ?ev=), so field-log entries can be linked to that fire.
 */
import { useCallback, useMemo, useState } from 'react';
import Header from './Header';
import FieldLog, { KIND_LABEL } from './FieldLog';
import DashMenu from './Dash';
import EntryForm from './EntryForm';
import PlaceMenu, { useIncident } from './PlaceMenu';
import { Icon } from './icons';
import { entryInRegion } from '@/lib/data';
import { forecastFires, PRED_BG, predLevel } from '@/lib/forecast';
import { useBaseData, useEntries, useRegionSeries, useUrlState } from '@/lib/hooks';
import { level, thresholds, type DayValue } from '@/lib/series';
import {
  dayFromIso, dayIndex, daysInMonth, fmtInt, fmtKm2, isoFromDay, monthFromIndex, monthIndex, monthOfDay,
  MONTH_NAMES, monthTitle, shortDate, weekdayMonFirst,
} from '@/lib/time';
import type { LogEntry, Region } from '@/lib/types';

const LVL = ['var(--lvl-0)', 'var(--lvl-1)', 'var(--lvl-2)', 'var(--lvl-3)', 'var(--lvl-4)'];
const DAY_BG = ['var(--day-0)', 'var(--day-1)', 'var(--day-2)', 'var(--day-3)', 'var(--day-4)'];
const WEEKDAYS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const SEASON_MONTHS = ['Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun'];
const N_SEASONS = 8;

type Scale = 'week' | 'month' | 'season';


export default function CalendarView() {
  const base = useBaseData();
  const { regionId, month: urlMonth, day: urlDay, point, incident: incidentRef, update, query } = useUrlState(base?.lastMonth ?? null);
  const region: Region | null = base?.regionById.get(regionId) ?? base?.regionById.get('AR') ?? null;
  const series = useRegionSeries(region?.id ?? 'AR', base?.lastMonth ?? null);
  const { entries, add } = useEntries();
  const incident = useIncident(incidentRef);

  const [scale, setScale] = useState<Scale>('month');
  const [selected, setSelected] = useState<string | null>(null);
  const [placeOpen, setPlaceOpen] = useState(true);
  const [dateOpen, setDateOpen] = useState(true);
  const [logOpen, setLogOpen] = useState(false);
  const [formOpen, setFormOpen] = useState(false);

  const lastMonth = base?.lastMonth ?? 0;
  const lastDay = base ? dayFromIso(base.meta.lastDate) : 0;
  // Days processed by the pipeline have fires (fires); the rest only raw hotspot counts.
  const pipeFrom = base?.meta.pipeline ? dayFromIso(base.meta.pipeline.from) : Infinity;
  const pipeTo = base?.meta.pipeline ? dayFromIso(base.meta.pipeline.to) : -Infinity;
  const month = Math.max(0, Math.min(lastMonth, urlMonth ?? lastMonth));
  const { year, month0 } = monthFromIndex(month);
  const nDays = daysInMonth(month);
  const dom = urlDay && urlDay <= nDays ? urlDay : null;

  const regionEntries = useMemo(() => (region ? entries.filter((e) => entryInRegion(e, region)) : []), [entries, region]);
  const entriesByDay = useMemo(() => {
    const m = new Map<number, LogEntry[]>();
    for (const e of regionEntries) {
      const d = dayFromIso(e.date);
      m.set(d, [...(m.get(d) ?? []), e]);
    }
    return m;
  }, [regionEntries]);

  const dayValue = useCallback((d: number): DayValue => series?.byDay.get(d) ?? { nM: 0, nV: 0, km2: 0, nF: d >= pipeFrom && d <= pipeTo ? 0 : -1 }, [series, pipeFrom, pipeTo]);
  const goDay = useCallback((d: number) => {
    const f = new Date(Date.parse(isoFromDay(d)));
    update({ m: monthOfDay(d), d: f.getUTCDate() });
  }, [update]);

  /* --- eight seasons, week by week --- */
  const seasonStart = month0 >= 6 ? year : year - 1;
  const seasonRows = useMemo(() => {
    if (!series) { return null; }
    const rows = [];
    for (let s = seasonStart - N_SEASONS + 1; s <= seasonStart; s++) {
      const d0 = dayIndex(s, 6, 1);
      const weeks: { d0: number; km2: number; future: boolean }[] = [];
      for (let w = 0; w < 52; w++) {
        let k = 0;
        for (let j = 0; j < 7; j++) { k += series.byDay.get(d0 + 7 * w + j)?.km2 ?? 0; }
        weeks.push({ d0: d0 + 7 * w, km2: k, future: d0 + 7 * w > lastDay || d0 + 7 * w < 0 });
      }
      rows.push({ season: s, weeks });
    }
    return { rows, t: thresholds(rows.flatMap((r) => r.weeks.map((w) => w.km2))) };
  }, [series, seasonStart, lastDay]);

  if (!base || !region) { return <div className="cal"><p className="loading">Cargando datos…</p></div>; }

  const monthD0 = dayIndex(year, month0, 1);
  const monthD1 = monthD0 + nDays - 1;
  const years = Array.from({ length: monthFromIndex(lastMonth).year - 2000 + 1 }, (_, k) => monthFromIndex(lastMonth).year - k);
  // Selected date: the clicked day, else the latest day with data (current month) or the 1st of the month.
  const selDay = dom ? monthD0 + dom - 1 : month === lastMonth ? lastDay : monthD0;
  const forecast = base.forecast;
  const predMax = Math.max(1, ...(forecast?.p.counts[region.id]?.fires ?? [0]));

  function dayCell(d: number, big = false) {
    const v = dayValue(d);
    // Forecast days (after the last observed day): yellow, with the model's estimate.
    const pred = d > lastDay ? forecastFires(forecast, region!, d) : null;
    const isPred = d > lastDay && !!forecast && d <= forecast.to;
    const out = d > lastDay && !isPred;
    const lvl = d <= lastDay ? level(v.km2, series?.dayThresholds ?? []) : 0;
    const bg = isPred ? (pred === null ? 'var(--surface)' : PRED_BG[predLevel(pred, predMax)]) : DAY_BG[lvl];
    const evs = entriesByDay.get(d) ?? [];
    const f = new Date(Date.parse(isoFromDay(d)));
    const n = v.nM + v.nV;
    const isSel = d === selDay;
    return (
      <div
        key={d}
        role="button"
        tabIndex={out ? -1 : 0}
        className={`day ${isSel ? 'is-selected' : ''} ${out ? 'is-out' : ''} ${isPred ? 'is-forecast' : ''}`}
        style={{ background: bg, borderColor: isPred ? '#E5CF6A' : lvl === 0 ? 'var(--line)' : DAY_BG[lvl], opacity: out ? 0.45 : 1 }}
        aria-label={isPred
          ? `${f.getUTCDate()} de ${MONTH_NAMES[f.getUTCMonth()].toLowerCase()}: ${pred === null ? 'sin pronóstico' : `${pred} ${pred === 1 ? 'fire estimado' : 'fires estimados'}`}`
          : `${f.getUTCDate()} de ${MONTH_NAMES[f.getUTCMonth()].toLowerCase()}: ${v.nF >= 0 ? `${v.nF} fires` : `${n} hotspots`}, ${fmtKm2(v.km2)} km²`}
        onClick={() => { if (!out) { goDay(d); } }}
        onKeyDown={(e) => { if (!out && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); goDay(d); } }}
      >
        <div>
          <div className="day__top">
            <span>{big ? `${WEEKDAYS[weekdayMonFirst(f.getUTCFullYear(), f.getUTCMonth(), f.getUTCDate())]} ${f.getUTCDate()}` : f.getUTCDate()}</span>
            {d <= lastDay && v.km2 > 0 && <span>{fmtKm2(v.km2)} km²</span>}
            {isPred && <span className="day__pred-tag">Estimado</span>}
          </div>
          {isPred && <div className="day__km2">{pred === null ? 'Sin pronóstico' : `≈ ${fmtInt(pred)} ${pred === 1 ? 'fire' : 'fires'}`}</div>}
          {d <= lastDay && (v.nF > 0 || (v.nF < 0 && n > 0)) && (
            <div className="day__km2">{v.nF >= 0 ? (v.nF === 1 ? '1 fire' : `${fmtInt(v.nF)} fires`) : (n === 1 ? '1 hotspot' : `${fmtInt(n)} hotspots`)}</div>
          )}
          {big && d <= lastDay && (
            <div className="day__sensors">{v.nF >= 0 && <span>Fires: {fmtInt(v.nF)}</span>}<span>Hotspots MODIS: {fmtInt(v.nM)}</span><span>Hotspots VIIRS: {fmtInt(v.nV)}</span></div>
          )}
        </div>
        <div className="day__events">
          {evs.slice(0, big ? 6 : 2).map((e) => (
            <button key={e.id} type="button" className="event" aria-pressed={selected === e.id} aria-label={e.kind ? `${KIND_LABEL[e.kind]}: ${e.title}` : e.title}
              onClick={(ev) => { ev.stopPropagation(); setSelected(e.id); setLogOpen(true); }}>
              {big || !e.kind ? e.title : KIND_LABEL[e.kind]}
            </button>
          ))}
          {evs.length > (big ? 6 : 2) && <span className="hint">+{evs.length - (big ? 6 : 2)} más</span>}
        </div>
      </div>
    );
  }

  /* --- center card: week / month / season --- */
  let body: React.ReactNode;
  let title = monthTitle(month);
  if (scale === 'month') {
    const blanks = weekdayMonFirst(year, month0, 1);
    const cells: React.ReactNode[] = Array.from({ length: blanks }, (_, i) => <div key={`b${i}`} className="day" style={{ background: 'transparent', cursor: 'default' }} />);
    for (let d = monthD0; d <= monthD1; d++) { cells.push(dayCell(d)); }
    while (cells.length % 7 !== 0) { cells.push(<div key={`a${cells.length}`} className="day" style={{ background: 'transparent', cursor: 'default' }} />); }
    body = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div className="weekdays">{WEEKDAYS.map((x) => <span key={x}>{x}</span>)}</div>
        <div className="days">{cells}</div>
      </div>
    );
  } else if (scale === 'week') {
    const ref = dom ? monthD0 + dom - 1 : monthD0;
    const f = new Date(Date.parse(isoFromDay(ref)));
    const w0 = ref - weekdayMonFirst(f.getUTCFullYear(), f.getUTCMonth(), f.getUTCDate());
    title = `Semana del ${shortDate(isoFromDay(w0))}`;
    body = <div className="week-grid">{Array.from({ length: 7 }, (_, j) => dayCell(w0 + j, true))}</div>;
  } else {
    title = `Temporada ${seasonStart}/${String((seasonStart + 1) % 100).padStart(2, '0')}`;
    const ms = Array.from({ length: 12 }, (_, k) => monthIndex(seasonStart, 6 + k));
    body = (
      <div className="season-grid">
        {ms.map((m) => {
          const out = m > lastMonth || m < 0;
          const v = out || !series ? 0 : series.monthKm2[m];
          const lvl = out || !series ? 0 : level(v, series.monthThresholds);
          const { month0: m0, year: y } = monthFromIndex(m);
          return (
            <button key={m} type="button" disabled={out} style={{ background: DAY_BG[lvl], opacity: out ? 0.45 : 1 }}
              onClick={() => { update({ m, d: null }); setScale('month'); }}>
              <strong>{MONTH_NAMES[m0]} {y}</strong>
              <span>{out ? 'Sin datos' : `${fmtKm2(v)} km²`}</span>
            </button>
          );
        })}
      </div>
    );
  }

  function shift(dir: -1 | 1) {
    if (scale === 'week') {
      const ref = (dom ? monthD0 + dom - 1 : monthD0) + 7 * dir;
      if (ref >= 0 && ref <= (forecast?.to ?? lastDay)) { goDay(ref); }
    } else if (scale === 'season') {
      update({ m: Math.max(0, Math.min(lastMonth, month + 12 * dir)), d: null });
    } else {
      update({ m: Math.max(0, Math.min(lastMonth, month + dir)), d: null });
    }
  }

  const selValue = dayValue(selDay);
  const selPred = forecastFires(forecast, region, selDay);
  const selDate = new Date(Date.parse(isoFromDay(selDay)));
  // Location breadcrumb: País › Provincia › Departamento; the selected one is the title.
  const ancestors: Region[] = region.kind === 'country' ? []
    : region.kind === 'province' ? [base.regionById.get('AR')!]
      : [base.regionById.get('AR')!, base.regionById.get(region.province ?? '')!].filter(Boolean);

  const monthCard = (
    <div className="panel card card--month">
      <div className="card__head">
        <div>
          <button type="button" className="nav-btn" aria-label="Anterior" onClick={() => shift(-1)}><span><Icon.left /></span></button>
          <button type="button" className="nav-btn" aria-label="Siguiente" onClick={() => shift(1)}><span><Icon.right /></span></button>
          <h2 className="month">{title}</h2>
        </div>
        <div>
          <div className="segmented" role="group" aria-label="Escala del calendario">
            {(['week', 'month', 'season'] as Scale[]).map((s) => (
              <button key={s} type="button" aria-pressed={scale === s} onClick={() => setScale(s)}>{{ week: 'Semana', month: 'Mes', season: 'Temporada' }[s]}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="card__scroll">{series ? body : <p className="loading">Cargando serie…</p>}</div>
    </div>
  );

  const seasonsCard = (
    <div className="panel card card--seasons">
      <div className="card__head">
        <div><h2>Ocho temporadas, semana por semana</h2></div>
        <div><span className="hint">De julio a junio · km² con fuego</span></div>
      </div>
      <div className="seasons" aria-label={`Actividad de fuego por semana en ${region.name}, temporadas ${seasonStart - N_SEASONS + 1} a ${seasonStart}. ${monthTitle(month)} está resaltado.`}>
        <div className="seasons__row"><div className="seasons__label" /><div className="seasons__months">{SEASON_MONTHS.map((m) => <span key={m}>{m}</span>)}</div></div>
        {seasonRows?.rows.map((r) => (
          <div key={r.season} className="seasons__row">
            <div className={`seasons__label ${r.season === seasonStart ? 'is-open' : ''}`}>{r.season}/{String((r.season + 1) % 100).padStart(2, '0')}</div>
            <div className="seasons__weeks">
              {r.weeks.map((w, i) => {
                const marked = w.d0 + 6 >= monthD0 && w.d0 <= monthD1;
                return (
                  <button key={i} type="button" disabled={w.future}
                    className={marked ? 'is-marked' : ''}
                    style={{ background: w.future ? 'var(--surface)' : LVL[level(w.km2, seasonRows.t)] }}
                    title={`Semana del ${shortDate(isoFromDay(w.d0))}: ${fmtKm2(w.km2)} km²`}
                    aria-label={`Semana del ${shortDate(isoFromDay(w.d0))}: ${fmtKm2(w.km2)} km²`}
                    onClick={() => goDay(w.d0)} />
                );
              })}
            </div>
          </div>
        )) ?? <p className="loading">Cargando serie…</p>}
      </div>
    </div>
  );

  return (
    <div className="cal">
      <Header
        view="calendar"
        regions={base.regions}
        region={region}
        year={year}
        years={years}
        query={query}
        onRegion={(id) => update({ r: id, pt: null, ev: null })}
        onYear={(y) => update({ m: Math.max(0, Math.min(lastMonth, monthIndex(y, month0))), d: null })}
      />
      <main className="cal__main">
        <div className={`cal__side ${placeOpen || dateOpen || logOpen ? 'is-open' : ''}`}>
          <DashMenu label="Ubicación" icon={<Icon.pin />} corner="top-left" open={placeOpen} onOpen={() => setPlaceOpen(true)} onClose={() => setPlaceOpen(false)} className="place-menu">
            <PlaceMenu
              regions={base.regions}
              regionById={base.regionById}
              region={region}
              month={month}
              point={point}
              incident={incident}
              hasIncident={incidentRef !== null}
              mapHref={`/?${query}`}
              onRegion={(id) => update({ r: id, pt: null, ev: null })}
              onPick={(i) => {
                const d = i.day;
                update({ pt: { lat: i.lat, lon: i.lon }, ev: { month: i.month, id: i.event.id }, m: monthOfDay(d), d: new Date(Date.parse(isoFromDay(d))).getUTCDate() });
              }}
              onClear={() => update({ pt: null, ev: null })}
              onReport={() => setFormOpen(true)}
            />
          </DashMenu>
          <DashMenu label="Fecha" icon={<Icon.calendar />} corner="top-left" open={dateOpen} onOpen={() => setDateOpen(true)} onClose={() => setDateOpen(false)} className="date-card">
            <h1 className="date-card__date">{selDate.getUTCDate()} de {MONTH_NAMES[selDate.getUTCMonth()].toLowerCase()} de {selDate.getUTCFullYear()}</h1>
            <div className="date-card__place">
              {ancestors.length > 0 && (
                <nav className="crumbs" aria-label="Ubicación">
                  {ancestors.map((r) => (
                    <span key={r.id}><button type="button" onClick={() => update({ r: r.id })}>{r.name}</button><span aria-hidden="true">›</span></span>
                  ))}
                </nav>
              )}
              <h2>{region.name}</h2>
            </div>
            {selDay > lastDay ? (
              <>
                <div className="date-card__fires date-card__fires--forecast">
                  <span className="loc-card__big">{selPred === null ? '—' : fmtInt(selPred)}</span>
                  <span>{selPred === null ? 'sin pronóstico para esta zona' : `${selPred === 1 ? 'fire estimado' : 'fires estimados'}`}</span>
                </div>
                <div className="note note--warn" role="alert">
                  <div className="note__head"><strong>Cuidado.</strong><span className="note__bang" aria-hidden="true">!</span></div>
                  <p>
                    Es una estimación del modelo para {forecast?.p.coverage.name}, no un registro satelital: predice dónde puede haber fuego
                    a partir de los hotspots recientes y el pronóstico del tiempo. Puede haber fallas.
                  </p>
                </div>
              </>
            ) : (
              <div className="date-card__fires">
                <span className="loc-card__big">{selValue.nF < 0 ? '—' : fmtInt(selValue.nF)}</span>
                <span>{selValue.nF === 1 ? 'fire' : 'fires'}</span>
              </div>
            )}
          </DashMenu>
          <DashMenu label="Bitácora" icon={<Icon.log />} corner="top-left" open={logOpen} onOpen={() => setLogOpen(true)} onClose={() => setLogOpen(false)} className="log-menu">
            <FieldLog entries={regionEntries} selected={selected} regionName={region.name} onSelect={(e) => { setSelected(e.id); goDay(dayFromIso(e.date)); }} />
          </DashMenu>
        </div>
        {/* Calendar on top (scrolls), the eight-season strip always visible at the bottom. */}
        <section className="cal__center">{monthCard}{seasonsCard}</section>
      </main>
      {formOpen && (
        <EntryForm
          point={point ?? { lat: (region.bbox[1] + region.bbox[3]) / 2, lon: (region.bbox[0] + region.bbox[2]) / 2 }}
          incident={incident ? { id: incident.event.id, start: incident.event.start, end: incident.event.end } : null}
          defaultDate={isoFromDay(Math.min(selDay, lastDay))}
          onClose={() => setFormOpen(false)}
          onSaved={(e) => { add(e); setFormOpen(false); setSelected(e.id); }}
        />
      )}
    </div>
  );
}
