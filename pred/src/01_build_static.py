"""Etapa 01 — rasters estáticos de Córdoba en una grilla de 1 km (EPSG:6933).

Salidas en data/static/:
  grid.json, cordoba_mask.npy, dept_id.npy, ap.npy,
  landcover_<año>.npy, fire_climatology.npy
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ensure_dir, grid_from_bounds, grid_rowcol_from_xy,  # noqa: E402
                    load_config, parse_args, read_json, setup_logging, write_json)

def month_days(years: list[int]) -> dict[int, int]:
    out = {m: 0 for m in range(1, 13)}
    for y in years:
        for m in range(1, 13):
            out[m] += pd.Period(f"{y}-{m:02d}", freq="M").days_in_month
    return out


def load_polygons(cfg: dict):
    prov = gpd.read_file(Path(cfg["paths"]["boundaries"]) / "ign_provincia.geojson",
                         columns=["nam", "in1", "geometry"])
    cor = prov[prov["nam"].astype(str).str.strip() == cfg["region"]["province_name"]]
    if len(cor) != 1:
        raise RuntimeError("No se encontró una única provincia de Córdoba")
    poly = cor.geometry.iloc[0]

    dep = gpd.read_file(Path(cfg["paths"]["boundaries"]) / "ign_departamento.geojson",
                        columns=["nam", "in1", "geometry"])
    dep["dep_id"] = dep["in1"].astype(str).str.zfill(5)
    dep = dep[dep["dep_id"].str.startswith(cfg["region"]["province_in1"])].copy()
    dep = dep.sort_values("dep_id").reset_index(drop=True)
    dep["geometry"] = dep.geometry.make_valid()
    dep["dept_idx"] = np.arange(1, len(dep) + 1, dtype=np.int16)

    ap = gpd.read_file(cfg["paths"]["protected_areas"])
    ap["geometry"] = ap.geometry.make_valid()
    return poly, dep, ap


def build_grid(cfg: dict, poly) -> dict:
    crs = cfg["region"]["crs_grid"]
    poly_proj = gpd.GeoSeries([poly], crs="EPSG:4326").to_crs(crs).iloc[0]
    grid = grid_from_bounds(poly_proj.bounds, float(cfg["region"]["cell_size_m"]))
    grid["crs"] = crs
    grid["transform"] = list(from_origin(grid["x0"], grid["y1"],
                                         grid["cell_size_m"], grid["cell_size_m"]))[:6]
    return grid


def rasterize_mask(poly, grid: dict) -> np.ndarray:
    poly_proj = gpd.GeoSeries([poly], crs="EPSG:4326").to_crs(grid["crs"]).iloc[0]
    tr = from_origin(grid["x0"], grid["y1"], grid["cell_size_m"], grid["cell_size_m"])
    return rasterize([(poly_proj, 1)], out_shape=(grid["height"], grid["width"]),
                     transform=tr, fill=0, dtype="uint8").astype(np.uint8)


def rasterize_departments(dep, grid: dict) -> tuple[np.ndarray, dict]:
    dep_proj = dep.to_crs(grid["crs"])
    tr = from_origin(grid["x0"], grid["y1"], grid["cell_size_m"], grid["cell_size_m"])
    shapes = [(geom, int(idx)) for geom, idx in zip(dep_proj.geometry, dep_proj["dept_idx"])]
    arr = rasterize(shapes, out_shape=(grid["height"], grid["width"]), transform=tr,
                    fill=0, dtype="int16").astype(np.int16)
    mapping = {
        int(r.dept_idx): {"dep_id": str(r.dep_id), "name": str(r.nam)}
        for r in dep.itertuples()
    }
    return arr, mapping


def rasterize_ap(ap, grid: dict) -> np.ndarray:
    ap_proj = ap.to_crs(grid["crs"])
    tr = from_origin(grid["x0"], grid["y1"], grid["cell_size_m"], grid["cell_size_m"])
    shapes = [(geom, 1) for geom in ap_proj.geometry if not geom.is_empty]
    return rasterize(shapes, out_shape=(grid["height"], grid["width"]), transform=tr,
                     fill=0, dtype="uint8").astype(np.uint8)


def reproject_landcover(cfg: dict, grid: dict, year: int) -> np.ndarray:
    root = Path(cfg["paths"]["landcover"])
    path = root / f"MCD12Q1.061_LC_Type1_doy{year}001000000_aid0001.tif"
    if not path.exists():
        raise FileNotFoundError(path)
    tr = from_origin(grid["x0"], grid["y1"], grid["cell_size_m"], grid["cell_size_m"])
    dst = np.full((grid["height"], grid["width"]), 255, dtype=np.uint8)
    with rasterio.open(path) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata if src.nodata is not None else 255,
            dst_transform=tr,
            dst_crs=grid["crs"],
            dst_nodata=255,
            resampling=Resampling.nearest,
        )
    return dst


def build_fire_climatology(cfg: dict, grid: dict) -> np.ndarray:
    """Frecuencia de días con hotspot por celda y mes, solo con años de train."""
    years = [int(y) for y in cfg["static"]["fire_climatology_years"]]
    start = pd.Timestamp(f"{min(years)}-01-01", tz="UTC")
    end = pd.Timestamp(f"{max(years) + 1}-01-01", tz="UTC")
    path = Path(cfg["paths"]["prep_processed"]) / "hotspots.parquet"
    hs = pd.read_parquet(path, columns=["latitude", "longitude", "ts_utc"])
    hs = hs[(pd.to_datetime(hs["ts_utc"], utc=True) >= start) &
            (pd.to_datetime(hs["ts_utc"], utc=True) < end)].copy()
    lon = hs["longitude"].to_numpy()
    lat = hs["latitude"].to_numpy()
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
    x, y = fwd.transform(lon, lat)
    row, col = grid_rowcol_from_xy(x, y, grid)
    ok = (row >= 0) & (row < grid["height"]) & (col >= 0) & (col < grid["width"])
    row, col = row[ok], col[ok]
    mask = np.load(Path(cfg["paths"]["static"]) / "cordoba_mask.npy") if (Path(cfg["paths"]["static"]) / "cordoba_mask.npy").exists() else None
    if mask is not None:
        ok2 = mask[row, col].astype(bool)
        row, col = row[ok2], col[ok2]

    dates = ((pd.to_datetime(hs["ts_utc"], utc=True) +
              pd.Timedelta(hours=int(cfg["time"]["timezone_offset_hours"])))
             .dt.floor("D").dt.tz_localize(None))
    dates = dates.to_numpy()[ok]
    if mask is not None:
        dates = dates[ok2]
    month = pd.to_datetime(dates).month.to_numpy()
    cell = row.astype(np.int64) * grid["width"] + col.astype(np.int64)

    df = pd.DataFrame({"cell": cell, "month": month, "date": dates})
    df = df.drop_duplicates(["cell", "month", "date"])
    counts = df.groupby(["month", "cell"]).size().reset_index(name="n")
    out = np.zeros((12, grid["height"], grid["width"]), dtype=np.float32)
    mdays = month_days(years)
    for m, g in counts.groupby("month"):
        denom = max(mdays[int(m)], 1)
        np.add.at(out[int(m) - 1].ravel(), g["cell"].to_numpy(),
                  g["n"].to_numpy().astype(np.float32) / denom)
    return np.clip(out, 0.0, 1.0)


def main() -> int:
    args = parse_args("Rasters estáticos de Córdoba 1 km")
    cfg = load_config(args.config)
    data_dir = ensure_dir(cfg["paths"]["data"])
    static_dir = ensure_dir(cfg["paths"]["static"])
    log = setup_logging("01_build_static", data_dir / "logs" / "01_build_static.log",
                        cfg["run"]["log_level"])
    log.info("Config: %s", cfg["_config_path"])

    poly, dep, ap = load_polygons(cfg)
    grid = build_grid(cfg, poly)
    log.info("Grilla: %dx%d celdas de %.0f m; x=%.0f..%.0f y=%.0f..%.0f",
             grid["width"], grid["height"], grid["cell_size_m"],
             grid["x0"], grid["x1"], grid["y0"], grid["y1"])

    mask = rasterize_mask(poly, grid)
    np.save(static_dir / "cordoba_mask.npy", mask)
    log.info("Máscara Córdoba: %d celdas dentro", int(mask.sum()))

    dept, dept_map = rasterize_departments(dep, grid)
    np.save(static_dir / "dept_id.npy", dept)
    log.info("Departamentos rasterizados: %d", len(dept_map))

    ap_arr = rasterize_ap(ap, grid)
    np.save(static_dir / "ap.npy", ap_arr)
    log.info("Área protegida: %d celdas", int(ap_arr.sum()))

    years = [int(y) for y in cfg["static"]["landcover_years"]]
    if args.smoke:
        years = [max(years)]
    for year in years:
        arr = reproject_landcover(cfg, grid, year)
        np.save(static_dir / f"landcover_{year}.npy", arr)
        log.info("Landcover %d: %d celdas válidas", year, int((arr != 255).sum()))

    clim = build_fire_climatology(cfg, grid)
    np.save(static_dir / "fire_climatology.npy", clim)
    log.info("Climatología de fuego: max=%.4f", float(clim.max()))

    write_json(static_dir / "grid.json", grid)
    write_json(static_dir / "departments.json", dept_map)
    manifest = {
        "grid": grid,
        "mask_cells": int(mask.sum()),
        "departments": len(dept_map),
        "ap_cells": int(ap_arr.sum()),
        "landcover_years": years,
        "fire_climatology_shape": list(clim.shape),
    }
    write_json(static_dir / "static_manifest.json", manifest)
    log.info("Estáticos escritos en %s", static_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
