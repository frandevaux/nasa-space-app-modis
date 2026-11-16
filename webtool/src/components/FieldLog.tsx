'use client';
/* "Bitácora" menu body: field-log history of the selected region, newest first, a page at a time. */
import { useEffect, useState } from 'react';
import { Icon } from './icons';
import { eventNoun } from '@/lib/incidents';
import { localDate, MONTH_NAMES } from '@/lib/time';
import type { EntryKind, LogEntry } from '@/lib/types';

export const KIND_LABEL: Record<EntryKind, string> = {
  alert: 'Alerta',
  evacuation: 'Evacuación',
  procedure: 'Procedimiento',
  control: 'Controlado',
  lesson: 'Lección',
};

const PAGE = 5;

function period(date: string) {
  const [y, m] = date.split('-').map(Number);
  return `${MONTH_NAMES[m - 1]} de ${y}`;
}

interface Props {
  entries: LogEntry[];
  selected: string | null;
  regionName: string;
  onSelect: (e: LogEntry) => void;
  /** Shows the "Agregar registro" button (the calendar reports from its Ubicación menu instead). */
  onNew?: () => void;
}

export default function FieldLog({ entries, selected, regionName, onSelect, onNew }: Props) {
  const [shown, setShown] = useState(PAGE);
  useEffect(() => setShown(PAGE), [regionName]);

  return (
    <div className="log">
      <div className="log__list">
        {entries.length === 0 && <div className="log__empty">Todavía no hay registros de campo en {regionName}.</div>}
        {entries.slice(0, shown).map((e) => (
          <button key={e.id} type="button" className="entry" aria-pressed={e.id === selected} onClick={() => onSelect(e)}>
            <span className="entry__meta"><span>{period(e.date)}</span><span>{e.author || 'Anónimo'}</span></span>
            {e.kind && <span className="entry__kind">{KIND_LABEL[e.kind]} · {Number(e.date.slice(8))}</span>}
            <span className="entry__title">{e.title}</span>
            {e.event && <span className="entry__incident">{eventNoun(e.event.start, e.event.end).noun === 'fire' ? 'Fire' : 'Firewave'} del {localDate(e.event.start)} al {localDate(e.event.end)}</span>}
            <span>{e.text}</span>
            {e.lesson && <span className="entry__lesson">{e.lesson}</span>}
          </button>
        ))}
      </div>
      {(entries.length > shown || onNew) && <div className="log__actions">
        {entries.length > shown && <button type="button" className="btn btn--secondary" onClick={() => setShown(shown + PAGE)}>Ver más</button>}
        {onNew && <button type="button" className="btn btn--primary" onClick={onNew}>Agregar registro<Icon.plus /></button>}
      </div>}
    </div>
  );
}
