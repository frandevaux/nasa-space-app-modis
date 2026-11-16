'use client';
/* Modal to add a field-log entry, anchored to a point on the map. */
import { useEffect, useState } from 'react';
import { createEntry, getGeo } from '@/lib/data';
import { locate } from '@/lib/geo';
import type { EntryKind, LogEntry } from '@/lib/types';
import { KIND_LABEL } from './FieldLog';

interface Props {
  point: { lat: number; lon: number } | null;
  defaultDate: string;
  onClose: () => void;
  onSaved: (e: LogEntry) => void;
}

export default function EntryForm({ point, defaultDate, onClose, onSaved }: Props) {
  const [date, setDate] = useState(defaultDate);
  const [kind, setKind] = useState<EntryKind>('procedure');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [lesson, setLesson] = useState('');
  const [author, setAuthor] = useState('');
  const [lat, setLat] = useState(point ? point.lat.toFixed(4) : '');
  const [lon, setLon] = useState(point ? point.lon.toFixed(4) : '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { onClose(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    const la = Number(lat.replace(',', '.'));
    const lo = Number(lon.replace(',', '.'));
    setSaving(true);
    try {
      const depts = await getGeo('departments');
      const where = locate<{ id: string; province: string }>(depts, lo, la);
      const saved = await createEntry({
        date, kind, title, text, lesson: lesson || undefined, author: author || undefined,
        lat: la, lon: lo, department: where?.id, province: where?.province,
      });
      onSaved(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) { onClose(); } }}>
      <form className="modal" onSubmit={submit} aria-labelledby="entry-form-title">
        <h2 id="entry-form-title">Cargar un registro</h2>
        <p className="hint" style={{ margin: 0 }}>
          El registro queda anclado al punto marcado en el mapa. Contá qué pasó en el terreno: lo que el satélite no ve.
        </p>
        <div className="form-grid">
          <label className="form-row">Fecha del hecho
            <input type="date" required value={date} min="2000-11-01" onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="form-row">Tipo
            <select value={kind} onChange={(e) => setKind(e.target.value as EntryKind)}>
              {(Object.keys(KIND_LABEL) as EntryKind[]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          </label>
        </div>
        <label className="form-row">Título
          <input required maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ej.: Cortafuego en camino vecinal" />
        </label>
        <label className="form-row">Qué pasó
          <textarea required maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} placeholder="Condiciones, recursos, decisiones, resultado…" />
        </label>
        <label className="form-row">Lección para la próxima (opcional)
          <input maxLength={300} value={lesson} onChange={(e) => setLesson(e.target.value)} />
        </label>
        <div className="form-grid">
          <label className="form-row">Latitud
            <input required inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />
          </label>
          <label className="form-row">Longitud
            <input required inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} />
          </label>
        </div>
        <label className="form-row">Quién lo carga (opcional)
          <input maxLength={80} value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="Ej.: Brigada Punilla" />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal__actions">
          <button type="button" className="btn btn--secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" className="btn btn--primary" disabled={saving}>{saving ? 'Guardando…' : 'Guardar registro'}</button>
        </div>
      </form>
    </div>
  );
}
