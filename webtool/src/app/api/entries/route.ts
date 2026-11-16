/*
 * Field log ("Bitácora"): entries written by firefighters and brigades.
 * Prototype storage: webtool/data/entries.json (a local file, no users / auth).
 * A real deployment needs a database and authentication.
 */
import { promises as fs } from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { NextResponse } from 'next/server';
import type { EntryKind, LogEntry } from '@/lib/types';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const FILE = path.join(process.cwd(), 'data', 'entries.json');
const KINDS: EntryKind[] = ['alert', 'evacuation', 'procedure', 'control', 'lesson'];

async function readAll(): Promise<LogEntry[]> {
  try {
    return JSON.parse(await fs.readFile(FILE, 'utf-8'));
  } catch {
    return [];
  }
}

let queue: Promise<unknown> = Promise.resolve();

export async function GET() {
  const entries = await readAll();
  entries.sort((a, b) => b.date.localeCompare(a.date) || b.createdAt.localeCompare(a.createdAt));
  return NextResponse.json(entries);
}

const str = (v: unknown, max: number) => (typeof v === 'string' ? v.trim().slice(0, max) : '');
const STAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** Optional link to a fire event: { id, start, end } or nothing. */
function eventRef(v: unknown): LogEntry['event'] {
  if (!v || typeof v !== 'object') { return undefined; }
  const { id, start, end } = v as Record<string, unknown>;
  if (typeof id !== 'string' || !/^[0-9a-z]{4,32}$/.test(id)) { return undefined; }
  if (typeof start !== 'string' || !STAMP.test(start) || typeof end !== 'string' || !STAMP.test(end)) { return undefined; }
  return { id, start, end };
}

export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: 'JSON inválido' }, { status: 400 });
  }
  const date = str(body.date, 10);
  const kind = body.kind === undefined ? undefined : (body.kind as EntryKind);
  const title = str(body.title, 120);
  const text = str(body.text, 2000);
  const lat = Number(body.lat);
  const lon = Number(body.lon);
  const errors: string[] = [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { errors.push('fecha'); }
  if (kind !== undefined && !KINDS.includes(kind)) { errors.push('tipo'); }
  if (!title) { errors.push('título'); }
  if (!text) { errors.push('texto'); }
  if (!(lat >= -56 && lat <= -21 && lon >= -74 && lon <= -53)) { errors.push('ubicación'); }
  if (errors.length) {
    return NextResponse.json({ error: `Revisá: ${errors.join(', ')}` }, { status: 400 });
  }
  const entry: LogEntry = {
    id: randomUUID(),
    date,
    kind,
    title,
    text,
    lesson: str(body.lesson, 300) || undefined,
    author: str(body.author, 80) || undefined,
    lat: Math.round(lat * 1e5) / 1e5,
    lon: Math.round(lon * 1e5) / 1e5,
    department: str(body.department, 10) || undefined,
    province: str(body.province, 4) || undefined,
    event: eventRef(body.event),
    createdAt: new Date().toISOString(),
  };
  // Serialize writes so concurrent posts don't overwrite each other.
  const task = queue.then(async () => {
    const entries = await readAll();
    entries.push(entry);
    await fs.mkdir(path.dirname(FILE), { recursive: true });
    await fs.writeFile(FILE, JSON.stringify(entries, null, 2));
  });
  queue = task.catch(() => undefined);
  await task;
  return NextResponse.json(entry, { status: 201 });
}
