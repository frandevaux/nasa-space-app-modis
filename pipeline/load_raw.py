"""Une todos los CSV de FIRMS (anuales por país + API del año en curso) en un esquema común.

Salidas:
  data/processed/detections_raw.parquet   (se comparte por HTTP con el equipo)
  raw.detections en PostGIS               (con --db)

MODIS y VIIRS tienen columnas distintas; acá solo se unifican nombres, sin transformar valores:
  MODIS: brightness, bright_t31      -> bright_main, bright_aux
  VIIRS: bright_ti4, bright_ti5      -> bright_main, bright_aux
`type` solo existe en los datos SP: en los NRT queda NULL (se calcula después, ver pipeline de preprocesamiento).

Uso:  uv run python load_raw.py [--db]
"""
from __future__ import annotations

import argparse
import os
import time

import duckdb

from common import DATA_RAW, ROOT, load_env

OUT = ROOT / "data" / "processed" / "detections_raw.parquet"
COUNTRY = DATA_RAW / "firms" / "country"
API = DATA_RAW / "firms" / "api"

# Columnas comunes de salida
SELECT = """
    CAST(latitude AS DOUBLE)            AS latitude,
    CAST(longitude AS DOUBLE)           AS longitude,
    CAST({bmain} AS DOUBLE)             AS bright_main,
    CAST({baux} AS DOUBLE)              AS bright_aux,
    CAST(scan AS DOUBLE)                AS scan,
    CAST(track AS DOUBLE)               AS track,
    CAST(acq_date AS DATE)              AS acq_date,
    lpad(CAST(acq_time AS VARCHAR), 4, '0') AS acq_time,
    CAST(satellite AS VARCHAR)          AS satellite,
    '{instrument}'                      AS instrument,
    CAST(confidence AS VARCHAR)         AS confidence,
    CAST(version AS VARCHAR)            AS version,
    CAST(frp AS DOUBLE)                 AS frp,
    CAST(daynight AS VARCHAR)           AS daynight,
    {type_expr}                         AS type,
    '{product}'                         AS product,
    '{origin}'                          AS origin
"""

MODIS = dict(bmain="brightness", baux="bright_t31", instrument="MODIS")
VIIRS = dict(bmain="bright_ti4", baux="bright_ti5", instrument="VIIRS")


def part(glob: str, cols: dict, product: str, origin: str, has_type: bool) -> str:
    sel = SELECT.format(
        **cols, product=product, origin=origin,
        type_expr="CAST(type AS INTEGER)" if has_type else "CAST(NULL AS INTEGER)",
    )
    return f"SELECT {sel} FROM read_csv('{glob}', header=true, all_varchar=true, union_by_name=true)"


def build_query() -> str:
    parts = [
        part(f"{COUNTRY}/modis/*.csv", MODIS, "MODIS", "country", True),
        part(f"{COUNTRY}/viirs-snpp/*.csv", VIIRS, "VIIRS_SNPP", "country", True),
        part(f"{COUNTRY}/viirs-jpss1/*.csv", VIIRS, "VIIRS_NOAA20", "country", True),
    ]
    for src_dir in sorted(API.iterdir()) if API.exists() else []:
        src = src_dir.name  # p. ej. MODIS_SP, VIIRS_SNPP_NRT
        files = [f for f in src_dir.glob("*.csv") if f.stat().st_size > 200]  # >200 B: algo más que el encabezado
        if not files:
            continue
        cols = MODIS if src.startswith("MODIS") else VIIRS
        product = src.rsplit("_", 1)[0]  # MODIS, VIIRS_SNPP, VIIRS_NOAA20, VIIRS_NOAA21
        parts.append(part(f"{src_dir}/*.csv", cols, product, f"api_{src.rsplit('_', 1)[1].lower()}", src.endswith("_SP")))

    union = "\nUNION ALL\n".join(parts)
    # Deduplicación exacta (mismo satélite, instante y posición) y marca de NRT por versión.
    return f"""
    WITH u AS ({union})
    SELECT *, version ILIKE '%NRT%' AS is_nrt
    FROM u
    QUALIFY row_number() OVER (
        PARTITION BY satellite, instrument, acq_date, acq_time, latitude, longitude
        ORDER BY (version ILIKE '%NRT%'), origin   -- si hay SP y NRT del mismo foco, gana SP
    ) = 1
    """


def to_parquet(con: duckdb.DuckDBPyConnection) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    t = time.time()
    con.execute(f"COPY ({build_query()}) TO '{OUT}' (FORMAT parquet, COMPRESSION zstd)")
    print(f"parquet: {OUT.relative_to(ROOT)} en {time.time()-t:.0f}s", flush=True)
    print(con.execute(f"""
        SELECT product, origin, is_nrt, count(*) n, min(acq_date) desde, max(acq_date) hasta,
               count(*) FILTER (WHERE type IS NULL) sin_type
        FROM '{OUT}' GROUP BY ALL ORDER BY product, desde
    """).df().to_string(index=False), flush=True)


DDL = """
DROP TABLE IF EXISTS raw.detections;
CREATE TABLE raw.detections (
    id bigserial PRIMARY KEY,
    latitude double precision NOT NULL,
    longitude double precision NOT NULL,
    bright_main double precision,
    bright_aux double precision,
    scan double precision,
    track double precision,
    acq_date date NOT NULL,
    acq_time char(4) NOT NULL,
    satellite text NOT NULL,
    instrument text NOT NULL,
    confidence text,
    version text,
    frp double precision,
    daynight char(1),
    type smallint,
    product text NOT NULL,
    origin text NOT NULL,
    is_nrt boolean NOT NULL
);
"""

COLS = ("latitude, longitude, bright_main, bright_aux, scan, track, acq_date, acq_time, satellite, "
        "instrument, confidence, version, frp, daynight, type, product, origin, is_nrt")


def to_postgres(con: duckdb.DuckDBPyConnection) -> None:
    import psycopg

    load_env()
    t = time.time()
    with psycopg.connect(os.environ["DATABASE_URL"]) as pg:
        pg.execute(DDL)
        # DuckDB escribe un CSV temporal y Postgres lo ingiere con COPY (mucho más rápido que fila por fila).
        tmp = OUT.with_suffix(".copy.csv")
        con.execute(f"COPY (SELECT {COLS} FROM '{OUT}') TO '{tmp}' (HEADER false, DELIMITER ',')")
        with pg.cursor() as cur, cur.copy(f"COPY raw.detections ({COLS}) FROM STDIN WITH (FORMAT csv)") as cp, open(tmp, "rb") as f:
            while chunk := f.read(8 << 20):
                cp.write(chunk)
        tmp.unlink()
        n = pg.execute("SELECT count(*) FROM raw.detections").fetchone()[0]
        print(f"  {n:,} filas copiadas", flush=True)
        pg.execute("""
            ALTER TABLE raw.detections ADD COLUMN geom geometry(Point, 4326)
              GENERATED ALWAYS AS (ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)) STORED;
            CREATE INDEX ON raw.detections USING gist (geom);
            CREATE INDEX ON raw.detections (acq_date);
            CREATE INDEX ON raw.detections (product, acq_date);
            ANALYZE raw.detections;
        """)
    print(f"postgres: raw.detections cargada en {time.time()-t:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="store_true", help="además de generar el Parquet, cargar en PostGIS")
    args = ap.parse_args()
    con = duckdb.connect()
    to_parquet(con)
    if args.db:
        to_postgres(con)


if __name__ == "__main__":
    main()
