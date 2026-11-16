"""Etapa 03 — índice de acceso, offsets y metadatos de canales.

Agrega `long_start`/`long_count` al índice para que el Dataset lea los
hotspots de cada ancla sin escanear toda la tabla, y calcula estadísticas
de desbalance. No materializa tensores densos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ensure_dir, load_config, parse_args, read_json,  # noqa: E402
                    setup_logging, write_json, write_parquet_atomic)

HIST_CHANNELS = [
    "hs_count", "hs_presence", "hs_density_s1", "hs_density_s2",
    "frp_sum_log", "frp_max_log", "conf_mean", "conf_max",
    "known_mask", "sensor_modis", "daynight_N",
    "t2m_max", "rh2m", "precip", "ws10m_max", "gwettop",
    "vpd", "days_since_rain", "precip_7d", "precip_30d",
]
FUTURE_CHANNELS = [
    "t2m_max", "rh2m", "precip", "ws10m_max", "gwettop",
    "vpd", "days_since_rain",
]
STATIC_CHANNELS = [
    "cordoba_mask", "dept_norm",
    "landcover_forest", "landcover_shrub", "landcover_grass",
    "landcover_crop", "landcover_other",
    "ap", "fire_climatology", "dist_center", "dist_known_hs", "days_since_hs",
]


def main() -> int:
    args = parse_args("Índice de parches y estadísticas")
    cfg = load_config(args.config)
    data_dir = ensure_dir(cfg["paths"]["data"])
    out_dir = ensure_dir(cfg["paths"]["hotspots"])
    log = setup_logging("03_build_patches", data_dir / "logs" / "03_build_patches.log",
                        cfg["run"]["log_level"])
    log.info("Config: %s", cfg["_config_path"])

    index = pd.read_parquet(out_dir / "index.parquet")
    long = pd.read_parquet(out_dir / "hotspots_long.parquet")
    if args.smoke:
        keep = set(index["anchor_idx"].head(400).tolist())
        index = index[index["anchor_idx"].isin(keep)].copy()
        long = long[long["anchor_idx"].isin(keep)].copy()
        log.info("Smoke: %d anclas, %d filas long", len(index), len(long))

    long = long.sort_values(["anchor_idx", "day_offset", "hotspot_pk"],
                            kind="stable").reset_index(drop=True)
    counts = long.groupby("anchor_idx", sort=False).size()
    starts = counts.cumsum().shift(fill_value=0).astype(np.int64)
    index = index.sort_values("anchor_idx").reset_index(drop=True)
    index["long_start"] = index["anchor_idx"].map(starts).fillna(0).astype(np.int64)
    index["long_count"] = index["anchor_idx"].map(counts).fillna(0).astype(np.int64)

    horizon = int(cfg["grid"]["horizon_days"])
    future = long[(long["day_offset"] >= 1) & (long["day_offset"] <= horizon)]
    n_future_hs = future.groupby("anchor_idx").size()
    n_future_cells = (future.drop_duplicates(["anchor_idx", "dx", "dy"])
                      .groupby("anchor_idx").size())
    index["n_future_hotspots"] = index["anchor_idx"].map(n_future_hs).fillna(0).astype(np.int32)
    index["n_future_cells"] = index["anchor_idx"].map(n_future_cells).fillna(0).astype(np.int32)

    patch = int(cfg["grid"]["patch_cells"])
    pos_rate = float(index["n_future_cells"].sum()) / max(len(index) * patch * patch * horizon, 1)
    log.info("Positivos: %.4f%% de celdas-día; %.1f%% de anclas con algún hotspot futuro",
             100.0 * pos_rate,
             100.0 * (index["n_future_cells"] > 0).mean())

    # Extender stats con escalas de canales de fuego y desbalance.
    stats = read_json(out_dir / "stats.json")
    stats["fire"] = {
        "count_clip": 10.0,
        "frp_log_scale": 5.0,
        "conf_scale": 100.0,
        "density_scale": 10.0,
    }
    stats["dataset"] = {
        "n_samples": int(len(index)),
        "n_train": int((index["split"] == "train").sum()),
        "n_val": int((index["split"] == "val").sum()),
        "n_test": int((index["split"] == "test").sum()),
        "pos_rate": pos_rate,
        "patch_cells": patch,
        "horizon_days": horizon,
        "n_future_hotspots_mean": float(index["n_future_hotspots"].mean()),
        "n_future_cells_mean": float(index["n_future_cells"].mean()),
        "anchors_with_future_pct": float((index["n_future_cells"] > 0).mean()),
    }
    write_json(out_dir / "stats.json", stats)

    channels = {
        "hist": HIST_CHANNELS,
        "future": FUTURE_CHANNELS,
        "static": STATIC_CHANNELS,
        "n_hist": len(HIST_CHANNELS),
        "n_future": len(FUTURE_CHANNELS),
        "n_static": len(STATIC_CHANNELS),
    }
    write_json(out_dir / "channels.json", channels)
    write_parquet_atomic(index, out_dir / "index.parquet")

    log.info("Índice actualizado: %s", index[["anchor_idx", "long_start", "long_count",
                                               "n_future_hotspots", "n_future_cells"]].head().to_string(index=False))
    log.info("Escrito en %s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
