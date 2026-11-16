"""Etapa 00 — inventario y validación de insumos para Córdoba.

No construye datos: verifica hotspots, límites IGN, POWER y landcover, y
escribe `data/inventory.json` con los conteos que usa el resto del pipeline.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config, parse_args, setup_logging, write_json  # noqa: E402


def cordoba_polygon(cfg: dict):
    prov = gpd.read_file(
        Path(cfg["paths"]["boundaries"]) / "ign_provincia.geojson",
        columns=["nam", "in1", "geometry"],
    )
    row = prov[prov["nam"].astype(str).str.strip() == cfg["region"]["province_name"]]
    if len(row) != 1:
        raise RuntimeError(f"No se encontró una única provincia {cfg['region']['province_name']!r}")
    return row.geometry.iloc[0], prov


def cordoba_departments(cfg: dict):
    dep = gpd.read_file(
        Path(cfg["paths"]["boundaries"]) / "ign_departamento.geojson",
        columns=["nam", "in1", "geometry"],
    )
    dep["dep_id"] = dep["in1"].astype(str).str.zfill(5)
    return dep[dep["dep_id"].str.startswith(cfg["region"]["province_in1"])].copy()


def scan_hotspots(cfg: dict, poly, smoke: bool) -> tuple[pd.DataFrame, dict]:
    path = Path(cfg["paths"]["prep_processed"]) / "hotspots.parquet"
    cols = [
        "hotspot_pk", "hotspot_id", "latitude", "longitude", "ts_utc",
        "frp", "confidence_incendio", "sensor", "satellite", "daynight",
        "scan_km", "track_km", "bright_main", "bright_aux",
    ]
    pf = pq.ParquetFile(path)
    available = set(pf.schema_arrow.names)
    cols = [c for c in cols if c in available]
    df = pq.read_table(path, columns=cols).to_pandas()
    n_total = len(df)

    # Recorte grueso por bbox de la provincia y luego point-in-polygon.
    minx, miny, maxx, maxy = poly.bounds
    m = ((df["longitude"] >= minx) & (df["longitude"] <= maxx) &
         (df["latitude"] >= miny) & (df["latitude"] <= maxy))
    df = df.loc[m].copy()
    df["in_cordoba"] = shapely.intersects_xy(poly, df["longitude"].to_numpy(),
                                             df["latitude"].to_numpy())
    df = df[df["in_cordoba"]].drop(columns=["in_cordoba"]).reset_index(drop=True)
    if smoke:
        df = df.head(200_000).copy()

    df["t0"] = ((pd.to_datetime(df["ts_utc"], utc=True)
                 + pd.Timedelta(hours=int(cfg["time"]["timezone_offset_hours"])))
                .dt.floor("D").dt.tz_localize(None))
    df["year"] = df["t0"].dt.year
    df["date"] = df["t0"]

    checks = {
        "input_rows_total": int(n_total),
        "cordoba_rows": int(len(df)),
        "smoke_subset": bool(smoke),
        "date_min": str(df["t0"].min().date()),
        "date_max": str(df["t0"].max().date()),
        "nulls": {c: int(df[c].isna().sum()) for c in df.columns},
        "frp_negative": int((df["frp"] < 0).sum()),
        "confidence_range": [float(df["confidence_incendio"].min()),
                             float(df["confidence_incendio"].max())],
        "sensors": df["sensor"].value_counts().to_dict(),
    }
    year_counts = df.groupby("year").size().to_dict()
    checks["hotspots_per_year"] = {int(k): int(v) for k, v in year_counts.items()}

    # Celdas-día únicas ~1 km (0.01° es una aproximación para el inventario).
    cells = df.assign(
        cilat=np.floor(df["latitude"] / 0.01).astype(np.int64),
        cilon=np.floor(df["longitude"] / 0.01).astype(np.int64),
    ).drop_duplicates(["cilat", "cilon", "t0"])
    checks["unique_cell_days_approx_1km"] = int(len(cells))

    for split in ("train", "val", "test"):
        a = pd.Timestamp(cfg["periods"][f"{split}_start"])
        b = pd.Timestamp(cfg["periods"][f"{split}_end"])
        checks[f"{split}_hotspots"] = int(((df["t0"] >= a) & (df["t0"] <= b)).sum())
    return df, checks


def scan_power(cfg: dict, smoke: bool) -> dict:
    power_dir = Path(cfg["paths"]["raw_power"])
    files = sorted(power_dir.glob("power_*.csv"))
    if not files:
        raise FileNotFoundError(f"No hay CSV POWER en {power_dir}")
    out = {
        "files": len(files),
        "cells_unique": len(files),
        "missing_value": int(cfg["weather"]["missing_value"]),
        "date_min": None,
        "date_max": None,
        "missing_2012_2016": 0,
        "rows_min": None,
        "rows_max": None,
        "columns": None,
    }
    sample = files if not smoke else files[:20]
    rows = []
    for f in sample:
        df = pd.read_csv(f, skiprows=14)
        out["columns"] = list(df.columns)
        rows.append(len(df))
        dates = pd.to_datetime(df["YEAR"].astype(str) + df["DOY"].astype(str).str.zfill(3),
                               format="%Y%j")
        out["date_min"] = str(min(pd.Timestamp(out["date_min"]) if out["date_min"] else dates.min(), dates.min()).date())
        out["date_max"] = str(max(pd.Timestamp(out["date_max"]) if out["date_max"] else dates.max(), dates.max()).date())
        mask = (dates >= pd.Timestamp("2012-01-01")) & (dates <= pd.Timestamp("2016-12-31"))
        out["missing_2012_2016"] += int((df.loc[mask, cfg["weather"]["variables"]] ==
                                         int(cfg["weather"]["missing_value"])).sum().sum())
    out["rows_min"] = int(min(rows))
    out["rows_max"] = int(max(rows))
    out["scanned_files"] = len(sample)

    mapping = power_dir / "departamento_to_cell.csv"
    if mapping.exists():
        mp = pd.read_csv(mapping, dtype={"departamento_id": str})
        mp["departamento_id"] = mp["departamento_id"].str.zfill(5)
        out["mapping_rows"] = int(len(mp))
        out["mapping_cells"] = int(mp[["cell_lat", "cell_lon"]].drop_duplicates().shape[0])
    return out


def scan_landcover(cfg: dict) -> dict:
    root = Path(cfg["paths"]["landcover"])
    files = sorted(root.glob("MCD12Q1.061_LC_Type1_doy*001000000_aid0001.tif"))
    years = []
    for f in files:
        name = f.name
        try:
            years.append(int(name.split("doy")[1][:4]))
        except Exception:  # noqa: BLE001
            pass
    wanted = [int(y) for y in cfg["static"]["landcover_years"]]
    return {
        "files": len(files),
        "years": sorted(years),
        "missing_wanted": sorted(set(wanted) - set(years)),
    }


def scan_protected(cfg: dict) -> dict:
    path = Path(cfg["paths"]["protected_areas"])
    gdf = gpd.read_file(path)
    invalid = int((~gdf.geometry.is_valid).sum())
    fixed = gdf.geometry.make_valid()
    return {
        "features": int(len(gdf)),
        "invalid_before": invalid,
        "invalid_after": int((~fixed.is_valid).sum()),
        "crs": str(gdf.crs),
    }


def main() -> int:
    args = parse_args("Inventario de insumos para Córdoba")
    cfg = load_config(args.config)
    log = setup_logging("00_inventory", Path(cfg["paths"]["data"]) / "logs" / "00_inventory.log",
                        cfg["run"]["log_level"])
    log.info("Config: %s", cfg["_config_path"])

    poly, _ = cordoba_polygon(cfg)
    dep = cordoba_departments(cfg)
    log.info("Córdoba: %d departamentos; bbox=%s", len(dep), poly.bounds)

    hs, hs_checks = scan_hotspots(cfg, poly, args.smoke)
    log.info("Hotspots: %d en Córdoba; %d train / %d val / %d test",
             hs_checks["cordoba_rows"], hs_checks["train_hotspots"],
             hs_checks["val_hotspots"], hs_checks["test_hotspots"])

    power = scan_power(cfg, args.smoke)
    log.info("POWER: %d archivos; %s..%s; faltantes 2012-2016=%d",
             power["files"], power["date_min"], power["date_max"],
             power["missing_2012_2016"])

    landcover = scan_landcover(cfg)
    protected = scan_protected(cfg)
    log.info("Landcover: %s; AP: %d features (%d inválidas)",
             landcover["years"], protected["features"], protected["invalid_before"])

    inventory = {
        "config": cfg["_config_path"],
        "smoke": bool(args.smoke),
        "province": cfg["region"]["province_name"],
        "departments": int(len(dep)),
        "department_ids": dep["dep_id"].tolist(),
        "hotspots": hs_checks,
        "power": power,
        "landcover": landcover,
        "protected_areas": protected,
    }
    out = Path(cfg["paths"]["data"]) / "inventory.json"
    write_json(out, inventory)
    log.info("Inventario escrito en %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
