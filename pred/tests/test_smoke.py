"""Tests chicos del pipeline de predicción (no requieren datos pesados)."""

from __future__ import annotations

import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np
import pandas as pd
import torch

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common import grid_from_bounds, grid_rowcol_from_xy  # noqa: E402

model_mod = SourceFileLoader("hotspot_model", str(SRC / "05_model.py")).load_module()
classic_mod = SourceFileLoader("classic_mod", str(SRC / "08_classic_fires_events.py")).load_module()


def test_grid_roundtrip():
    grid = grid_from_bounds((0.0, 0.0, 3000.0, 2000.0), 1000.0)
    assert grid["width"] == 3 and grid["height"] == 2
    row, col = grid_rowcol_from_xy(np.array([1500.0]), np.array([1500.0]), grid)
    assert int(row[0]) == 0 and int(col[0]) == 1


def test_model_forward_shape():
    model = model_mod.HotspotCNN()
    x_hist = torch.randn(2, 14, 20, 32, 32)
    x_fut = torch.randn(2, 7, 7, 32, 32)
    x_static = torch.randn(2, 12, 32, 32)
    v = torch.randn(2, 17)
    with torch.no_grad():
        out = model(x_hist, x_fut, x_static, v)
    assert tuple(out.shape) == (2, 7, 32, 32)
    assert torch.isfinite(out).all()


def test_classic_fires_grouping(tmp_path):
    cfg = {"classic": {"event_link_window_days": 5, "event_buffer_km": 1.0}}
    hs = pd.DataFrame({
        "lat": [-31.4000, -31.4005, -31.5000],
        "lon": [-64.2000, -64.2005, -64.2000],
        "date": ["2026-11-14", "2026-11-14", "2026-11-14"],
        "prob": [0.9, 0.8, 0.7],
    })
    fires = classic_mod.derive_fires(hs, cfg)
    # Los dos primeros están a ~70 m; el tercero está a ~11 km.
    assert len(fires) == 2


def test_classic_events_link_days():
    cfg = {"classic": {"event_link_window_days": 5, "event_buffer_km": 1.0}}
    fires = pd.DataFrame({
        "incendio_id": ["A", "B"],
        "day": pd.to_datetime(["2026-11-14", "2026-11-16"]),
        "t_inicio": pd.to_datetime(["2026-11-14 12:00", "2026-11-16 12:00"]),
        "t_fin": pd.to_datetime(["2026-11-14 12:00", "2026-11-16 12:00"]),
        "area_pixeles_km2": [1.0, 1.0],
        "confidence": [80.0, 80.0],
        "centroid_lon": [-64.20, -64.201],
        "centroid_lat": [-31.40, -31.401],
    })
    events = classic_mod.derive_events(fires, cfg)
    assert len(events) == 1
    assert int(events.iloc[0]["n_incendios"]) == 2
