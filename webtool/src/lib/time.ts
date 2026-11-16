/* Time indices. Month 0 = November 2000 (first FIRMS MODIS month); day 0 = 2000-11-01. */

export const START_YEAR = 2000;
export const START_MONTH = 10; // 0-based: November

export const MONTH_NAMES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
export const MONTH_ABBR = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

const DAY_MS = 86400000;
const T0 = Date.UTC(START_YEAR, START_MONTH, 1);

export function monthIndex(year: number, month0: number): number {
  return (year - START_YEAR) * 12 + month0 - START_MONTH;
}

export function monthFromIndex(i: number): { year: number; month0: number } {
  const t = START_MONTH + i;
  return { year: START_YEAR + Math.floor(t / 12), month0: ((t % 12) + 12) % 12 };
}

export function ym(i: number): string {
  const { year, month0 } = monthFromIndex(i);
  return `${year}-${String(month0 + 1).padStart(2, '0')}`;
}

export function indexFromYm(s: string): number {
  const [y, m] = s.split('-').map(Number);
  return monthIndex(y, m - 1);
}

export function monthTitle(i: number): string {
  const { year, month0 } = monthFromIndex(i);
  return `${MONTH_NAMES[month0]} de ${year}`;
}

export function dayIndex(year: number, month0: number, day: number): number {
  return Math.round((Date.UTC(year, month0, day) - T0) / DAY_MS);
}

export function dateFromDay(d: number): Date {
  return new Date(T0 + d * DAY_MS);
}

export function isoFromDay(d: number): string {
  return dateFromDay(d).toISOString().slice(0, 10);
}

export function dayFromIso(s: string): number {
  const [y, m, dd] = s.split('-').map(Number);
  return dayIndex(y, m - 1, dd);
}

export function monthOfDay(d: number): number {
  const f = dateFromDay(d);
  return monthIndex(f.getUTCFullYear(), f.getUTCMonth());
}

export function daysInMonth(i: number): number {
  const { year, month0 } = monthFromIndex(i);
  return new Date(Date.UTC(year, month0 + 1, 0)).getUTCDate();
}

/** 0 = Monday … 6 = Sunday */
export function weekdayMonFirst(year: number, month0: number, day: number): number {
  return (new Date(Date.UTC(year, month0, day)).getUTCDay() + 6) % 7;
}

export function shortDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTH_ABBR[m - 1]} ${y}`;
}

const nf1 = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });

export function fmtKm2(v: number): string {
  if (v === 0) { return '0'; }
  if (v < 0.1) { return '< 0,1'; }
  return v < 100 ? nf1.format(v) : nf0.format(v);
}

export function fmtInt(v: number): string {
  return nf0.format(v);
}

/** UTC timestamp 'YYYY-MM-DDTHH:MM' → local Argentina time (UTC−3), e.g. '1 ene 2025, 22:22'. */
export function localDateTime(isoUtc: string): string {
  const t = new Date(`${isoUtc}:00Z`).getTime() - 3 * 3600000;
  const f = new Date(t);
  const hh = String(f.getUTCHours()).padStart(2, '0');
  const mm = String(f.getUTCMinutes()).padStart(2, '0');
  return `${f.getUTCDate()} ${MONTH_ABBR[f.getUTCMonth()]} ${f.getUTCFullYear()}, ${hh}:${mm}`;
}

/** UTC timestamp → local date only, e.g. '1 ene 2025'. */
export function localDate(isoUtc: string): string {
  return localDateTime(isoUtc).split(',')[0];
}

/** Does an event span several local (UTC−3) days? Those are "olas de incendios". start / end: UTC 'YYYY-MM-DDTHH:MM'. */
export function spansDays(start: string, end: string): boolean {
  const day = (s: string) => new Date(Date.parse(`${s}:00Z`) - 3 * 3600000).toISOString().slice(0, 10);
  return day(start) !== day(end);
}
