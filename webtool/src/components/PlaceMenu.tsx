'use client';
/*
 * Calendar "Ubicación" menu body.
 *   - With a point (clicked on the map, or picked from the list): the place and its fire event ("fire").
 *   - Without one: Argentina › province › department, and the list of that department's fires in the
 *     month on screen (start, end, latitude, longitude). Or go back to the map and pick a point there.
 */
import Link from 'next/link';
import { Icon } from './icons';
import { useEffect, useState } from 'react';
import { getGeo, getMonthFires } from '@/lib/data';
import { locate } from '@/lib/geo';
import { findIncident, incidentsIn, isWave, type Incident } from '@/lib/incidents';
import type { IncidentRef, Point } from '@/lib/hooks';
import { localDate, localDateTime, monthTitle, ym } from '@/lib/time';
import type { Region } from '@/lib/types';

/** "5 en octubre de 2020: 3 firewaves y 2 fires". */
function listTitle(items: Incident[], month: number): string {
  const waves = items.filter((i) => isWave(i.event.start, i.event.end)).length;
  const single = items.length - waves;
  const parts = [
    waves ? `${waves} ${waves === 1 ? 'firewave' : 'firewaves'}` : '',
    single ? `${single} ${single === 1 ? 'fire' : 'fires'}` : '',
  ].filter(Boolean);
  return `${parts.join(' y ') || 'Ningún fire'} en ${monthTitle(month).toLowerCase()}`;
}

/** Resolves an incident reference from the URL into its data (null while loading or if not found). */
export function useIncident(ref: IncidentRef | null): Incident | null {
  const [state, setState] = useState<{ key: string; inc: Incident | null } | null>(null);
  const key = ref ? `${ref.month}:${ref.id}` : '';
  useEffect(() => {
    if (!ref) { return; }
    let alive = true;
    getMonthFires(ref.month).then((m) => { if (alive) { setState({ key, inc: m ? findIncident(m, ref.id) : null }); } });
    return () => { alive = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return state && state.key === key ? state.inc : null;
}

interface Props {
  regions: Region[];
  regionById: Map<string, Region>;
  region: Region;
  month: number;
  point: Point | null;
  incident: Incident | null;
  hasIncident: boolean;
  mapHref: string;
  onRegion: (id: string) => void;
  onPick: (i: Incident) => void;
  onClear: () => void;
  /** Opens the report form (a field-log entry linked to this place and fire). */
  onReport: () => void;
}

export default function PlaceMenu({ regions, regionById, region, month, point, incident, hasIncident, mapHref, onRegion, onPick, onClear, onReport }: Props) {
  const provinceId = region.kind === 'province' ? region.id : region.kind === 'department' ? region.province ?? '' : '';
  const departmentId = region.kind === 'department' ? region.id : '';
  const [place, setPlace] = useState<{ name: string; province: string } | null>(null);
  const [list, setList] = useState<{ key: string; items: Incident[] } | null>(null);

  // Name of the place under the point.
  useEffect(() => {
    if (!point) { return; }
    let alive = true;
    getGeo('departments').then((d) => { if (alive) { setPlace(locate<{ name: string; province: string }>(d, point.lon, point.lat)); } });
    return () => { alive = false; };
  }, [point]);

  // Fires of the department in the month on screen.
  const listKey = departmentId && !point ? `${departmentId}:${ym(month)}` : '';
  useEffect(() => {
    if (!listKey) { return; }
    let alive = true;
    Promise.all([getMonthFires(ym(month)), getGeo('departments')]).then(([m, depts]) => {
      const f = depts.features.find((x) => x.properties?.id === departmentId);
      if (alive) { setList({ key: listKey, items: m && f ? incidentsIn(m, f) : [] }); }
    });
    return () => { alive = false; };
  }, [listKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (point) {
    return (
      <>
        <h2 className="loc-card__place">{place ? `${place.name}, ${regionById.get(place.province)?.name ?? ''}` : '…'}</h2>
        <dl className="loc-card__grid">
          <div><dt>Latitud</dt><dd>{point.lat.toFixed(3)}°</dd></div>
          <div><dt>Longitud</dt><dd>{point.lon.toFixed(3)}°</dd></div>
          {hasIncident ? (
            <>
              <div><dt>Inicio {incident && isWave(incident.event.start, incident.event.end) ? 'del firewave' : 'del fire'}</dt><dd>{incident ? localDateTime(incident.event.start) : '…'}</dd></div>
              <div><dt>Fin {incident && isWave(incident.event.start, incident.event.end) ? 'del firewave' : 'del fire'}</dt><dd>{incident ? localDateTime(incident.event.end) : '…'}</dd></div>
            </>
          ) : (
            <div className="loc-card__wide"><dt>Fire</dt><dd>No hay un fire registrado en este punto.</dd></div>
          )}
        </dl>
        <button type="button" className="btn btn--primary" onClick={onReport}>Reportar<Icon.plus /></button>
        <div className="place-actions">
          <button type="button" className="link-btn" onClick={onClear}>Elegir otro lugar</button>
          <Link href={mapHref} className="link-btn">Ver en el mapa</Link>
        </div>
      </>
    );
  }

  const provinces = regions.filter((r) => r.kind === 'province').sort((a, b) => a.name.localeCompare(b.name));
  const departments = regions.filter((r) => r.kind === 'department' && r.province === provinceId).sort((a, b) => a.name.localeCompare(b.name));
  const items = list && list.key === listKey ? list.items : null;

  return (
    <>
      <div className="place-pick">
        <label className="form-row">País
          <select value="AR" onChange={() => onRegion('AR')}><option value="AR">Argentina</option></select>
        </label>
        <label className="form-row">Provincia
          <select value={provinceId} onChange={(e) => onRegion(e.target.value || 'AR')}>
            <option value="">Elegí una provincia</option>
            {provinces.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="form-row">Departamento
          <select value={departmentId} disabled={!provinceId} onChange={(e) => onRegion(e.target.value || provinceId)}>
            <option value="">{provinceId ? 'Elegí un departamento' : 'Primero elegí una provincia'}</option>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
      </div>
      {departmentId && (
        <div className="incidents">
          <div className="panel__eyebrow">
            {items ? listTitle(items, month) : 'Buscando fires…'}
          </div>
          {items && items.length > 0 && (
            <ul className="incident-list">
              {items.map((i) => (
                <li key={i.event.id}>
                  <button type="button" onClick={() => onPick(i)}>
                    <span className={`incident-list__kind ${isWave(i.event.start, i.event.end) ? 'is-wave' : ''}`}>{isWave(i.event.start, i.event.end) ? 'Firewave' : 'Fire'}</span>
                    <span className="incident-list__dates"><span>Inicio {localDate(i.event.start)}</span><span>Fin {localDate(i.event.end)}</span></span>
                    <span className="incident-list__coords">Lat {i.lat.toFixed(3)}° · Lon {i.lon.toFixed(3)}°</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="place-actions place-actions--map">
        <span>¿No recordás el lugar?</span>
        <Link href={mapHref} className="link-btn">Tocá un punto en el mapa</Link>
      </div>
    </>
  );
}
