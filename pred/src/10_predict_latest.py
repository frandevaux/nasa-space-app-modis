"""Predicción operativa con los últimos hotspots disponibles y pronóstico real.

- Anclas: hotspots de Córdoba del último día con datos (por defecto, el máximo).
- Historia: 14 días de hotspots + POWER observado.
- Futuro: 7 días de pronóstico Open-Meteo (si falta una variable/día, se
  rellena con la última observación POWER y se registra).
- Salida: hotspots, incendios y eventos clásicos + GeoJSON/Parquet.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from pyproj import Transformer
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ensure_dir, grid_lonlat_from_rowcol, grid_rowcol_from_xy,
                    load_config, read_json, setup_logging, write_json)  # noqa: E402
from forecast_adapter import OpenMeteoForecastProvider  # noqa: E402

SRC = Path(__file__).resolve().parent
ds_mod = SourceFileLoader("hotspot_dataset", str(SRC / "04_dataset.py")).load_module()
model_mod = SourceFileLoader("hotspot_model", str(SRC / "05_model.py")).load_module()
classic_mod = SourceFileLoader("classic_mod", str(SRC / "08_classic_fires_events.py")).load_module()


def load_cordoba_hotspots(cfg, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    grid = read_json(Path(cfg["paths"]["static"]) / "grid.json")
    mask = np.load(Path(cfg["paths"]["static"]) / "cordoba_mask.npy")
    cols = ["hotspot_pk", "hotspot_id", "latitude", "longitude", "ts_utc",
            "frp", "confidence_incendio", "sensor", "satellite", "daynight",
            "scan_km", "track_km", "bright_main", "bright_aux"]
    hs = pd.read_parquet(Path(cfg["paths"]["prep_processed"]) / "hotspots.parquet",
                         columns=cols)
    hs["ts_utc"] = pd.to_datetime(hs["ts_utc"], utc=True)
    lo = (start - pd.Timedelta(days=2)).tz_localize("UTC")
    hi = (end + pd.Timedelta(days=2)).tz_localize("UTC")
    hs = hs[(hs["ts_utc"] >= lo) & (hs["ts_utc"] < hi)].copy()
    fwd = Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
    x, y = fwd.transform(hs["longitude"].to_numpy(), hs["latitude"].to_numpy())
    r, c = grid_rowcol_from_xy(x, y, grid)
    ok = (r >= 0) & (r < grid["height"]) & (c >= 0) & (c < grid["width"])
    ok &= mask[np.clip(r, 0, grid["height"] - 1), np.clip(c, 0, grid["width"] - 1)].astype(bool)
    hs = hs.loc[ok].copy()
    hs["row"] = r[ok]; hs["col"] = c[ok]
    hs["x"] = x[ok]; hs["y"] = y[ok]
    hs["cell_id"] = hs["row"].astype(np.int64) * grid["width"] + hs["col"].astype(np.int64)
    hs["t0"] = ((hs["ts_utc"] + pd.Timedelta(hours=int(cfg["time"]["timezone_offset_hours"])))
                .dt.floor("D").dt.tz_localize(None))
    hs["frp"] = hs["frp"].fillna(0.0).clip(lower=0.0)
    hs["confidence_incendio"] = hs["confidence_incendio"].fillna(0.0).clip(0, 100)
    hs["sensor_code"] = hs["sensor"].map({"MODIS": 0, "VIIRS": 1}).fillna(-1).astype(np.int8)
    hs["daynight_code"] = hs["daynight"].map({"D": 0, "N": 1}).fillna(-1).astype(np.int8)
    hs["doy"] = hs["t0"].dt.day_of_year.astype(np.int16)
    hs["hora_local"] = ((hs["ts_utc"] + pd.Timedelta(hours=int(cfg["time"]["timezone_offset_hours"])))
                        .dt.hour.astype(np.int8))
    return hs, grid


def power_cells(cfg) -> tuple[list[tuple[float, float]], cKDTree]:
    files = sorted(Path(cfg["paths"]["raw_power"]).glob("power_*.csv"))
    cells = []
    for f in files:
        stem = f.stem.replace("power_", "")
        la, lo = stem.split("_")
        cells.append((float(la), float(lo)))
    tree = cKDTree(np.c_[np.array([c[0] for c in cells]),
                         np.array([c[1] for c in cells])])
    return cells, tree


def load_power_cell(cfg, cell: tuple[float, float]) -> pd.DataFrame:
    f = Path(cfg["paths"]["raw_power"]) / f"power_{cell[0]}_{cell[1]}.csv"
    df = pd.read_csv(f, skiprows=14)
    df["date"] = pd.to_datetime(df["YEAR"].astype(str) + df["DOY"].astype(str).str.zfill(3),
                                format="%Y%j")
    df = df.rename(columns={"T2M": "t2m", "T2M_MAX": "t2m_max", "RH2M": "rh2m",
                            "PRECTOTCORR": "precip", "WS10M_MAX": "ws10m_max",
                            "GWETTOP": "soil_moisture"})
    for c in ["t2m", "t2m_max", "rh2m", "precip", "ws10m_max", "soil_moisture"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace(
            float(cfg["weather"]["missing_value"]), np.nan)
    return df.set_index("date")[["t2m", "t2m_max", "rh2m", "precip",
                                 "ws10m_max", "soil_moisture"]]


def build_weather(cfg, anchors: pd.DataFrame, t0: pd.Timestamp,
                  provider: OpenMeteoForecastProvider, log) -> np.ndarray:
    cells, tree = power_cells(cfg)
    pad = int(cfg["grid"]["weather_pad_days"])
    hist = int(cfg["grid"]["history_days"])
    horizon = int(cfg["grid"]["horizon_days"])
    ndays = pad + hist + horizon
    offs = np.arange(-pad - hist + 1, horizon + 1)  # -43..7
    out = np.full((len(anchors), ndays, 6), np.nan, dtype=np.float32)
    cache: dict[tuple[int, int], pd.DataFrame] = {}
    fc_cache: dict[tuple[float, float], pd.DataFrame] = {}
    for i, r in enumerate(anchors.itertuples(index=False)):
        _, ci = tree.query((r.center_lat, r.center_lon), k=1)
        cell = cells[int(ci)]
        if (cell) not in cache:
            cache[cell] = load_power_cell(cfg, cell)
        p = cache[cell]
        raw = p.reindex(pd.date_range(t0 - pd.Timedelta(days=pad + hist - 1),
                                      t0 + pd.Timedelta(days=horizon), freq="D"))
        vals = raw.to_numpy(dtype=np.float32)
        vals = vals[:ndays]
        out[i, :len(vals)] = vals
        # Pronóstico real para los 7 días futuros.
        key = (round(float(r.center_lat), 2), round(float(r.center_lon), 2))
        if key not in fc_cache:
            try:
                fc_cache[key] = provider.get(r.center_lat, r.center_lon,
                                             t0, days=horizon)
            except Exception as exc:  # noqa: BLE001
                log.warning("Open-Meteo falló en %s: %s", key, exc)
                fc_cache[key] = pd.DataFrame()
        fc = fc_cache[key]
        if len(fc):
            for lead, row in fc.iterrows():
                date = pd.Timestamp(row["date"])
                j = int((date - (t0 - pd.Timedelta(days=pad + hist - 1))).days)
                if 0 <= j < ndays:
                    out[i, j] = [row["t2m"], row["t2m_max"], row["rh2m"],
                                 row["precip"], row["ws10m_max"], row["soil_moisture"]]
        # Relleno de faltantes con la última observación / media de la ventana.
        for j in range(ndays):
            if not np.isfinite(out[i, j]).all():
                prev = out[i, max(0, j - 1)]
                prev = np.where(np.isfinite(prev), prev, np.nan)
                fill = prev if np.isfinite(prev).all() else np.nanmean(out[i], axis=0)
                m = ~np.isfinite(out[i, j])
                out[i, j, m] = fill[m]
    return out


def build_inference_dir(cfg, inf_dir: Path, anchors: pd.DataFrame, hs: pd.DataFrame,
                        grid: dict, t0: pd.Timestamp, log):
    ensure_dir(inf_dir)
    half = int(cfg["grid"]["patch_cells"]) // 2
    hist = int(cfg["grid"]["history_days"])
    tree = cKDTree(np.c_[hs["x"], hs["y"]])
    anchors = anchors.sort_values(["row", "col", "hotspot_pk"]).reset_index(drop=True)
    anchors["anchor_idx"] = np.arange(len(anchors), dtype=np.int64)
    inv = Transformer.from_crs(grid["crs"], "EPSG:4326", always_xy=True)
    lon, lat = inv.transform(anchors["x"], anchors["y"])
    anchors["center_lon"] = lon; anchors["center_lat"] = lat
    rows = []
    for i, r in enumerate(anchors.itertuples(index=False)):
        idx = tree.query_ball_point((r.x, r.y), half * 1000 * np.sqrt(2) + 1500)
        if not idx:
            continue
        idx = np.asarray(idx, dtype=np.int64)
        dx = hs["col"].to_numpy()[idx] - int(r.col)
        dy = hs["row"].to_numpy()[idx] - int(r.row)
        off = (hs["t0"].to_numpy("datetime64[D]")[idx] -
               np.datetime64(t0, "D")).astype("timedelta64[D]").astype(int)
        m = (dx >= -half) & (dx <= half - 1) & (dy >= -half) & (dy <= half - 1)
        m &= (off >= -hist) & (off <= 0)
        j = idx[m]
        if not len(j):
            continue
        rows.append(pd.DataFrame({
            "anchor_idx": np.full(len(j), int(r.anchor_idx)),
            "hotspot_pk": hs["hotspot_pk"].to_numpy()[j],
            "day_offset": off[m].astype(np.int8),
            "dx": dx[m].astype(np.int16), "dy": dy[m].astype(np.int16),
            "frp": hs["frp"].to_numpy()[j].astype(np.float32),
            "confidence": hs["confidence_incendio"].to_numpy()[j].astype(np.float32),
            "sensor_code": hs["sensor_code"].to_numpy()[j],
            "daynight_code": hs["daynight_code"].to_numpy()[j],
        }))
    long = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["anchor_idx", "hotspot_pk", "day_offset", "dx", "dy", "frp",
                 "confidence", "sensor_code", "daynight_code"])
    long = long.sort_values(["anchor_idx", "day_offset", "hotspot_pk"]).reset_index(drop=True)
    counts = long.groupby("anchor_idx", sort=False).size()
    starts = counts.cumsum().shift(fill_value=0).astype(np.int64)
    anchors["long_start"] = anchors["anchor_idx"].map(starts).fillna(0).astype(np.int64)
    anchors["long_count"] = anchors["anchor_idx"].map(counts).fillna(0).astype(np.int64)
    anchors["split"] = "inference"
    anchors["n_future_hotspots"] = 0
    anchors["n_future_cells"] = 0
    anchors["power_cell_lat"] = np.nan
    anchors["power_cell_lon"] = np.nan
    # Columnas esperadas por el Dataset.
    keep = ["anchor_idx", "hotspot_pk", "hotspot_id", "split", "t0", "row", "col",
            "center_lon", "center_lat", "cell_id", "frp", "confidence_incendio",
            "sensor", "satellite", "daynight", "scan_km", "track_km",
            "bright_main", "bright_aux", "doy", "hora_local", "long_start",
            "long_count", "n_future_hotspots", "n_future_cells",
            "power_cell_lat", "power_cell_lon"]
    anchors[keep].to_parquet(inf_dir / "index.parquet", index=False)
    long.to_parquet(inf_dir / "hotspots_long.parquet", index=False)

    provider = OpenMeteoForecastProvider(cfg)
    weather = build_weather(cfg, anchors, t0, provider, log)
    np.save(inf_dir / "weather.npy", weather)
    # Reutiliza stats/channels del entrenamiento.
    src = Path(cfg["paths"]["hotspots"])
    (inf_dir / "stats.json").write_text((src / "stats.json").read_text(), encoding="utf-8")
    (inf_dir / "channels.json").write_text((src / "channels.json").read_text(), encoding="utf-8")
    write_json(inf_dir / "meta.json", {
        "t0": str(t0.date()), "n_anchors": int(len(anchors)),
        "n_long": int(len(long)), "weather_shape": list(weather.shape),
        "forecast_provider": "open-meteo", "horizon_days": int(cfg["grid"]["horizon_days"]),
    })
    return anchors, inf_dir


def topk_from_probs(probs, mask, row0, col0, ds, t0, grid, inv, k=50):
    rows = []
    for lead in range(probs.shape[0]):
        p = probs[lead].copy(); p[mask < 0.5] = -1
        flat = p.reshape(-1)
        kk = min(k, len(flat)); kth = max(0, len(flat) - kk)
        top = np.argpartition(flat, kth)[-kk:]
        for fi in top:
            if flat[fi] <= 0.05:
                continue
            r, c = np.unravel_index(fi, p.shape)
            grow = row0 + int(r) - ds.half
            gcol = col0 + int(c) - ds.half
            if not (0 <= grow < grid["height"] and 0 <= gcol < grid["width"]):
                continue
            lon, lat = grid_lonlat_from_rowcol(np.array([grow]), np.array([gcol]), grid, inv)
            rows.append({"date": (t0 + pd.Timedelta(days=lead + 1)).date().isoformat(),
                         "lat": float(lat[0]), "lon": float(lon[0]),
                         "prob": float(flat[fi]), "lead": lead + 1,
                         "row": int(grow), "col": int(gcol)})
    return rows


def write_geojson(df: pd.DataFrame, path: Path):
    feats = []
    for _, r in df.iterrows():
        props = {k: (v.item() if hasattr(v, "item") else v)
                 for k, v in r.items() if k not in ("lat", "lon")}
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point",
                                   "coordinates": [float(r["lon"]), float(r["lat"])]},
                      "properties": props})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                               ensure_ascii=False, default=str), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/params.yaml")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD; default último día con datos")
    ap.add_argument("--lookback-days", type=int, default=1,
                    help="usar hotspots de los últimos N días como anclas")
    ap.add_argument("--max-anchors", type=int, default=300)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    cfg = load_config(args.config)
    log = setup_logging("10_predict_latest",
                        Path(cfg["paths"]["data"]) / "logs" / "10_predict_latest.log",
                        cfg["run"]["log_level"])
    hs_all, grid = load_cordoba_hotspots(cfg, pd.Timestamp("2026-10-01"),
                                         pd.Timestamp("2026-11-30"))
    t0 = pd.Timestamp(args.date) if args.date else hs_all["t0"].max()
    start = t0 - pd.Timedelta(days=max(args.lookback_days - 1, 0))
    anchors = hs_all[(hs_all["t0"] >= start) & (hs_all["t0"] <= t0)].copy()
    anchors = anchors.sort_values(["t0", "row", "col", "frp"],
                                  ascending=[True, True, True, False])
    anchors = anchors.drop_duplicates(["t0", "row", "col"], keep="first")
    if args.max_anchors and len(anchors) > args.max_anchors:
        anchors = anchors.head(args.max_anchors)
    anchors = anchors.reset_index(drop=True)
    log.info("T0=%s; anclas=%d (lookback=%d)", t0.date(), len(anchors), args.lookback_days)
    if len(anchors) == 0:
        log.error("No hay hotspots ancla en el período")
        return 1

    inf_dir = ensure_dir(Path(cfg["paths"]["data"]) / "inference" / f"latest_{t0.date()}")
    build_inference_dir(cfg, inf_dir, anchors, hs_all, grid, t0, log)
    cfg_inf = load_config(args.config)
    cfg_inf["paths"]["hotspots"] = str(inf_dir)
    ds = ds_mod.FireHotspotDataset(cfg_inf, "inference")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ckpt = torch.load(Path(cfg["paths"]["models"]) / "best.pt", map_location=device)
    model = model_mod.HotspotCNN(dropout=float(cfg["model"]["dropout"])).to(device)
    model.load_state_dict(ckpt["model"]); model.eval()
    inv = Transformer.from_crs(grid["crs"], "EPSG:4326", always_xy=True)
    rows = []
    from torch.utils.data import DataLoader
    dl = DataLoader(ds, batch_size=32, shuffle=False)
    with torch.no_grad():
        for b in dl:
            tensors = {k: v.to(device) for k, v in b.items()
                       if torch.is_tensor(v) and k not in ("anchor_idx",)}
            probs = torch.sigmoid(model(tensors["x_hist"], tensors["x_fut"],
                                        tensors["x_static"], tensors["v"])).cpu().numpy()
            for bi in range(probs.shape[0]):
                r = ds.index.iloc[bi]
                rows.extend(topk_from_probs(probs[bi], b["mask"][bi].numpy(),
                                            int(r["row"]), int(r["col"]), ds,
                                            pd.Timestamp(r["t0"]), grid, inv,
                                            k=int(max(cfg["eval"]["top_k_per_anchor"]))))
    hs = pd.DataFrame(rows)
    if len(hs):
        min_prob = float(cfg["classic"]["min_prob"])
        max_day = int(cfg["classic"]["max_hotspots_per_day"])
        hs = hs[hs["prob"] >= min_prob]
        hs = (hs.sort_values(["date", "prob"], ascending=[True, False])
              .groupby("date", sort=False).head(max_day)
              .sort_values(["date", "row", "col"]).reset_index(drop=True))
    out_dir = ensure_dir(Path(args.out) if args.out else
                         Path(cfg["paths"]["reports"]) / "latest_prediction")
    hs.to_parquet(out_dir / "predicted_hotspots.parquet", index=False)
    write_geojson(hs, out_dir / "predicted_hotspots.geojson")
    fires = classic_mod.derive_fires(hs, cfg, log) if len(hs) else pd.DataFrame()
    events = classic_mod.derive_events(fires, cfg, log) if len(fires) else pd.DataFrame()
    if len(fires):
        fires.to_parquet(out_dir / "predicted_fires.parquet", index=False)
    if len(events):
        events.to_parquet(out_dir / "predicted_events.parquet", index=False)
    summary = {
        "t0": str(t0.date()),
        "dates": sorted(hs["date"].unique().tolist()) if len(hs) else [],
        "n_anchors": int(len(anchors)),
        "n_hotspots": int(len(hs)),
        "n_fires": int(len(fires)),
        "n_events": int(len(events)),
        "forecast": "open-meteo + POWER history",
        "threshold": float(cfg["classic"]["min_prob"]),
        "max_per_day": int(cfg["classic"]["max_hotspots_per_day"]),
        "model_epoch": ckpt.get("epoch"),
    }
    write_json(out_dir / "summary.json", summary)
    log.info("Predicción: %s", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
