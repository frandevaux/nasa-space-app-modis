/*
 * Timeline scales. Each scale has its own unit index:
 *   day   → day index (0 = 2000-11-01)
 *   week  → Monday-based week index (week 0 starts on Mon 2000-10-30)
 *   month → month index (0 = Nov 2000)
 * The map always works with a window of days [from, to] derived from the cursor.
 */
import { dateFromDay, dayIndex, daysInMonth, MONTH_ABBR, MONTH_NAMES, monthFromIndex, monthOfDay, shortDate, isoFromDay } from './time';

export type Scale = 'day' | 'week' | 'month';

export const SCALES: { id: Scale; label: string }[] = [
  { id: 'day', label: 'Días' },
  { id: 'week', label: 'Semanas' },
  { id: 'month', label: 'Meses' },
];

/** Days shown on the map in day scale: the selected day plus the previous ones, fading out. */
export const DAY_TRAIL = 7;

// 2000-11-01 was a Wednesday → the Monday of its week is day −2.
const WEEK_ANCHOR = -2;

export const weekOfDay = (d: number) => Math.floor((d - WEEK_ANCHOR) / 7);
export const weekStart = (w: number) => WEEK_ANCHOR + 7 * w;
export const monthStartDay = (m: number) => {
  const { year, month0 } = monthFromIndex(m);
  return dayIndex(year, month0, 1);
};
export const monthEndDay = (m: number) => monthStartDay(m) + daysInMonth(m) - 1;

/** Unit index of `scale` that contains day `d`. */
export function unitOfDay(scale: Scale, d: number): number {
  if (scale === 'day') { return d; }
  if (scale === 'week') { return weekOfDay(d); }
  return monthOfDay(d);
}

/** Representative day of a unit (used when switching scales and to write the URL). */
export function dayOfUnit(scale: Scale, i: number): number {
  if (scale === 'day') { return i; }
  if (scale === 'week') { return weekStart(i); }
  return monthStartDay(i);
}

/** Window of days the map shows for a unit, plus the day that counts as "now" for fading. */
export function windowOf(scale: Scale, i: number): { from: number; to: number; fade: boolean } {
  if (scale === 'day') { return { from: i - DAY_TRAIL + 1, to: i, fade: true }; }
  if (scale === 'week') { return { from: weekStart(i), to: weekStart(i) + 6, fade: false }; }
  return { from: monthStartDay(i), to: monthEndDay(i), fade: false };
}

export function unitTitle(scale: Scale, i: number): string {
  if (scale === 'day') {
    const f = dateFromDay(i);
    return `${f.getUTCDate()} de ${MONTH_NAMES[f.getUTCMonth()].toLowerCase()} de ${f.getUTCFullYear()}`;
  }
  if (scale === 'week') { return `Semana del ${shortDate(isoFromDay(weekStart(i)))}`; }
  const { year, month0 } = monthFromIndex(i);
  return `${MONTH_NAMES[month0]} de ${year}`;
}

/** Ruler label for a unit, or null. `strong` marks year / month boundaries. */
export function unitLabel(scale: Scale, i: number): { text: string; strong: boolean } | null {
  if (scale === 'day') {
    const f = dateFromDay(i);
    const dom = f.getUTCDate();
    if (dom === 1) {
      const m = f.getUTCMonth();
      return { text: m === 0 ? `ene '${String(f.getUTCFullYear()).slice(2)}` : MONTH_ABBR[m], strong: true };
    }
    return dom % 5 === 0 && dom < 30 ? { text: String(dom), strong: false } : null;
  }
  if (scale === 'week') {
    const s = dateFromDay(weekStart(i));
    const e = dateFromDay(weekStart(i) + 6);
    if (e.getUTCMonth() !== s.getUTCMonth() || s.getUTCDate() === 1) {
      const m = e.getUTCMonth();
      return { text: m === 0 ? `'${String(e.getUTCFullYear()).slice(2)}` : MONTH_ABBR[m], strong: m === 0 };
    }
    return null;
  }
  const { year, month0 } = monthFromIndex(i);
  if (month0 === 0) { return { text: `'${String(year).slice(2)}`, strong: true }; }
  if (month0 === 6) { return { text: 'jul', strong: false }; }
  return null;
}

/** Transport steps (small, large) per scale. */
export const STEPS: Record<Scale, { small: number; large: number; smallLabel: string; largeLabel: string }> = {
  day: { small: 1, large: 7, smallLabel: '1d', largeLabel: '7d' },
  week: { small: 1, large: 4, smallLabel: '1s', largeLabel: '4s' },
  month: { small: 1, large: 12, smallLabel: '1m', largeLabel: '1a' },
};
