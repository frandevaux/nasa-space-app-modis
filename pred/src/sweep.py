"""Barrido de umbral/presupuesto para la derivación clásica de incendios/eventos.

Usa `predicted_hotspots_val_all.parquet` (top-k por ancla, sin filtrar) y
evalúa combinaciones de probabilidad mínima y máximo de hotspots por día.
"""

from __future__ import annotations

import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config, parse_args, read_json, setup_logging, write_json  # noqa: E402

classic = SourceFileLoader("classic_mod", str(Path(__file__).resolve().parent /
                                              "08_classic_fires_events.py")).load_module()


def load_real(cfg, split: str = "val"):
    prep = Path(cfg["paths"]["prep_processed"])
    start = pd.Timestamp(cfg["periods"][f"{split}_start"])
    end = pd.Timestamp(cfg["periods"][f"{split}_end"]) + pd.Timedelta(days=1)
    rf = pd.read_parquet(prep / "incendios.parquet",
                         columns=["incendio_id", "t_inicio", "centroid_lon", "centroid_lat"])
    rf = rf[(rf["t_inicio"] >= start) & (rf["t_inicio"] < end)]
    rf = rf[rf["centroid_lon"].between(-66.0, -61.5) &
            rf["centroid_lat"].between(-35.2, -29.3)]
    re = pd.read_parquet(prep / "eventos.parquet",
                         columns=["evento_id", "inicio", "centroid_lon", "centroid_lat"])
    re = re[(re["inicio"] >= start) & (re["inicio"] < end)]
    re = re[re["centroid_lon"].between(-66.0, -61.5) &
            re["centroid_lat"].between(-35.2, -29.3)]
    return rf, re


def main() -> int:
    args = parse_args("Barrido umbral/presupuesto")
    cfg = load_config(args.config)
    rep = Path(cfg["paths"]["reports"])
    split = args.split
    hs = pd.read_parquet(rep / f"predicted_hotspots_{split}_all.parquet")
    rf, re = load_real(cfg, split)
    thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    budgets = [50, 100, 200, 300, 500, 1000]
    rows = []
    for th in thresholds:
        base = hs[hs["prob"] >= th].copy()
        if len(base) == 0:
            continue
        for budget in budgets:
            sub = (base.sort_values(["date", "prob"], ascending=[True, False])
                   .groupby("date", sort=False).head(budget))
            fires = classic.derive_fires(sub, cfg)
            events = classic.derive_events(fires, cfg)
            mf = classic._match(fires, rf, 1.0, 1, "day", "t_inicio")
            me = classic._match(events, re, 2.0, 1, "inicio", "inicio")
            rows.append({
                "threshold": th, "max_per_day": budget,
                "n_hotspots": int(len(sub)), "n_fires": int(len(fires)),
                "n_events": int(len(events)),
                "fire_precision": mf["precision"], "fire_recall": mf["recall"],
                "fire_f1": mf["f1"], "fire_missed": mf["missed_rate"],
                "event_precision": me["precision"], "event_recall": me["recall"],
                "event_f1": me["f1"], "event_missed": me["missed_rate"],
            })
            print(f"th={th} budget={budget} hs={len(sub)} fires={len(fires)} "
                  f"events={len(events)} fire_f1={mf['f1']:.3f} event_f1={me['f1']:.3f} "
                  f"event_recall={me['recall']:.3f}", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(rep / "sweep.csv", index=False)
    write_json(rep / "sweep.json", out.to_dict(orient="records"))
    if len(out):
        best = out.sort_values(["event_f1", "event_recall"], ascending=False).iloc[0]
        print("MEJOR event_f1:", best.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
