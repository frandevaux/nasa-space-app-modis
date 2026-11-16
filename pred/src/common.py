"""Utilidades comunes de la etapa de predicción de hotspots.

Todas las rutas del config son relativas a `pred/`. Este módulo no conoce
incendios ni eventos: solo hotspots, grilla, clima y estáticos.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from pyproj import Transformer

PRED_ROOT = Path(__file__).resolve().parents[1]


def parse_args(description: str = "") -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--config", default="config/params.yaml")
    ap.add_argument("--smoke", action="store_true", help="corrida reducida para probar")
    ap.add_argument("--force", action="store_true", help="recalcular salidas existentes")
    ap.add_argument("--epochs", type=int, default=None, help="override de épocas")
    ap.add_argument("--split", default="val", choices=["val", "test"],
                    help="split a evaluar")
    return ap.parse_args()


def load_config(path: str | Path) -> dict[str, Any]:
    """Carga el YAML y resuelve las rutas a absolutas."""
    p = Path(path)
    if not p.is_absolute():
        p = PRED_ROOT / p
    with p.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    def _resolve(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: _resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve(v) for v in value]
        if isinstance(value, str) and (
            value.startswith("./")
            or value.startswith("../")
            or value.startswith("data/")
            or value.startswith("config/")
        ):
            return str((PRED_ROOT / value).resolve())
        return value

    cfg = _resolve(cfg)
    cfg["_root"] = str(PRED_ROOT)
    cfg["_config_path"] = str(p)
    return cfg


def setup_logging(name: str, log_path: str | Path | None = None,
                  level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    if log_path is not None:
        lp = Path(log_path)
        lp.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(lp, mode="a", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, p)


def read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_parquet_atomic(df: pd.DataFrame, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, p)
    return p


def seed_everything(seed: int) -> None:
    import random
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Proyección y grilla
# ---------------------------------------------------------------------------

def make_transformers(crs_grid: str) -> tuple[Transformer, Transformer]:
    """(lon/lat -> grid, grid -> lon/lat)."""
    fwd = Transformer.from_crs("EPSG:4326", crs_grid, always_xy=True)
    inv = Transformer.from_crs(crs_grid, "EPSG:4326", always_xy=True)
    return fwd, inv


def grid_from_bounds(bounds: tuple[float, float, float, float],
                     cell_size_m: float) -> dict:
    """Grilla alineada a múltiplos de cell_size_m.

    bounds = (xmin, ymin, xmax, ymax) en la CRS de la grilla.
    """
    xmin, ymin, xmax, ymax = bounds
    x0 = np.floor(xmin / cell_size_m) * cell_size_m
    y0 = np.floor(ymin / cell_size_m) * cell_size_m
    x1 = np.ceil(xmax / cell_size_m) * cell_size_m
    y1 = np.ceil(ymax / cell_size_m) * cell_size_m
    width = int(round((x1 - x0) / cell_size_m))
    height = int(round((y1 - y0) / cell_size_m))
    return {
        "x0": float(x0),
        "y0": float(y0),
        "x1": float(x1),
        "y1": float(y1),
        "width": width,
        "height": height,
        "cell_size_m": float(cell_size_m),
        "crs": None,
    }


def grid_rowcol_from_xy(x: np.ndarray, y: np.ndarray, grid: dict) -> tuple[np.ndarray, np.ndarray]:
    """Fila/columna (0-based) para coordenadas de la CRS de la grilla.

    La fila 0 es la de arriba (y = y1).
    """
    col = np.floor((np.asarray(x) - grid["x0"]) / grid["cell_size_m"]).astype(np.int64)
    row = np.floor((grid["y1"] - np.asarray(y)) / grid["cell_size_m"]).astype(np.int64)
    return row, col


def grid_xy_from_rowcol(row: np.ndarray, col: np.ndarray, grid: dict) -> tuple[np.ndarray, np.ndarray]:
    """Centro de la celda en la CRS de la grilla."""
    x = grid["x0"] + (np.asarray(col) + 0.5) * grid["cell_size_m"]
    y = grid["y1"] - (np.asarray(row) + 0.5) * grid["cell_size_m"]
    return x, y


def grid_lonlat_from_rowcol(row: np.ndarray, col: np.ndarray,
                            grid: dict, inv: Transformer) -> tuple[np.ndarray, np.ndarray]:
    x, y = grid_xy_from_rowcol(row, col, grid)
    lon, lat = inv.transform(x, y)
    return np.asarray(lon), np.asarray(lat)


def in_grid(row: np.ndarray, col: np.ndarray, grid: dict) -> np.ndarray:
    return ((row >= 0) & (row < grid["height"]) &
            (col >= 0) & (col < grid["width"]))


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

def local_date(ts_utc: pd.Series, offset_hours: int = -3) -> pd.Series:
    """Fecha local (UTC-3), tz-naive, a partir de timestamps UTC."""
    return ((pd.to_datetime(ts_utc, utc=True) + pd.Timedelta(hours=offset_hours))
            .dt.floor("D").dt.tz_localize(None))


def date_to_day_index(dates: pd.Series, origin: str | pd.Timestamp) -> np.ndarray:
    o = pd.Timestamp(origin)
    return (pd.to_datetime(dates).dt.floor("D") - o).dt.days.to_numpy()


# ---------------------------------------------------------------------------
# Máscaras y rasters
# ---------------------------------------------------------------------------

def pad_crop(arr: np.ndarray, row: int, col: int, size: int) -> np.ndarray:
    """Extrae una ventana size x size centrada en (row,col), con padding de ceros."""
    half = size // 2
    r0, r1 = row - half, row + half
    c0, c1 = col - half, col + half
    h, w = arr.shape[:2]
    out = np.zeros((size, size) + arr.shape[2:], dtype=arr.dtype)
    rr0, rr1 = max(r0, 0), min(r1, h)
    cc0, cc1 = max(c0, 0), min(c1, w)
    if rr1 <= rr0 or cc1 <= cc0:
        return out
    out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = arr[rr0:rr1, cc0:cc1]
    return out


def crop_pad(arr: np.ndarray, row: int, col: int, size: int,
             fill: float = 0.0) -> np.ndarray:
    """Como pad_crop pero con un valor de relleno configurable."""
    half = size // 2
    r0, r1 = row - half, row + half
    c0, c1 = col - half, col + half
    h, w = arr.shape[:2]
    out = np.full((size, size) + arr.shape[2:], fill, dtype=arr.dtype)
    rr0, rr1 = max(r0, 0), min(r1, h)
    cc0, cc1 = max(c0, 0), min(c1, w)
    if rr1 <= rr0 or cc1 <= cc0:
        return out
    out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = arr[rr0:rr1, cc0:cc1]
    return out
