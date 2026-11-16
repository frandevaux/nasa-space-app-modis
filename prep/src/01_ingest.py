"""Etapa 01 — ingesta y esquema unificado de hotspots.

Lee los CSV crudos (country + API), excluye sidecars AppleDouble, normaliza
columnas MODIS/VIIRS, rellena `acq_time` a HHMM y calcula ts_utc / ts_local.

Salidas:
  prep/data/interim/00_csv_manifest.parquet
  prep/data/interim/01_hotspots_raw.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RunContext, open_duckdb, write_parquet_atomic  # noqa: E402
from io_utils import (add_file_hashes, check_expected_counts, copy_query_to_parquet,
                      discover_files, summary_by)  # noqa: E402


def _files_sql(paths: list[str]) -> str:
    escaped = []
    for p in paths:
        escaped.append("'" + str(p).replace("'", "''") + "'")
    return "[" + ", ".join(escaped) + "]"


def build_query(manifest: pd.DataFrame, cfg: dict, files_sql: str) -> str:
    tz_offset = int(cfg["pass_bin"]["utc_offset_hours"])
    fmt = cfg["ingest"]["timestamp_format"]
    return f"""
WITH raw AS (
    SELECT *
    FROM read_csv(
        {files_sql},
        header = true,
        all_varchar = true,
        union_by_name = true,
        filename = true
    )
),
joined AS (
    SELECT
        r.*,
        m."group" AS source_group,
        m.source AS source,
        m.sensor AS sensor,
        m.product AS product,
        m.priority AS priority
    FROM raw r
    JOIN manifest m ON r.filename = m.path
),
norm AS (
    SELECT
        source_group,
        source,
        sensor,
        product,
        priority,
        filename AS source_file,
        row_number() OVER (PARTITION BY filename) AS source_row,
        CAST(latitude AS DOUBLE) AS latitude,
        CAST(longitude AS DOUBLE) AS longitude,
        CAST(scan AS DOUBLE) AS scan_km,
        CAST(track AS DOUBLE) AS track_km,
        COALESCE(CAST(brightness AS DOUBLE), CAST(bright_ti4 AS DOUBLE)) AS bright_main,
        COALESCE(CAST(bright_t31 AS DOUBLE), CAST(bright_ti5 AS DOUBLE)) AS bright_aux,
        CAST(frp AS DOUBLE) AS frp,
        trim(confidence) AS conf_raw,
        trim(version) AS version,
        upper(trim(instrument)) AS instrument,
        upper(trim(daynight)) AS daynight,
        CASE
            WHEN satellite = 'N' THEN 'SNPP'
            WHEN satellite = 'N20' THEN 'NOAA20'
            WHEN satellite = 'N21' THEN 'NOAA21'
            ELSE satellite
        END AS satellite,
        trY_cast(trim(type) AS INTEGER) AS type,
        lpad(trim(acq_time), 4, '0') AS acq_time_padded,
        trim(acq_date) AS acq_date,
        trY_strptime(trim(acq_date) || lpad(trim(acq_time), 4, '0'), '{fmt}') AS ts_utc
    FROM joined
),
valid AS (
    SELECT
        *,
        ts_utc + INTERVAL '{tz_offset} hours' AS ts_local
    FROM norm
    WHERE ts_utc IS NOT NULL
      AND scan_km > 0
      AND track_km > 0
)
SELECT
    source_group, source, sensor, product, priority,
    source_file, source_row,
    latitude, longitude,
    ts_utc, ts_local,
    satellite, instrument, daynight,
    scan_km, track_km,
    bright_main, bright_aux, frp,
    conf_raw, version, type,
    acq_date, acq_time_padded AS acq_time
FROM valid
"""


def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("01_ingest", argv)
    try:
        cfg = ctx.cfg
        manifest = discover_files(ctx)
        counts = check_expected_counts(manifest, cfg, strict=not ctx.smoke)
        manifest = add_file_hashes(manifest, enabled=True)
        manifest_path = ctx.interim("00_csv_manifest.parquet")
        write_parquet_atomic(manifest, manifest_path)
        ctx.log.info("Manifest: %d archivos, %d bytes", len(manifest), int(manifest["size_bytes"].sum()))
        ctx.stats.add("ingest.files", int(len(manifest)))
        ctx.stats.add("ingest.bytes", int(manifest["size_bytes"].sum()))
        ctx.stats.add("ingest.group_counts", counts["counts"])
        if counts["mismatches"]:
            ctx.stats.warn(f"Conteos inesperados (permitido en smoke): {counts['mismatches']}")

        con = open_duckdb(ctx)
        con.register("manifest", manifest)

        files_sql = _files_sql(manifest["path"].tolist())
        query = build_query(manifest, cfg, files_sql)
        dest = ctx.interim("01_hotspots_raw.parquet")
        copy_query_to_parquet(con, query, dest, row_group_size=100_000)

        # Conteos y controles.
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{dest}')").fetchone()[0]
        ctx.stats.add("ingest.rows_raw", int(rows))
        ctx.stats.table("ingest.by_group", con.execute(
            f"SELECT source_group, count(*) AS rows FROM read_parquet('{dest}') "
            "GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall())
        ctx.stats.table("ingest.by_product", con.execute(
            f"SELECT product, count(*) AS rows FROM read_parquet('{dest}') "
            "GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall())
        null_ts = con.execute(
            f"SELECT count(*) FROM read_parquet('{dest}') WHERE ts_utc IS NULL"
        ).fetchone()[0]
        bad_scan = con.execute(
            f"SELECT count(*) FROM read_parquet('{dest}') WHERE scan_km <= 0 OR track_km <= 0"
        ).fetchone()[0]
        ctx.stats.add("ingest.null_ts", int(null_ts))
        ctx.stats.add("ingest.bad_scan_track", int(bad_scan))
        if null_ts or bad_scan:
            ctx.stats.warn(f"Filas descartadas por timestamp/scan: {null_ts + bad_scan}")

        # Distribución anual y rango temporal.
        ctx.stats.table("ingest.by_year", con.execute(
            f"SELECT year(ts_utc) AS year, count(*) AS rows FROM read_parquet('{dest}') "
            "GROUP BY 1 ORDER BY 1"
        ).fetchall())
        minmax = con.execute(
            f"SELECT min(ts_utc), max(ts_utc), min(latitude), max(latitude), "
            f"min(longitude), max(longitude) FROM read_parquet('{dest}')"
        ).fetchone()
        ctx.stats.add("ingest.ts_min", str(minmax[0]))
        ctx.stats.add("ingest.ts_max", str(minmax[1]))
        ctx.stats.add("ingest.lat_range", [float(minmax[2]), float(minmax[3])])
        ctx.stats.add("ingest.lon_range", [float(minmax[4]), float(minmax[5])])

        ctx.stats.add("ingest.manifest_sha256", str(manifest["manifest_sha256"].iloc[0]))
        ctx.stats.flush()
        ctx.log.info("Etapa 01 OK: %d filas -> %s", rows, dest)
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 01 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
