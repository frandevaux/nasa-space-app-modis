"""Descarga por la Area API de FIRMS lo que no cubren los archivos anuales: el año en curso.

Para cada fuente usa SP (definitivo, trae `type`) mientras esté disponible y NRT después.
Los rangos se leen de /api/data_availability, así que el script sirve también para refrescar.

Uso:  python3 pipeline/download_api.py [--from 2026-01-01]
Destino: data/raw/firms/api/<SOURCE>/<SOURCE>_<inicio>_<dias>d.csv
Idempotente: saltea los bloques ya bajados, salvo los NRT de los últimos 3 días (se rehacen).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import time

from common import ARG_BBOX, DATA_RAW, fetch, get_text, load_env

API = "https://firms.modaps.eosdis.nasa.gov/api"
CHUNK_DAYS = 5  # máximo permitido por la API

# familia -> (fuente SP, fuente NRT)
FAMILIES = {
    "MODIS": ("MODIS_SP", "MODIS_NRT"),
    "VIIRS_SNPP": ("VIIRS_SNPP_SP", "VIIRS_SNPP_NRT"),
    "VIIRS_NOAA20": ("VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"),
    # NOAA-21 solo para la capa de focos recientes del mapa (no entra en la serie histórica)
    "VIIRS_NOAA21": (None, "VIIRS_NOAA21_NRT"),
}


def availability(key: str) -> dict[str, tuple[dt.date, dt.date]]:
    text = get_text(f"{API}/data_availability/csv/{key}/all")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        out[row["data_id"]] = (dt.date.fromisoformat(row["min_date"]), dt.date.fromisoformat(row["max_date"]))
    return out


def mapkey_status(key: str) -> dict:
    return json.loads(get_text(f"https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/?MAP_KEY={key}"))


def chunks(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        n = min(CHUNK_DAYS, (end - d).days + 1)
        yield d, n
        d += dt.timedelta(days=n)


def plan(avail, start: dt.date):
    """Lista de (source, inicio, días). SP hasta su último día; NRT desde el día siguiente."""
    today = dt.date.today()
    for sp, nrt in FAMILIES.values():
        nrt_from = start
        if sp and sp in avail:
            sp_min, sp_max = avail[sp]
            s = max(start, sp_min)
            if s <= sp_max:
                for c in chunks(s, sp_max):
                    yield sp, *c
            nrt_from = max(start, sp_max + dt.timedelta(days=1))
        if nrt in avail:
            n_min, n_max = avail[nrt]
            s = max(nrt_from, n_min)
            for c in chunks(s, min(n_max, today)):
                yield nrt, *c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=f"{dt.date.today().year}-01-01")
    ap.add_argument("--max-transactions", type=int, default=4000, help="margen bajo el límite de 5000/10 min")
    args = ap.parse_args()

    load_env()
    key = os.environ["MAP_KEY"]
    avail = availability(key)
    start = dt.date.fromisoformat(args.start)
    today = dt.date.today()

    todo = []
    for source, d0, n in plan(avail, start):
        dest = DATA_RAW / "firms" / "api" / source / f"{source}_{d0.isoformat()}_{n}d.csv"
        recent = source.endswith("_NRT") and (today - (d0 + dt.timedelta(days=n - 1))).days < 3
        if dest.exists() and not recent:
            continue
        todo.append((source, d0, n, dest))
    print(f"{len(todo)} requests por hacer", flush=True)

    for i, (source, d0, n, dest) in enumerate(todo, 1):
        if i % 25 == 1:
            st = mapkey_status(key)
            used = st.get("current_transactions", 0)
            if used >= args.max_transactions:
                print(f"cuota cerca del límite ({used}); espero 10 min", flush=True)
                time.sleep(600)
        url = f"{API}/area/csv/{key}/{source}/{ARG_BBOX}/{n}/{d0.isoformat()}"
        size = fetch(url, dest)
        head = dest.read_text()[:200]
        if not head.startswith("latitude"):
            dest.unlink()
            raise SystemExit(f"respuesta inesperada para {source} {d0}: {head!r}")
        print(f"[{i}/{len(todo)}] {source} {d0} +{n}d  {size/1e3:.0f} kB", flush=True)

    print("estado de la key:", mapkey_status(key), flush=True)


if __name__ == "__main__":
    main()
