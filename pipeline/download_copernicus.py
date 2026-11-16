"""Índices de peligro de incendio (FWI) de Copernicus CEMS para Argentina, diario, 2000 → hoy.

Fuente: EWDS, dataset `cems-fire-historical-v1` (reanálisis ERA5, sistema GEFF 4.1).
Necesita ~/.cdsapirc con el token (sirve el mismo de CDS) y la licencia CC-BY aceptada.

Un pedido por año (consolidado). Para los meses recientes que todavía no están consolidados
se usa el dataset intermedio. Los pedidos esperan en la cola de Copernicus: se lanzan varios en paralelo.

Destino: data/raw/climate/fwi/fwi_<año>[_intermediate].nc
Uso:     uv run python download_copernicus.py [--from 2000] [--workers 6]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import cdsapi

from common import DATA_RAW

EWDS = "https://ewds.climate.copernicus.eu/api"
DATASET = "cems-fire-historical-v1"
OUT = DATA_RAW / "climate" / "fwi"
AREA = [-21, -74, -56, -53]  # N, W, S, E (Argentina continental + Tierra del Fuego + Malvinas)
VARIABLES = [
    "fire_weather_index",
    "fine_fuel_moisture_code",
    "duff_moisture_code",
    "drought_code",
    "initial_fire_spread_index",
    "build_up_index",
]


def read_key() -> str:
    for line in (Path.home() / ".cdsapirc").read_text().splitlines():
        if line.startswith("key:"):
            return line.split(":", 1)[1].strip()
    raise SystemExit("falta key en ~/.cdsapirc")


def available_months() -> dict[str, dict[str, set[str]]]:
    """{dataset_type: {año: {meses}}} según las constraints publicadas del dataset."""
    meta = json.loads(urllib.request.urlopen(f"{EWDS}/catalogue/v1/collections/{DATASET}").read())
    href = next(l["href"] for l in meta["links"] if l["rel"] == "constraints")
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for r in json.loads(urllib.request.urlopen(href).read()):
        if "reanalysis" not in r.get("product_type", []):
            continue
        for dtype in r.get("dataset_type", []):
            for y in r.get("year", []):
                out[dtype][y] |= set(r.get("month", []))
    return out


def request(year: str, months: list[str], dtype: str) -> dict:
    return {
        "product_type": "reanalysis",
        "variable": VARIABLES,
        "dataset_type": dtype,
        "system_version": ["4_1"],
        "year": [year],
        "month": sorted(months),
        "day": [f"{d:02d}" for d in range(1, 32)],
        "grid": "0.25/0.25",
        "data_format": "netcdf",
        "area": AREA,
    }


def download(client: cdsapi.Client, req: dict, dest: Path) -> str:
    tmp = dest.with_suffix(".nc.part")
    t = time.time()
    for attempt in range(60):
        try:
            client.retrieve(DATASET, req, str(tmp))
            break
        except Exception as e:  # noqa: BLE001
            # Copernicus limita los pedidos en cola por dataset: esperar y reintentar.
            if "queued requests" in str(e) and attempt < 59:
                time.sleep(60)
                continue
            raise
    tmp.replace(dest)
    return f"{dest.name} {dest.stat().st_size/1e6:.0f} MB en {(time.time()-t)/60:.1f} min"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    avail = available_months()
    this_year = dt.date.today().year
    jobs = []
    for y in range(args.start, this_year + 1):
        ys = str(y)
        cons = avail["consolidated_dataset"].get(ys, set())
        if cons:
            jobs.append((ys, sorted(cons), "consolidated_dataset", OUT / f"fwi_{ys}.nc"))
        inter = avail["intermediate_dataset"].get(ys, set()) - cons
        if inter:
            jobs.append((ys, sorted(inter), "intermediate_dataset", OUT / f"fwi_{ys}_intermediate.nc"))

    # Los archivos del año en curso se rehacen siempre (se agregan meses nuevos).
    todo = [j for j in jobs if not j[3].exists() or j[0] == str(this_year)]
    print(f"{len(todo)} pedidos a Copernicus", flush=True)
    for ys, months, dtype, dest in todo:
        print(f"  {dest.name}: {dtype}, meses {months[0]}–{months[-1]}", flush=True)

    client = cdsapi.Client(url=EWDS, key=read_key(), quiet=True, progress=False)
    errors = []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(download, client, request(ys, m, dt_), dest): dest for ys, m, dt_, dest in todo}
        for f in as_completed(futs):
            try:
                print("ok ", f.result(), flush=True)
            except Exception as e:  # noqa: BLE001
                errors.append(futs[f].name)
                print("ERR", futs[f].name, e, flush=True)
    print(f"listo, {len(errors)} errores {errors}", flush=True)


if __name__ == "__main__":
    main()
