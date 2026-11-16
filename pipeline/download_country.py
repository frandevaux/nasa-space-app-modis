"""Descarga los CSV anuales por país de FIRMS para Argentina (no usa MAP_KEY).

Uso:  python3 pipeline/download_country.py [--workers 6]
Destino: data/raw/firms/country/<producto>/<producto>_<año>_Argentina.csv
Es idempotente: saltea los archivos ya descargados.
"""
from __future__ import annotations

import argparse
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import DATA_RAW, fetch

BASE = "https://firms.modaps.eosdis.nasa.gov/data/country"
LAST_FULL_YEAR = dt.date.today().year - 1

# producto FIRMS -> primer año disponible
PRODUCTS = {
    "modis": 2000,        # Terra + Aqua (desde nov-2000)
    "viirs-snpp": 2012,   # S-NPP (base de la serie VIIRS)
    "viirs-jpss1": 2018,  # NOAA-20 (relleno de huecos de S-NPP)
}


def jobs():
    for prod, first in PRODUCTS.items():
        for year in range(first, LAST_FULL_YEAR + 1):
            name = f"{prod}_{year}_Argentina.csv"
            yield f"{BASE}/{prod}/{year}/{name}", DATA_RAW / "firms" / "country" / prod / name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    pending = [(u, d) for u, d in jobs() if not d.exists()]
    print(f"{len(pending)} archivos por descargar", flush=True)
    total = 0
    errors = []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch, u, d): d for u, d in pending}
        for f in as_completed(futs):
            d = futs[f]
            try:
                n = f.result()
                total += n
                print(f"ok  {d.name}  {n/1e6:.1f} MB", flush=True)
            except Exception as e:  # noqa: BLE001
                errors.append(d.name)
                print(f"ERR {d.name}: {e}", flush=True)
    print(f"listo: {total/1e6:.0f} MB, {len(errors)} errores {errors}", flush=True)


if __name__ == "__main__":
    main()
