import type { Metadata } from 'next';
import { Suspense } from 'react';
import CalendarView from '@/components/CalendarView';

export const metadata: Metadata = { title: 'Mente Fría — Calendario' };

export default function CalendarPage() {
  return (
    <div className="cal-page">
      <Suspense fallback={null}>
        <CalendarView />
      </Suspense>
    </div>
  );
}
