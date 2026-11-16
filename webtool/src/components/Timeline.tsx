'use client';
/*
 * Timeline with a fixed, centered playhead. The strip moves underneath:
 * drag it, scroll it (wheel / trackpad), click a cell, or use the keyboard.
 * The scale (days / weeks / months) changes what one cell means.
 * Only visible cells are rendered (the day scale has ~9,500 units).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Icon } from './icons';
import { SCALES, STEPS, unitLabel, unitTitle, type Scale } from '@/lib/timescale';

const CELL_PX = 14;
const COMMIT_DELAY_MS = 250;

export interface CellStyle { bg: string; className?: string }

interface Props {
  scale: Scale;
  cursor: number;              // committed unit index
  max: number;                 // last valid unit index
  now: number;                 // unit with the latest data ("today")
  cellStyle: (i: number) => CellStyle;
  subtitle: string;
  rangeText: string;
  playing: boolean;
  onCommit: (i: number) => void;
  onScale: (s: Scale) => void;
  onPlay: () => void;
}

export default function Timeline({ scale, cursor, max, now, cellStyle, subtitle, rangeText, playing, onCommit, onScale, onPlay }: Props) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(1200);
  const [live, setLive] = useState<number | null>(null); // fractional cursor while dragging / scrolling
  const drag = useRef<{ x: number; start: number; moved: boolean } | null>(null);
  const wheelTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const liveRef = useRef<number | null>(null);
  liveRef.current = live;

  const clamp = useCallback((v: number) => Math.max(0, Math.min(max, v)), [max]);
  const pos = live ?? cursor;

  useEffect(() => {
    const el = trackRef.current;
    if (!el) { return; }
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // Wheel / trackpad: move the strip, commit shortly after the gesture ends.
  useEffect(() => {
    const el = trackRef.current;
    if (!el) { return; }
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      const base = liveRef.current ?? cursor;
      setLive(clamp(base + delta / CELL_PX));
      if (wheelTimer.current) { clearTimeout(wheelTimer.current); }
      wheelTimer.current = setTimeout(() => {
        const v = liveRef.current;
        setLive(null);
        if (v !== null) { onCommit(Math.round(v)); }
      }, COMMIT_DELAY_MS);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [cursor, clamp, onCommit]);

  function onPointerDown(e: React.PointerEvent) {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, start: cursor, moved: false };
  }
  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current;
    if (!d) { return; }
    const dx = e.clientX - d.x;
    if (Math.abs(dx) > 3) { d.moved = true; }
    if (d.moved) { setLive(clamp(d.start - dx / CELL_PX)); }
  }
  function onPointerUp(e: React.PointerEvent) {
    const d = drag.current;
    drag.current = null;
    if (!d) { return; }
    if (!d.moved) {
      // Click: center the clicked cell.
      const rect = trackRef.current!.getBoundingClientRect();
      onCommit(clamp(Math.round(cursor + (e.clientX - rect.left - rect.width / 2) / CELL_PX)));
    } else if (live !== null) {
      onCommit(Math.round(live));
    }
    setLive(null);
  }
  function onKeyDown(e: React.KeyboardEvent) {
    const s = STEPS[scale];
    const moves: Record<string, number> = { ArrowLeft: -s.small, ArrowRight: s.small, PageUp: -s.large, PageDown: s.large };
    if (e.key in moves) { e.preventDefault(); onCommit(clamp(cursor + moves[e.key])); }
    if (e.key === 'Home') { e.preventDefault(); onCommit(0); }
    if (e.key === 'End') { e.preventDefault(); onCommit(now); }
  }

  // Visible cells only
  const half = width / 2;
  const first = Math.max(0, Math.floor(pos - half / CELL_PX) - 2);
  const last = Math.min(max, Math.ceil(pos + half / CELL_PX) + 2);
  const cells = [];
  const ruler = [];
  for (let i = first; i <= last; i++) {
    const x = half + (i - pos) * CELL_PX - CELL_PX / 2;
    const st = cellStyle(i);
    cells.push(<div key={i} className={`tl-cell ${st.className ?? ''} ${i === now ? 'is-now' : ''}`} style={{ transform: `translateX(${x}px)`, background: st.bg }} />);
    const lb = unitLabel(scale, i);
    if (lb) { ruler.push(<span key={i} className={lb.strong ? 'year' : ''} style={{ transform: `translateX(${x}px)` }}>{lb.text}</span>); }
  }
  const s = STEPS[scale];
  const shown = Math.round(pos);

  return (
    <section className="panel timeline" aria-label="Línea de tiempo">
      <div className="timeline__top">
        <div className="timeline__title">
          <strong>{unitTitle(scale, shown)}</strong>
          <span><span>{subtitle}</span></span>
        </div>
        <div className="transport" role="group" aria-label="Moverse por la línea de tiempo">
          <button type="button" onClick={() => onCommit(clamp(cursor - s.large))} aria-label={`Retroceder ${s.largeLabel}`}>-{s.largeLabel}</button>
          <button type="button" onClick={() => onCommit(clamp(cursor - s.small))} aria-label={`Retroceder ${s.smallLabel}`}>-{s.smallLabel}</button>
          <button type="button" className="transport__play" onClick={onPlay} aria-label={playing ? 'Pausar' : 'Reproducir la línea de tiempo'}>{playing ? <Icon.pause /> : <Icon.play />}</button>
          <button type="button" onClick={() => onCommit(clamp(cursor + s.small))} aria-label={`Avanzar ${s.smallLabel}`}>+{s.smallLabel}</button>
          <button type="button" onClick={() => onCommit(clamp(cursor + s.large))} aria-label={`Avanzar ${s.largeLabel}`}>+{s.largeLabel}</button>
        </div>
        <div className="timeline__right">
          <span className="timeline__range">{rangeText}</span>
          <button type="button" className="tl-today" aria-pressed={cursor === now} onClick={() => onCommit(now)}>Hoy</button>
          <div className="segmented segmented--small" role="group" aria-label="Escala de la línea de tiempo">
            {SCALES.map((x) => (
              <button key={x.id} type="button" aria-pressed={scale === x.id} onClick={() => onScale(x.id)}>{x.label}</button>
            ))}
          </div>
        </div>
      </div>
      <div
        ref={trackRef}
        className={`tl-track ${live !== null ? 'is-dragging' : ''}`}
        role="slider"
        tabIndex={0}
        aria-label="Línea de tiempo: arrastrá, usá la rueda o las flechas"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={cursor}
        aria-valuetext={unitTitle(scale, cursor)}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => { drag.current = null; setLive(null); }}
        onKeyDown={onKeyDown}
      >
        <div className="tl-cells" aria-hidden="true">{cells}</div>
        <div className="tl-ruler" aria-hidden="true">{ruler}</div>
        <div className="tl-playhead" aria-hidden="true" />
      </div>
    </section>
  );
}
