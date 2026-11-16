"""Descargas de clima sin cuenta:
  1. NASA POWER diario (2000 → ayer) en un punto por departamento del IGN.
     POWER usa una grilla de 0,5° × 0,625°: los departamentos que caen en la misma celda comparten descarga.
  2. Índice ONI (ENSO) de NOAA CPC.

Destino:
  data/raw/climate/power/power_<lat>_<lon>.csv
  data/raw/climate/power/departamento_to_cell.csv    (departamento -> celda POWER)
  data/raw/climate/oni.ascii.txt

Uso:  uv run python download_climate.py [--workers 4]
Idempotente: saltea celdas ya descargadas.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import geopandas as gpd

from common import DATA_RAW, ROOT, fetch

OUT = DATA_RAW / "climate"
POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
# Temperatura media y máxima, humedad relativa, lluvia, viento máximo a 10 m, humedad del suelo superficial
PARAMS = "T2M,T2M_MAX,RH2M,PRECTOTCORR,WS10M_MAX,GWETTOP"
START = "20000101"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"


def power_cell(lat: float, lon: float) -> tuple[float, float]:
    """Centro de la celda POWER (0,5° lat × 0,625° lon) que contiene el punto."""
    clat = math.floor((lat + 90) / 0.5) * 0.5 - 90 + 0.25
    clon = math.floor((lon + 180) / 0.625) * 0.625 - 180 + 0.3125
    return round(clat, 4), round(clon, 4)


def departamento_points() -> gpd.GeoDataFrame:
    dep = gpd.read_file(ROOT / "data" / "boundaries" / "shp" / "ign_departamento.zip")
    pts = dep.geometry.representative_point()  # siempre cae dentro del polígono
    g = gpd.GeoDataFrame({"departamento_id": dep["in1"].astype(str).str.zfill(5), "name": dep["nam"]},
                         geometry=pts, crs=dep.crs)
    g = g[(g.geometry.y > -56) & (g.geometry.x < -53)]  # sin sector antártico ni Atlántico Sur
    g["lat"], g["lon"] = g.geometry.y.round(4), g.geometry.x.round(4)
    cells = [power_cell(la, lo) for la, lo in zip(g.lat, g.lon)]
    g["cell_lat"] = [c[0] for c in cells]
    g["cell_lon"] = [c[1] for c in cells]
    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    fetch(ONI_URL, OUT / "oni.ascii.txt")
    print("ok  oni.ascii.txt", flush=True)

    g = departamento_points()
    (OUT / "power").mkdir(parents=True, exist_ok=True)
    g.drop(columns="geometry").to_csv(OUT / "power" / "departamento_to_cell.csv", index=False)
    cells = sorted(set(zip(g.cell_lat, g.cell_lon)))
    print(f"{len(g)} departamentos -> {len(cells)} celdas POWER", flush=True)

    end = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")
    jobs = []
    for la, lo in cells:
        dest = OUT / "power" / f"power_{la}_{lo}.csv"
        if dest.exists():
            continue
        url = (f"{POWER}?parameters={PARAMS}&community=AG&latitude={la}&longitude={lo}"
               f"&start={START}&end={end}&format=CSV&time-standard=LST")
        jobs.append((url, dest))
    print(f"{len(jobs)} celdas por descargar", flush=True)

    errors = []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch, u, d, 4, 300): d for u, d in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            d = futs[f]
            try:
                n = f.result()
                print(f"[{i}/{len(jobs)}] ok {d.name} {n/1e3:.0f} kB", flush=True)
            except Exception as e:  # noqa: BLE001
                errors.append(d.name)
                print(f"[{i}/{len(jobs)}] ERR {d.name}: {e}", flush=True)
    print(f"listo, {len(errors)} errores {errors}", flush=True)


if __name__ == "__main__":
    main()
