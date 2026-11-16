from __future__ import annotations

import pandas as pd

from conftest import load_step


def _known(ts):
    return pd.DataFrame({
        "latitude": [-34.0], "longitude": [-58.0],
        "scan_km": [1.0], "track_km": [1.0],
        "ts_utc": [pd.Timestamp(ts)], "type": [2],
    })


def _nrt(ts, lon=-58.0):
    return pd.DataFrame({
        "latitude": [-34.0], "longitude": [lon],
        "scan_km": [1.0], "track_km": [1.0],
        "ts_utc": [pd.Timestamp(ts)], "type": [None],
    })


def test_infer_nrt_discards_touching_static_source(ctx):
    step = load_step("02_clean.py")
    ctx.gpu = None
    keep, dropped, stats = step.infer_nrt(ctx, _known("2025-01-01 12:00"),
                                          _nrt("2025-01-02 12:00"))
    assert len(dropped) == 1 and len(keep) == 0
    assert stats["discarded"] == 1


def test_infer_nrt_keeps_far_hotspot(ctx):
    step = load_step("02_clean.py")
    ctx.gpu = None
    keep, dropped, stats = step.infer_nrt(ctx, _known("2025-01-01 12:00"),
                                          _nrt("2025-01-02 12:00", lon=-60.0))
    assert len(keep) == 1 and len(dropped) == 0
    assert keep.iloc[0]["type_inferred"]


def test_infer_nrt_lookback_boundary(ctx):
    step = load_step("02_clean.py")
    ctx.gpu = None
    # 364 días: dentro de la ventana -> descarta.
    keep, dropped, _ = step.infer_nrt(ctx, _known("2024-01-03 12:00"),
                                      _nrt("2025-01-02 12:00"))
    assert len(dropped) == 1
    # 366 días: fuera de la ventana -> conserva.
    keep, dropped, _ = step.infer_nrt(ctx, _known("2024-01-01 12:00"),
                                      _nrt("2025-01-02 12:00"))
    assert len(keep) == 1
