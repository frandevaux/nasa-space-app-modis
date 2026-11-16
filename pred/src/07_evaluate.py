"""Etapa 07 — evaluación de hotspots, derivación clásica y reporte."""

from __future__ import annotations

import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from pyproj import Transformer
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             precision_recall_fscore_support, roc_auc_score)
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ensure_dir, grid_lonlat_from_rowcol, load_config, parse_args,
                    read_json, setup_logging, write_json)  # noqa: E402

SRC = Path(__file__).resolve().parent
train_mod = SourceFileLoader("train_mod", str(SRC / "06_train.py")).load_module()
classic_mod = SourceFileLoader("classic_mod", str(SRC / "08_classic_fires_events.py")).load_module()


def array_metrics(y, p, mask):
    m = np.broadcast_to(mask[:, None, :, :], y.shape).reshape(-1) > 0.5
    y = y.reshape(-1)[m]
    p = p.reshape(-1)[m]
    out = {
        "pr_auc": float(average_precision_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "roc_auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "brier": float(brier_score_loss(y, p)) if len(y) else float("nan"),
        "pos_rate": float(y.mean()) if len(y) else float("nan"),
    }
    for th in (0.2, 0.3, 0.5, 0.7):
        pred = (p >= th).astype(np.int8)
        pr, rc, f1, _ = precision_recall_fscore_support(y, pred, average="binary",
                                                        zero_division=0)
        out[f"precision@{th}"] = float(pr)
        out[f"recall@{th}"] = float(rc)
        out[f"f1@{th}"] = float(f1)
    return out


def baseline_metrics(ds, loader, device):
    """Persistencia (hotspots en t0) y climatología (canal estático)."""
    y_pers, p_pers, y_clim, p_clim, masks = [], [], [], [], []
    with torch.no_grad():
        for b in loader:
            y = b["y"].numpy()
            mask = b["mask"].numpy()
            hist = b["x_hist"][:, -1, 1].numpy()  # presencia en t0 (B,32,32)
            clim = b["x_static"][:, 8].numpy()    # fire_climatology del mes
            y_pers.append(y)
            p_pers.append(np.repeat(hist[:, None, :, :], y.shape[1], axis=1))
            y_clim.append(y)
            p_clim.append(np.repeat(clim[:, None, :, :], y.shape[1], axis=1))
            masks.append(mask)
    y = np.concatenate(y_pers); m = np.concatenate(masks)
    return {
        "persistence": array_metrics(y, np.concatenate(p_pers), m),
        "climatology": array_metrics(y, np.concatenate(p_clim), m),
    }


def topk_hotspots(cfg, ds, loader, model, device, k: int = 20) -> pd.DataFrame:
    grid = read_json(Path(cfg["paths"]["static"]) / "grid.json")
    inv = Transformer.from_crs(grid["crs"], "EPSG:4326", always_xy=True)
    lookup = ds.index.set_index("anchor_idx")
    rows = []
    model.eval()
    with torch.no_grad():
        for b in loader:
            b = {kk: vv.to(device) for kk, vv in b.items() if torch.is_tensor(vv)}
            logits = model(b["x_hist"], b["x_fut"], b["x_static"], b["v"])
            probs = torch.sigmoid(logits).cpu().numpy()
            mask = b["mask"].cpu().numpy()
            anchor_idx = b["anchor_idx"].cpu().numpy()
            for bi in range(probs.shape[0]):
                try:
                    idx = lookup.loc[int(anchor_idx[bi])]
                except KeyError:
                    continue
                if isinstance(idx, pd.DataFrame):
                    idx = idx.iloc[0]
                row0 = int(idx["row"]); col0 = int(idx["col"])
                t0 = pd.Timestamp(idx["t0"])
                hs_id = str(idx["hotspot_id"])
                for lead in range(probs.shape[1]):
                    p = probs[bi, lead].copy()
                    p[mask[bi] < 0.5] = -1.0
                    flat = p.reshape(-1)
                    kk = min(k, len(flat))
                    kth = max(0, len(flat) - kk)
                    top = np.argpartition(flat, kth)[-kk:]
                    top = top[np.argsort(flat[top])[::-1]]
                    for flat_idx in top:
                        if flat[flat_idx] <= 0.05:
                            continue
                        r, c = np.unravel_index(flat_idx, p.shape)
                        grow = row0 + int(r) - ds.half
                        gcol = col0 + int(c) - ds.half
                        if not (0 <= grow < grid["height"] and 0 <= gcol < grid["width"]):
                            continue
                        lon, lat = grid_lonlat_from_rowcol(np.array([grow]), np.array([gcol]),
                                                           grid, inv)
                        rows.append({
                            "hotspot_ancla": hs_id,
                            "anchor_idx": int(anchor_idx[bi]),
                            "lead": lead + 1,
                            "date": (t0 + pd.Timedelta(days=lead + 1)).date().isoformat(),
                            "lat": float(lat[0]),
                            "lon": float(lon[0]),
                            "prob": float(flat[flat_idx]),
                            "row": int(grow),
                            "col": int(gcol),
                        })
    df = pd.DataFrame(rows)
    if len(df):
        df = (df.sort_values(["date", "row", "col", "prob"], ascending=[True, True, True, False])
              .drop_duplicates(["date", "row", "col"], keep="first")
              .reset_index(drop=True))
    return df


def main() -> int:
    args = parse_args("Evaluación de hotspots y derivación clásica")
    cfg = load_config(args.config)
    data_dir = ensure_dir(cfg["paths"]["data"])
    rep = ensure_dir(cfg["paths"]["reports"])
    log = setup_logging("07_evaluate", data_dir / "logs" / "07_evaluate.log",
                        cfg["run"]["log_level"])

    split = args.split
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ds_split, dl_split = train_mod.make_loader(cfg, split, args.smoke, shuffle=False)
    model = train_mod.model_mod.HotspotCNN(
        dropout=float(cfg["model"]["dropout"])).to(device)
    ckpt_path = Path(cfg["paths"]["models"]) / ("best_smoke.pt" if args.smoke else "best.pt")
    if not ckpt_path.exists():
        log.error("Falta checkpoint %s; correr 06_train", ckpt_path)
        return 1
    ckpt = torch.load(ckpt_path, map_location=device)
    model.load_state_dict(ckpt["model"])
    log.info("Checkpoint %s época %s métrica %.4f", ckpt_path, ckpt.get("epoch"),
             ckpt.get("metric", float("nan")))

    weights = train_mod.model_mod.LossWeights(
        pos_weight=float(cfg["model"]["pos_weight"]),
        lambda_patch=float(cfg["model"]["lambda_patch"]),
        gamma=float(cfg["model"]["focal_gamma"]),
        lambda_count=float(cfg["model"]["lambda_count"]),
    )
    model_metrics = train_mod.evaluate(model, dl_split, device, weights)
    log.info("Métricas hotspot (%s): %s", split, model_metrics)

    base = baseline_metrics(ds_split, dl_split, device)
    log.info("Baselines: %s", base)

    k = int(max(cfg["eval"]["top_k_per_anchor"]))
    hs = topk_hotspots(cfg, ds_split, dl_split, model, device, k=k)
    n_before = len(hs)
    hs.to_parquet(rep / f"predicted_hotspots_{split}_all.parquet", index=False)
    if len(hs):
        min_prob = float(cfg["classic"].get("min_prob", 0.5))
        max_day = int(cfg["classic"].get("max_hotspots_per_day", 300))
        hs = hs[hs["prob"] >= min_prob].copy()
        hs = (hs.sort_values(["date", "prob"], ascending=[True, False])
              .groupby("date", sort=False).head(max_day)
              .sort_values(["date", "row", "col"]).reset_index(drop=True))
    hs.to_parquet(rep / f"predicted_hotspots_{split}.parquet", index=False)
    log.info("Hotspots predichos: %d (antes del presupuesto: %d)", len(hs), n_before)

    fires = classic_mod.derive_fires(hs, cfg, log) if len(hs) else pd.DataFrame()
    events = classic_mod.derive_events(fires, cfg, log) if len(fires) else pd.DataFrame()
    if len(fires):
        fires.to_parquet(rep / f"predicted_fires_{split}.parquet", index=False)
    if len(events):
        events.to_parquet(rep / f"predicted_events_{split}.parquet", index=False)
    comp = classic_mod.compare_to_real(
        fires, events, cfg, t0=pd.Timestamp(cfg["periods"][f"{split}_end"]),
        start=cfg["periods"][f"{split}_start"],
        end=cfg["periods"][f"{split}_end"], log=log)

    out = {
        "checkpoint": str(ckpt_path),
        "epoch": ckpt.get("epoch"),
        "hotspot_metrics": model_metrics,
        "baselines": base,
        "classic": comp,
        "n_predicted_hotspots": int(len(hs)),
        "n_topk_before_budget": int(n_before),
        "n_predicted_fires": int(len(fires)),
        "n_predicted_events": int(len(events)),
    }
    write_json(rep / f"metrics_{split}.json", out)

    lines = [
        f"# Reporte de evaluación — hotspots Córdoba ({split})",
        "",
        f"- Checkpoint: `{ckpt_path}` (época {ckpt.get('epoch')})",
        f"- Hotspots predichos: {len(hs)}; incendios clásicos: {len(fires)}; eventos: {len(events)}",
        "",
        "## Métricas de hotspot",
        "",
        f"- PR-AUC: {model_metrics['pr_auc']:.4f}",
        f"- ROC-AUC: {model_metrics['roc_auc']:.4f}",
        f"- Brier: {model_metrics['brier']:.4f}",
        f"- Recall@0.5: {model_metrics['recall@0.5']:.4f}",
        f"- Patch hit rate: {model_metrics['patch_hit_rate']:.4f}",
        "",
        "## Baselines",
        "",
        f"- Persistencia PR-AUC: {base['persistence']['pr_auc']:.4f}",
        f"- Climatología PR-AUC: {base['climatology']['pr_auc']:.4f}",
        "",
        "## Derivación clásica",
        "",
        f"- Incendios: {comp['fires']}",
        f"- Eventos: {comp['events']}",
        f"- Enlace: {comp.get('link', {})}",
    ]
    (rep / f"report_{split}.md").write_text("\n".join(lines), encoding="utf-8")
    log.info("Reporte en %s", rep / f"report_{split}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
