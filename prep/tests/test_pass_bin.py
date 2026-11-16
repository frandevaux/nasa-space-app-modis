from __future__ import annotations

import pandas as pd

from conftest import load_step


def _frame(rows):
    return pd.DataFrame(rows, columns=["ts_local", "ts_utc"])


def test_pass_bin_boundaries(ctx):
    step = load_step("03_conf_class.py")
    df = _frame([
        ("2025-01-01 06:59", "2025-01-01 09:59"),
        ("2025-01-01 07:00", "2025-01-01 10:00"),
        ("2025-01-01 18:59", "2025-01-01 21:59"),
        ("2025-01-01 19:00", "2025-01-01 22:00"),
        ("2025-01-02 02:59", "2025-01-02 05:59"),
        ("2025-01-02 07:00", "2025-01-02 10:00"),
    ])
    df["ts_local"] = pd.to_datetime(df["ts_local"])
    df["ts_utc"] = pd.to_datetime(df["ts_utc"])
    out = step.add_pass_bin(df, ctx.cfg, ctx)
    assert out["pass_bin"].tolist() == [
        "2024-12-31_N",
        "2025-01-01_D",
        "2025-01-01_D",
        "2025-01-01_N",
        "2025-01-01_N",
        "2025-01-02_D",
    ]
    night = out.iloc[3]
    assert night["bin_start_utc"] == pd.Timestamp("2025-01-01 22:00")
    assert night["bin_end_utc"] == pd.Timestamp("2025-01-02 10:00")
    assert ((out["ts_utc"] >= out["bin_start_utc"]) &
            (out["ts_utc"] < out["bin_end_utc"])).all()
