"""Etapa 02 — muestras de hotspots y clima para Córdoba.

Una muestra por hotspot (o por celda-día si `dataset.dedup_cell_day`).
Salidas en data/hotspots/:
  index.parquet, hotspots_long.parquet, weather.npy,
  hotspot_forecast_7d.parquet, meta.json, stats.json, power_cells.json
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ensure_dir, grid_lonlat_from_rowcol, grid_rowcol_from_xy,  # noqa: E402
                    load_config, parse_args, read_json, setup_logging,
                    write_json, write_parquet_atomic)

POWER_ORIGIN = pd.Timestamp("2000-01-01")
POWER_NDAYS = 9814  # 2000-01-01 .. 2026-11-13 inclusive


def load_grid(cfg: dict) -> dict:
    return read_json(Path(cfg["paths"]["static"]) / "grid.json")


def load_cordoba_hotspots(cfg: dict, grid: dict) -> pd.DataFrame:
    path = Path(cfg["paths"]["prep_processed"]) / "hotspots.parquet"
    cols = ["hotspot_pk", "hotspot_id", "latitude", "longitude", "ts_utc",
            "frp", "confidence_incendio", "sensor", "satellite", "daynight",
            "scan_km", "track_km", "bright_main", "bright_aux"]
    hs = pd.read_parquet(path, columns=cols)
    hs["ts_utc"] = pd.to_datetime(hs["ts_utc"], utc=True)

    # Ventana que cubre todos los anclas y sus etiquetas de 7 días.
    starts = [pd.Timestamp(cfg["periods"][k]) for k in
              ("train_start", "val_start", "test_start")]
    ends = [pd.Timestamp(cfg["periods"][k]) for k in
            ("train_end", "val_end", "test_end")]
    lo = min(starts) - pd.Timedelta(days=30)
    hi = max(ends) + pd.Timedelta(days=8)
    hs = hs[(hs["ts_utc"] >= lo.tz_localize("UTC")) &
            (hs["ts_utc"] < hi.tz_localize("UTC"))].copy()

    fwd = Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
    x, y = fwd.transform(hs["longitude"].to_numpy(), hs["latitude"].to_numpy())
    row, col = grid_rowcol_from_xy(x, y, grid)
    mask = np.load(Path(cfg["paths"]["static"]) / "cordoba_mask.npy")
    ok = (row >= 0) & (row < grid["height"]) & (col >= 0) & (col < grid["width"])
    ok &= mask[np.clip(row, 0, grid["height"] - 1), np.clip(col, 0, grid["width"] - 1)].astype(bool)
    hs = hs.loc[ok].copy()
    hs["row"] = row[ok]
    hs["col"] = col[ok]
    hs["x"] = x[ok]
    hs["y"] = y[ok]
    hs["cell_id"] = hs["row"].astype(np.int64) * grid["width"] + hs["col"].astype(np.int64)
    hs["t0"] = ((hs["ts_utc"] +
                 pd.Timedelta(hours=int(cfg["time"]["timezone_offset_hours"])))
                .dt.floor("D").dt.tz_localize(None))
    hs["frp"] = hs["frp"].fillna(0.0).clip(lower=0.0)
    hs["confidence_incendio"] = hs["confidence_incendio"].fillna(0.0).clip(0, 100)
    hs["sensor_code"] = hs["sensor"].map({"MODIS": 0, "VIIRS": 1}).fillna(-1).astype(np.int8)
    hs["daynight_code"] = hs["daynight"].map({"D": 0, "N": 1}).fillna(-1).astype(np.int8)
    return hs


def build_anchors(cfg: dict, grid: dict, hs: pd.DataFrame) -> pd.DataFrame:
    train_start = pd.Timestamp(cfg["periods"]["train_start"])
    train_end = pd.Timestamp(cfg["periods"]["train_end"])
    val_start = pd.Timestamp(cfg["periods"]["val_start"])
    val_end = pd.Timestamp(cfg["periods"]["val_end"])
    test_start = pd.Timestamp(cfg["periods"]["test_start"])
    test_end = pd.Timestamp(cfg["periods"]["test_end"])
    m_train = (hs["t0"] >= train_start) & (hs["t0"] <= train_end)
    m_val = (hs["t0"] >= val_start) & (hs["t0"] <= val_end)
    m_test = (hs["t0"] >= test_start) & (hs["t0"] <= test_end)
    anchors = hs.loc[m_train | m_val | m_test].copy()
    anchors["split"] = np.select(
        [m_train.loc[anchors.index], m_val.loc[anchors.index], m_test.loc[anchors.index]],
        ["train", "val", "test"], default="train",
    )

    if bool(cfg["dataset"].get("dedup_cell_day", False)):
        anchors = (anchors.sort_values(["t0", "row", "col", "frp"],
                                       ascending=[True, True, True, False])
                   .drop_duplicates(["t0", "row", "col"], keep="first"))

    anchors = anchors.sort_values(["t0", "row", "col", "hotspot_pk"],
                                  kind="stable").reset_index(drop=True)
    anchors["anchor_idx"] = np.arange(len(anchors), dtype=np.int64)
    inv = Transformer.from_crs(grid["crs"], "EPSG:4326", always_xy=True)
    lon, lat = inv.transform(anchors["x"].to_numpy(), anchors["y"].to_numpy())
    anchors["center_lon"] = lon
    anchors["center_lat"] = lat
    anchors["doy"] = anchors["t0"].dt.day_of_year.astype(np.int16)
    anchors["hora_local"] = ((anchors["ts_utc"] +
                              pd.Timedelta(hours=int(cfg["time"]["timezone_offset_hours"])))
                             .dt.hour.astype(np.int8))
    return anchors


def build_long(cfg: dict, grid: dict, hs: pd.DataFrame, anchors: pd.DataFrame,
               log) -> pd.DataFrame:
    """Hotspots dentro del parche 32x32 y de la ventana [t0-13, t0+7]."""
    n_hist = int(cfg["grid"]["history_days"])
    horizon = int(cfg["grid"]["horizon_days"])
    half = int(cfg["grid"]["patch_cells"]) // 2
    max_off = half * float(cfg["region"]["cell_size_m"]) * np.sqrt(2.0) + 1500.0

    tree = cKDTree(np.c_[hs["x"].to_numpy(), hs["y"].to_numpy()])
    hs_row = hs["row"].to_numpy(np.int64)
    hs_col = hs["col"].to_numpy(np.int64)
    hs_pk = hs["hotspot_pk"].to_numpy(np.int64)
    hs_frp = hs["frp"].to_numpy(np.float32)
    hs_conf = hs["confidence_incendio"].to_numpy(np.float32)
    hs_sensor = hs["sensor_code"].to_numpy(np.int8)
    hs_dn = hs["daynight_code"].to_numpy(np.int8)
    hs_t0 = hs["t0"].to_numpy("datetime64[D]")

    a_x = anchors["x"].to_numpy()
    a_y = anchors["y"].to_numpy()
    a_row = anchors["row"].to_numpy(np.int64)
    a_col = anchors["col"].to_numpy(np.int64)
    a_day = anchors["t0"].to_numpy("datetime64[D]")
    a_idx = anchors["anchor_idx"].to_numpy(np.int64)

    out_anchor, out_pk, out_off = [], [], []
    out_dx, out_dy, out_frp, out_conf, out_sensor, out_dn = [], [], [], [], [], []
    for i in range(len(anchors)):
        idx = tree.query_ball_point((a_x[i], a_y[i]), max_off)
        if not idx:
            continue
        idx = np.asarray(idx, dtype=np.int64)
        dx = hs_col[idx] - a_col[i]
        dy = hs_row[idx] - a_row[i]
        day_off = (hs_t0[idx] - a_day[i]).astype("timedelta64[D]").astype(np.int32)
        m = (dx >= -half) & (dx <= half - 1) & (dy >= -half) & (dy <= half - 1)
        m &= (day_off >= -n_hist) & (day_off <= horizon)
        if not m.any():
            continue
        j = idx[m]
        out_anchor.append(np.full(j.size, a_idx[i], dtype=np.int64))
        out_pk.append(hs_pk[j])
        out_off.append(day_off[m].astype(np.int8))
        out_dx.append(dx[m].astype(np.int16))
        out_dy.append(dy[m].astype(np.int16))
        out_frp.append(hs_frp[j])
        out_conf.append(hs_conf[j])
        out_sensor.append(hs_sensor[j])
        out_dn.append(hs_dn[j])
        if (i + 1) % 2000 == 0:
            log.info("Long: %d/%d anclas", i + 1, len(anchors))

    if not out_anchor:
        raise RuntimeError("No se generó ningún hotspot_long")
    df = pd.DataFrame({
        "anchor_idx": np.concatenate(out_anchor),
        "hotspot_pk": np.concatenate(out_pk),
        "day_offset": np.concatenate(out_off),
        "dx": np.concatenate(out_dx),
        "dy": np.concatenate(out_dy),
        "frp": np.concatenate(out_frp),
        "confidence": np.concatenate(out_conf),
        "sensor_code": np.concatenate(out_sensor),
        "daynight_code": np.concatenate(out_dn),
    })
    log.info("Long: %d filas para %d anclas", len(df), df["anchor_idx"].nunique())
    return df


def parse_power_cells(cfg: dict) -> tuple[list[tuple[float, float]], np.ndarray, np.ndarray]:
    from pyproj import Transformer
    files = sorted(Path(cfg["paths"]["raw_power"]).glob("power_*.csv"))
    cells = []
    for f in files:
        stem = f.stem.replace("power_", "")
        lat, lon = stem.split("_")
        cells.append((float(lat), float(lon)))
    lat = np.array([c[0] for c in cells], dtype=float)
    lon = np.array([c[1] for c in cells], dtype=float)
    return cells, lat, lon


def load_power_arrays(cfg: dict, cells: list[tuple[float, float]]) -> dict[tuple[float, float], np.ndarray]:
    """{cell: (9814, 6) float32} con NaN en faltantes."""
    variables = list(cfg["weather"]["variables"])
    missing = float(cfg["weather"]["missing_value"])
    out = {}
    for lat, lon in cells:
        path = Path(cfg["paths"]["raw_power"]) / f"power_{lat}_{lon}.csv"
        df = pd.read_csv(path, skiprows=14)
        dates = pd.to_datetime(df["YEAR"].astype(str) + df["DOY"].astype(str).str.zfill(3),
                               format="%Y%j")
        off = (dates - POWER_ORIGIN).dt.days.to_numpy()
        arr = np.full((POWER_NDAYS, len(variables)), np.nan, dtype=np.float32)
        vals = df[variables].to_numpy(dtype=np.float32)
        vals[vals == missing] = np.nan
        ok = (off >= 0) & (off < POWER_NDAYS)
        arr[off[ok]] = vals[ok]
        out[(float(lat), float(lon))] = arr
    return out


def assign_power_cells(cfg: dict, grid: dict, anchors: pd.DataFrame,
                       cells: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
    cell_lat = np.array([c[0] for c in cells], dtype=float)
    cell_lon = np.array([c[1] for c in cells], dtype=float)
    cx, cy = fwd.transform(cell_lon, cell_lat)
    tree = cKDTree(np.c_[cx, cy])
    _, idx = tree.query(np.c_[anchors["x"].to_numpy(), anchors["y"].to_numpy()], k=1)
    return idx, (cell_lat[idx], cell_lon[idx])


def build_weather(cfg: dict, anchors: pd.DataFrame, cell_idx: np.ndarray,
                  cells: list[tuple[float, float]],
                  power: dict[tuple[float, float], np.ndarray]) -> np.ndarray:
    pad = int(cfg["grid"]["weather_pad_days"])
    hist = int(cfg["grid"]["history_days"])
    horizon = int(cfg["grid"]["horizon_days"])
    n_days = pad + hist + horizon  # -43 .. +7
    out = np.full((len(anchors), n_days, 6), np.nan, dtype=np.float32)
    t0_off = (anchors["t0"] - POWER_ORIGIN).dt.days.to_numpy()
    for i, (ci, off) in enumerate(zip(cell_idx, t0_off)):
        arr = power[cells[int(ci)]]
        lo = int(off) - pad - hist + 1
        hi = lo + n_days
        sl = arr[max(lo, 0):min(hi, POWER_NDAYS)]
        dst_lo = max(0, -lo)
        out[i, dst_lo:dst_lo + len(sl)] = sl
    return out


def derived_weather(raw: np.ndarray) -> dict[str, np.ndarray]:
    """raw: (..., 6) T2M, T2M_MAX, RH2M, PRECIP, WS10M_MAX, GWETTOP."""
    t2m = raw[..., 0]
    rh = raw[..., 2]
    precip = raw[..., 3]
    es = 0.6108 * np.exp(17.27 * t2m / (t2m + 237.3))
    vpd = es * (1.0 - rh / 100.0)
    wet = precip >= 1.0
    days_since = np.zeros_like(precip, dtype=np.float32)
    count = np.zeros(precip.shape[:-1], dtype=np.float32)
    n_days = precip.shape[-1]
    for t in range(n_days):
        count = np.where(wet[..., t], 0.0, np.minimum(count + 1.0, 30.0))
        days_since[..., t] = count
    p7 = np.zeros_like(precip, dtype=np.float32)
    p30 = np.zeros_like(precip, dtype=np.float32)
    for t in range(n_days):
        p7[..., t] = np.nansum(precip[..., max(0, t - 6):t + 1], axis=-1)
        p30[..., t] = np.nansum(precip[..., max(0, t - 29):t + 1], axis=-1)
    return {"vpd": vpd, "days_since_rain": days_since, "precip_7d": p7, "precip_30d": p30}


def build_forecast_table(cfg: dict, anchors: pd.DataFrame, weather: np.ndarray) -> pd.DataFrame:
    raw_names = list(cfg["weather"]["variables"])
    pad = int(cfg["grid"]["weather_pad_days"])
    hist = int(cfg["grid"]["history_days"])
    horizon = int(cfg["grid"]["horizon_days"])
    off0 = pad + hist - 1  # índice del día t0 en weather (-43..7)
    der = derived_weather(weather)
    rows = []
    for lead in range(1, horizon + 1):
        idx = off0 + lead
        row = {
            "anchor_idx": anchors["anchor_idx"].to_numpy(),
            "hotspot_pk": anchors["hotspot_pk"].to_numpy(),
            "hotspot_id": anchors["hotspot_id"].to_numpy(),
            "t0": anchors["t0"].to_numpy(),
            "lead": lead,
            "date": (anchors["t0"] + pd.Timedelta(days=lead)).to_numpy(),
        }
        for k, name in enumerate(raw_names):
            row[name] = weather[:, idx, k]
        for name, arr in der.items():
            row[name] = arr[:, idx]
        rows.append(pd.DataFrame(row))
    return pd.concat(rows, ignore_index=True)


def compute_stats(cfg: dict, anchors: pd.DataFrame, weather: np.ndarray) -> dict:
    train = anchors["split"].to_numpy() == "train"
    names = list(cfg["weather"]["variables"])
    w = weather[train]
    stats = {}
    for k, name in enumerate(names):
        vals = w[:, :, k]
        stats[name] = {
            "mean": float(np.nanmean(vals)),
            "std": float(np.nanstd(vals)),
            "min": float(np.nanmin(vals)),
            "max": float(np.nanmax(vals)),
        }
    der = derived_weather(w)
    for name, arr in der.items():
        stats[name] = {
            "mean": float(np.nanmean(arr)),
            "std": float(np.nanstd(arr)),
            "min": float(np.nanmin(arr)),
            "max": float(np.nanmax(arr)),
        }
    return stats


def main() -> int:
    args = parse_args("Muestras de hotspots y clima")
    cfg = load_config(args.config)
    data_dir = ensure_dir(cfg["paths"]["data"])
    out_dir = ensure_dir(cfg["paths"]["hotspots"])
    log = setup_logging("02_build_hotspots", data_dir / "logs" / "02_build_hotspots.log",
                        cfg["run"]["log_level"])
    log.info("Config: %s", cfg["_config_path"])

    grid = load_grid(cfg)
    hs = load_cordoba_hotspots(cfg, grid)
    log.info("Hotspots Córdoba en la ventana configurada: %d", len(hs))

    anchors = build_anchors(cfg, grid, hs)
    if args.smoke:
        anchors = anchors.head(400).copy()
        anchors["anchor_idx"] = np.arange(len(anchors), dtype=np.int64)
    log.info("Anclas: %d train / %d val / %d test",
             int((anchors["split"] == "train").sum()),
             int((anchors["split"] == "val").sum()),
             int((anchors["split"] == "test").sum()))

    long = build_long(cfg, grid, hs, anchors, log)
    write_parquet_atomic(long, out_dir / "hotspots_long.parquet")

    cells, cell_lat, cell_lon = parse_power_cells(cfg)
    power = load_power_arrays(cfg, cells)
    cell_idx, (p_lat, p_lon) = assign_power_cells(cfg, grid, anchors, cells)
    weather = build_weather(cfg, anchors, cell_idx, cells, power)
    np.save(out_dir / "weather.npy", weather)
    log.info("Weather: %s (NaN=%.2f%%)", weather.shape,
             100.0 * np.isnan(weather).mean())

    forecast = build_forecast_table(cfg, anchors, weather)
    write_parquet_atomic(forecast, out_dir / "hotspot_forecast_7d.parquet")

    stats = compute_stats(cfg, anchors, weather)
    write_json(out_dir / "stats.json", stats)

    index = anchors[[
        "anchor_idx", "hotspot_pk", "hotspot_id", "split", "t0",
        "row", "col", "center_lon", "center_lat", "cell_id",
        "frp", "confidence_incendio", "sensor", "satellite", "daynight",
        "scan_km", "track_km", "bright_main", "bright_aux",
        "doy", "hora_local",
    ]].copy()
    index["power_cell_lat"] = p_lat
    index["power_cell_lon"] = p_lon
    write_parquet_atomic(index, out_dir / "index.parquet")

    meta = {
        "n_samples": int(len(anchors)),
        "n_train": int((anchors["split"] == "train").sum()),
        "n_val": int((anchors["split"] == "val").sum()),
        "n_test": int((anchors["split"] == "test").sum()),
        "grid": grid,
        "patch_cells": int(cfg["grid"]["patch_cells"]),
        "history_days": int(cfg["grid"]["history_days"]),
        "horizon_days": int(cfg["grid"]["horizon_days"]),
        "weather_variables": list(cfg["weather"]["variables"]),
        "weather_day_offsets": list(range(-(int(cfg["grid"]["weather_pad_days"]) +
                                          int(cfg["grid"]["history_days"]) - 1),
                                         int(cfg["grid"]["horizon_days"]) + 1)),
        "dedup_cell_day": bool(cfg["dataset"].get("dedup_cell_day", False)),
    }
    write_json(out_dir / "meta.json", meta)
    write_json(out_dir / "power_cells.json",
               {"cells": [{"lat": c[0], "lon": c[1]} for c in cells]})
    log.info("Escrito en %s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
