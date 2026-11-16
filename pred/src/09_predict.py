"""Etapa 09 — inferencia: hotspot(s) ancla -> hotspots, incendios y eventos.

Soporta hotspots existentes (`--hotspot-id`), puntos (`--point`) y CSV de
FIRMS (`--firms-csv`). Para puntos nuevos se usa el hotspot histórico más
cercano como ancla (documentado); el clima futuro puede venir de POWER
(fechas pasadas) u Open-Meteo (fechas futuras).
"""

from __future__ import annotations

import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ensure_dir, grid_lonlat_from_rowcol, load_config, parse_args,
                    read_json, setup_logging, write_json)  # noqa: E402
from forecast_adapter import get_provider  # noqa: E402

SRC = Path(__file__).resolve().parent
ds_mod = SourceFileLoader("hotspot_dataset", str(SRC / "04_dataset.py")).load_module()
model_mod = SourceFileLoader("hotspot_model", str(SRC / "05_model.py")).load_module()
classic_mod = SourceFileLoader("classic_mod", str(SRC / "08_classic_fires_events.py")).load_module()


def load_model(cfg, device):
    ckpt_path = Path(cfg["paths"]["models"]) / "best.pt"
    if not ckpt_path.exists():
        raise FileNotFoundError(ckpt_path)
    ckpt = torch.load(ckpt_path, map_location=device)
    model = model_mod.HotspotCNN(dropout=float(cfg["model"]["dropout"])).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model, ckpt


def find_sample(cfg, hotspot_id: str | None = None, lat: float | None = None,
                lon: float | None = None):
    idx = pd.read_parquet(Path(cfg["paths"]["hotspots"]) / "index.parquet")
    if hotspot_id is not None:
        hit = idx[idx["hotspot_id"].astype(str) == str(hotspot_id)]
        if len(hit) == 0:
            raise KeyError(f"hotspot_id {hotspot_id!r} no está en el índice")
        row = hit.iloc[0]
    else:
        d = (idx["center_lat"] - lat) ** 2 + ((idx["center_lon"] - lon) *
                                              np.cos(np.deg2rad(lat))) ** 2
        row = idx.loc[d.idxmin()]
    ds = ds_mod.FireHotspotDataset(cfg, str(row["split"]))
    pos = ds.index.index[ds.index["hotspot_pk"] == int(row["hotspot_pk"])]
    if len(pos) == 0:
        raise KeyError("Ancla no encontrada en el dataset")
    return ds, int(pos[0]), row


def predict_sample(model, ds, i, device, k: int = 20) -> pd.DataFrame:
    b = ds[i]
    tensors = {kk: vv.unsqueeze(0).to(device) for kk, vv in b.items()
               if torch.is_tensor(vv)}
    with torch.no_grad():
        logits = model(tensors["x_hist"], tensors["x_fut"], tensors["x_static"],
                       tensors["v"])
        probs = torch.sigmoid(logits)[0].cpu().numpy()
    mask = b["mask"].numpy()
    row = ds.index.iloc[i]
    row0, col0 = int(row["row"]), int(row["col"])
    t0 = pd.Timestamp(row["t0"])
    grid = read_json(Path(cfg_static_placeholder()) / "grid.json")
    return probs, mask, row0, col0, t0


def cfg_static_placeholder() -> str:
    # Se reemplaza en main; evita pasar cfg por argumentos en predict_sample.
    return _STATIC_DIR


_STATIC_DIR = "."


def topk_points(probs, mask, row0, col0, t0, ds, k=20) -> list[dict]:
    grid = read_json(Path(_STATIC_DIR) / "grid.json")
    from pyproj import Transformer
    inv = Transformer.from_crs(grid["crs"], "EPSG:4326", always_xy=True)
    rows = []
    for lead in range(probs.shape[0]):
        p = probs[lead].copy()
        p[mask < 0.5] = -1
        flat = p.reshape(-1)
        kk = min(k, len(flat))
        kth = max(0, len(flat) - kk)
        top = np.argpartition(flat, kth)[-kk:]
        for fi in top:
            if flat[fi] <= 0.05:
                continue
            r, c = np.unravel_index(fi, p.shape)
            grow = row0 + int(r) - ds.half
            gcol = col0 + int(c) - ds.half
            if not (0 <= grow < grid["height"] and 0 <= gcol < grid["width"]):
                continue
            lon, lat = grid_lonlat_from_rowcol(np.array([grow]), np.array([gcol]),
                                               grid, inv)
            rows.append({"date": (t0 + pd.Timedelta(days=lead + 1)).date().isoformat(),
                         "lat": float(lat[0]), "lon": float(lon[0]),
                         "prob": float(flat[fi]), "lead": lead + 1,
                         "row": int(grow), "col": int(gcol)})
    return rows


def write_geojson(df: pd.DataFrame, path: Path, lat="lat", lon="lon"):
    feats = []
    for _, r in df.iterrows():
        props = {k: (v.item() if hasattr(v, "item") else v)
                 for k, v in r.items() if k not in (lat, lon)}
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point",
                                   "coordinates": [float(r[lon]), float(r[lat])]},
                      "properties": props})
    import json
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                               ensure_ascii=False, default=str), encoding="utf-8")


def main() -> int:
    args = parse_args("Predicción de hotspots")
    cfg = load_config(args.config)
    global _STATIC_DIR
    _STATIC_DIR = cfg["paths"]["static"]
    data_dir = ensure_dir(cfg["paths"]["data"])
    rep = ensure_dir(cfg["paths"]["reports"])
    log = setup_logging("09_predict", data_dir / "logs" / "09_predict.log",
                        cfg["run"]["log_level"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, ckpt = load_model(cfg, device)
    log.info("Modelo %s época %s", ckpt.get("epoch"), ckpt.get("metric"))

    import argparse
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--hotspot-id")
    ap.add_argument("--point", help="LAT,LON")
    ap.add_argument("--date")
    ap.add_argument("--firms-csv")
    ap.add_argument("--out")
    known, _ = ap.parse_known_args()

    rows = []
    if known.firms_csv:
        firms = pd.read_csv(known.firms_csv)
        lat_col = "latitude" if "latitude" in firms else "lat"
        lon_col = "longitude" if "longitude" in firms else "lon"
        for _, r in firms.iterrows():
            ds, i, row = find_sample(cfg, lat=float(r[lat_col]), lon=float(r[lon_col]))
            probs, mask, row0, col0, t0 = predict_sample(model, ds, i, device)
            rows.extend(topk_points(probs, mask, row0, col0, t0, ds,
                                    k=int(max(cfg["eval"]["top_k_per_anchor"]))))
    elif known.point:
        lat, lon = [float(x) for x in known.point.split(",")]
        ds, i, row = find_sample(cfg, lat=lat, lon=lon)
        probs, mask, row0, col0, t0 = predict_sample(model, ds, i, device)
        rows.extend(topk_points(probs, mask, row0, col0, t0, ds,
                                k=int(max(cfg["eval"]["top_k_per_anchor"]))))
    else:
        ds, i, row = find_sample(cfg, hotspot_id=known.hotspot_id)
        probs, mask, row0, col0, t0 = predict_sample(model, ds, i, device)
        rows.extend(topk_points(probs, mask, row0, col0, t0, ds,
                                k=int(max(cfg["eval"]["top_k_per_anchor"]))))

    hs = pd.DataFrame(rows)
    out_dir = Path(known.out) if known.out else rep / "predict"
    ensure_dir(out_dir)
    if len(hs):
        hs = (hs.sort_values(["date", "row", "col", "prob"], ascending=[True, True, True, False])
              .drop_duplicates(["date", "row", "col"], keep="first").reset_index(drop=True))
    hs.to_parquet(out_dir / "predicted_hotspots.parquet", index=False)
    write_geojson(hs, out_dir / "predicted_hotspots.geojson")
    fires = classic_mod.derive_fires(hs, cfg, log) if len(hs) else pd.DataFrame()
    events = classic_mod.derive_events(fires, cfg, log) if len(fires) else pd.DataFrame()
    if len(fires):
        fires.to_parquet(out_dir / "predicted_fires.parquet", index=False)
    if len(events):
        events.to_parquet(out_dir / "predicted_events.parquet", index=False)
    summary = {
        "anchor": {"hotspot_id": known.hotspot_id, "point": known.point,
                   "firms_csv": known.firms_csv},
        "n_hotspots": int(len(hs)),
        "n_fires": int(len(fires)),
        "n_events": int(len(events)),
        "dates": sorted(hs["date"].unique().tolist()) if len(hs) else [],
        "model_epoch": ckpt.get("epoch"),
    }
    write_json(out_dir / "summary.json", summary)
    log.info("Predicción: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
