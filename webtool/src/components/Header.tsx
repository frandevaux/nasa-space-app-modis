'use client';
import Link from 'next/link';
import { useMemo, useRef, useState } from 'react';
import { Icon } from './icons';
import type { Region } from '@/lib/types';

const normalize = (s: string) => s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const KIND_ORDER = { country: 0, province: 1, department: 2 } as const;

interface Props {
  view: 'map' | 'calendar';
  regions: Region[];
  region: Region | null;
  year: number | null;
  years: number[];
  query: string;
  /** Query for the link to the other view, if it differs from the current one. */
  otherQuery?: string;
  onRegion: (id: string) => void;
  onYear: (year: number) => void;
}

export default function Header({ view, regions, region, year, years, query, otherQuery, onRegion, onYear }: Props) {
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const matches = useMemo(() => {
    const q = normalize(text.trim());
    if (!q) { return regions.filter((r) => r.kind !== 'department').slice(0, 30); }
    return regions
      .filter((r) => normalize(r.name).includes(q))
      .sort((a, b) => {
        const sa = normalize(a.name).startsWith(q) ? 0 : 1;
        const sb = normalize(b.name).startsWith(q) ? 0 : 1;
        return sa - sb || KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || a.name.localeCompare(b.name);
      })
      .slice(0, 30);
  }, [text, regions]);

  function choose(r: Region) {
    onRegion(r.id);
    setText('');
    setOpen(false);
    inputRef.current?.blur();
  }

  const label = region ? (region.kind === 'department' ? `${region.name}, ${region.subtitle.replace('Departamento · ', '')}` : region.kind === 'province' ? `${region.name}, Argentina` : 'Argentina') : '';

  return (
    <header className="header">
      <div className="logo">Mente Fría<sup>®</sup></div>
      <div role="search" className={`search ${view === 'calendar' ? 'search--outlined' : ''}`}>
        <span className="search__icon"><Icon.search /></span>
        <input
          ref={inputRef}
          className="search__input"
          role="combobox"
          aria-expanded={open}
          aria-controls="region-suggest"
          aria-label="Buscar provincia o departamento"
          placeholder={label || 'Buscar provincia o departamento'}
          value={text}
          onChange={(e) => { setText(e.target.value); setActive(0); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(matches.length - 1, a + 1)); }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            if (e.key === 'Enter' && matches[active]) { choose(matches[active]); }
            if (e.key === 'Escape') { setOpen(false); }
          }}
        />
        {open && matches.length > 0 && (
          <ul className="suggest" id="region-suggest" role="listbox">
            {matches.map((r, i) => (
              <li key={r.id}>
                <button type="button" role="option" aria-selected={i === active} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(r)}>
                  <span>{r.name}</span>
                  <span>{r.subtitle}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <span className="search__sep" aria-hidden="true" />
        <select aria-label="Año" value={year ?? ''} onChange={(e) => onYear(Number(e.target.value))}>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      <nav className="views" aria-label="Visualización">
        <Link href={`/?${view === 'map' ? query : otherQuery ?? query}`} aria-current={view === 'map' ? 'page' : undefined}>Mapa</Link>
        <Link href={`/calendario?${view === 'calendar' ? query : otherQuery ?? query}`} aria-current={view === 'calendar' ? 'page' : undefined}>Calendario</Link>
      </nav>
      <button type="button" className="user" aria-label="Cuenta de usuario (no disponible en el prototipo)" title="Cuentas de usuario: pendiente">
        <span className="user__avatar"><Icon.user /></span>Invitado<Icon.downSmall />
      </button>
    </header>
  );
}
