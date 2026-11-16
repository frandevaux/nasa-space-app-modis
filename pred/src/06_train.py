"""Etapa 06 — entrenamiento CNN+LSTM con métricas y visualizaciones en vivo."""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime
from importlib.machinery import SourceFileLoader
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import (average_precision_score, brier_score_loss,
                             precision_recall_fscore_support, roc_auc_score)
from torch.utils.data import DataLoader
from torch.utils.tensorboard import SummaryWriter
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ensure_dir, load_config, parse_args, seed_everything, write_json  # noqa: E402

SRC = Path(__file__).resolve().parent
ds_mod = SourceFileLoader("hotspot_dataset", str(SRC / "04_dataset.py")).load_module()
model_mod = SourceFileLoader("hotspot_model", str(SRC / "05_model.py")).load_module()


def make_loader(cfg: dict, split: str, smoke: bool, shuffle: bool):
    ds = ds_mod.FireHotspotDataset(cfg, split, smoke=smoke)
    workers = 0 if smoke else int(cfg["model"]["num_workers"])
    bs = 8 if smoke else int(cfg["model"]["batch_size"])
    return ds, DataLoader(
        ds, batch_size=bs, shuffle=shuffle, num_workers=workers,
        pin_memory=True, persistent_workers=workers > 0,
        drop_last=shuffle,
    )


def to_device(batch, device):
    out = {}
    for k, v in batch.items():
        out[k] = v.to(device, non_blocking=True) if torch.is_tensor(v) else v
    return out


@torch.no_grad()
def evaluate(model, loader, device, weights, max_points: int = 30_000_000):
    model.eval()
    losses = []
    probs, ys, masks = [], [], []
    patch_hits = []
    patch_total = 0
    for batch in loader:
        b = to_device(batch, device)
        logits = model(b["x_hist"], b["x_fut"], b["x_static"], b["v"])
        loss = model_mod.compute_loss(logits, b["y"], b["y_count"], b["mask"], weights)
        losses.append(float(loss["loss"]))
        p = torch.sigmoid(logits)
        m = b["mask"].unsqueeze(1).expand_as(p) > 0.5
        probs.append(p[m].cpu().numpy())
        ys.append(b["y"][m].cpu().numpy())
        # patch hit: para cada (muestra, lead) con positivos, ¿max prob > 0.5?
        has = (b["y"] * m).sum(dim=(2, 3)) > 0.5
        pmax = (p * b["y"]).amax(dim=(2, 3))
        if has.any():
            patch_hits.append((pmax[has] > 0.5).float().cpu().numpy())
            patch_total += int(has.sum())
    p = np.concatenate(probs) if probs else np.array([])
    y = np.concatenate(ys) if ys else np.array([])
    if len(p) > max_points:
        rng = np.random.default_rng(0)
        pos = np.flatnonzero(y > 0.5)
        neg = np.flatnonzero(y <= 0.5)
        keep_neg = rng.choice(neg, size=max_points - len(pos), replace=False)
        idx = np.concatenate([pos, keep_neg])
        p, y = p[idx], y[idx]
    out = {
        "loss": float(np.mean(losses)) if losses else float("nan"),
        "pr_auc": float(average_precision_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "roc_auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "brier": float(brier_score_loss(y, p)) if len(y) else float("nan"),
        "pos_rate": float(y.mean()) if len(y) else float("nan"),
        "patch_hit_rate": float(np.concatenate(patch_hits).mean()) if patch_hits else float("nan"),
        "n_patch_pos": int(patch_total),
        "n_points": int(len(y)),
    }
    for th in (0.2, 0.3, 0.5, 0.7):
        pred = (p >= th).astype(np.int8)
        pr, rc, f1, _ = precision_recall_fscore_support(y, pred, average="binary", zero_division=0)
        out[f"precision@{th}"] = float(pr)
        out[f"recall@{th}"] = float(rc)
        out[f"f1@{th}"] = float(f1)
    return out


def make_val_figure(ds, indices, model, device, out_path: Path):
    model.eval()
    rows = min(4, len(indices))
    fig, axes = plt.subplots(rows, 4, figsize=(12, 3 * rows))
    if rows == 1:
        axes = np.array([axes])
    for j, idx in enumerate(indices[:rows]):
        b = ds[int(idx)]
        xh = b["x_hist"].unsqueeze(0).to(device)
        xf = b["x_fut"].unsqueeze(0).to(device)
        xs = b["x_static"].unsqueeze(0).to(device)
        vv = b["v"].unsqueeze(0).to(device)
        with torch.no_grad():
            p = torch.sigmoid(model(xh, xf, xs, vv))[0].cpu().numpy()
        hist = b["x_hist"][-1, 1].numpy()
        true = b["y"].sum(0).numpy()
        axes[j, 0].imshow(hist, cmap="magma")
        axes[j, 0].set_title("hotspots t0")
        axes[j, 1].imshow(true, cmap="magma")
        axes[j, 1].set_title("futuro real (suma 7d)")
        axes[j, 2].imshow(p[0], cmap="viridis", vmin=0, vmax=1)
        axes[j, 2].set_title("prob lead 1")
        axes[j, 3].imshow(p[6], cmap="viridis", vmin=0, vmax=1)
        axes[j, 3].set_title("prob lead 7")
        for ax in axes[j]:
            ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def main() -> int:
    args = parse_args("Entrenamiento CNN+LSTM")
    cfg = load_config(args.config)
    data_dir = ensure_dir(cfg["paths"]["data"])
    models_dir = ensure_dir(cfg["paths"]["models"])
    runs_dir = ensure_dir(cfg["paths"]["runs"])
    log_path = data_dir / "logs" / "06_train.log"
    from common import setup_logging
    log = setup_logging("06_train", log_path, cfg["run"]["log_level"])

    seed_everything(int(cfg["project"]["seed"]))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("Device: %s", device)

    ds_train, dl_train = make_loader(cfg, "train", args.smoke, shuffle=True)
    ds_val, dl_val = make_loader(cfg, "val", args.smoke, shuffle=False)
    log.info("Train: %d; Val: %d", len(ds_train), len(ds_val))

    model = model_mod.HotspotCNN(dropout=float(cfg["model"]["dropout"])).to(device)
    log.info("Parámetros: %d", model_mod.param_count(model))

    weights = model_mod.LossWeights(
        pos_weight=float(cfg["model"]["pos_weight"]),
        lambda_patch=float(cfg["model"]["lambda_patch"]),
        gamma=float(cfg["model"]["focal_gamma"]),
        lambda_count=float(cfg["model"]["lambda_count"]),
    )
    opt = torch.optim.AdamW(model.parameters(), lr=float(cfg["model"]["lr"]),
                            weight_decay=float(cfg["model"]["weight_decay"]))
    epochs = 2 if args.smoke else int(args.epochs or cfg["model"]["epochs"])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    amp = bool(cfg["model"]["amp"]) and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp)

    run_name = datetime.now().strftime("%Y%m%d-%H%M%S") + ("-smoke" if args.smoke else "")
    writer = SummaryWriter(log_dir=str(runs_dir / run_name)) if not args.smoke else None
    history_path = models_dir / ("history_smoke.csv" if args.smoke else "history.csv")
    history = []
    best_metric = -1e9
    patience = 0
    best_path = models_dir / ("best_smoke.pt" if args.smoke else "best.pt")

    # Muestras fijas para visualizaciones.
    val_pos = ds_val.index[ds_val.index["n_future_cells"] > 0].index.tolist()
    vis_idx = val_pos[:4] if val_pos else list(range(min(4, len(ds_val))))

    for epoch in range(1, epochs + 1):
        model.train()
        t0 = time.time()
        tot = {"loss": 0.0, "bce": 0.0, "patch": 0.0, "n": 0}
        pbar = tqdm(dl_train, desc=f"epoch {epoch}/{epochs}", leave=False)
        for batch in pbar:
            b = to_device(batch, device)
            opt.zero_grad(set_to_none=True)
            with torch.amp.autocast("cuda", enabled=amp):
                logits = model(b["x_hist"], b["x_fut"], b["x_static"], b["v"])
                losses = model_mod.compute_loss(logits, b["y"], b["y_count"], b["mask"], weights)
            scaler.scale(losses["loss"]).backward()
            scaler.unscale_(opt)
            nn.utils.clip_grad_norm_(model.parameters(), float(cfg["model"]["grad_clip"]))
            scaler.step(opt)
            scaler.update()
            for k in ("loss", "bce", "patch"):
                tot[k] += float(losses[k]) * b["x_hist"].shape[0]
            tot["n"] += b["x_hist"].shape[0]
            pbar.set_postfix(loss=float(losses["loss"]))
        sched.step()
        train_loss = {k: tot[k] / max(tot["n"], 1) for k in ("loss", "bce", "patch")}

        val = evaluate(model, dl_val, device, weights, max_points=4_000_000)
        metric = 0.5 * (val["pr_auc"] if np.isfinite(val["pr_auc"]) else 0.0) + 0.5 * (
            val["patch_hit_rate"] if np.isfinite(val["patch_hit_rate"]) else 0.0)
        elapsed = time.time() - t0
        row = {
            "epoch": epoch, "lr": opt.param_groups[0]["lr"], "time_s": elapsed,
            **{f"train_{k}": v for k, v in train_loss.items()},
            **{f"val_{k}": v for k, v in val.items()},
            "metric": metric,
        }
        history.append(row)
        log.info("epoch %d loss=%.4f val_loss=%.4f PR-AUC=%.4f recall@0.5=%.4f "
                 "patch_hit=%.4f metric=%.4f (%.1fs)",
                 epoch, train_loss["loss"], val["loss"], val["pr_auc"],
                 val["recall@0.5"], val["patch_hit_rate"], metric, elapsed)

        if writer is not None:
            for k, v in row.items():
                if isinstance(v, (int, float)) and np.isfinite(v):
                    writer.add_scalar(k, v, epoch)
            try:
                fig_path = models_dir / "last_val_figure.png"
                make_val_figure(ds_val, vis_idx, model, device, fig_path)
                img = plt.imread(fig_path)
                if img.dtype != np.uint8:
                    img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
                writer.add_image("val/examples", torch.from_numpy(img).permute(2, 0, 1), epoch)
            except Exception as exc:  # noqa: BLE001
                log.warning("No se pudo generar figura: %s", exc)

        if metric > best_metric:
            best_metric = metric
            patience = 0
            torch.save({
                "model": model.state_dict(),
                "epoch": epoch,
                "metric": metric,
                "val": val,
                "config": cfg,
            }, best_path)
            log.info("Nuevo mejor checkpoint en %s", best_path)
        else:
            patience += 1
            if patience >= int(cfg["model"]["patience"]):
                log.info("Early stopping en época %d", epoch)
                break

    with history_path.open("w", newline="", encoding="utf-8") as fh:
        keys = list(history[0].keys())
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(history)
    if writer is not None:
        writer.close()

    # Curva de entrenamiento rápida.
    try:
        fig, ax = plt.subplots(1, 2, figsize=(10, 4))
        ax[0].plot([r["epoch"] for r in history], [r["train_loss"] for r in history], label="train")
        ax[0].plot([r["epoch"] for r in history], [r["val_loss"] for r in history], label="val")
        ax[0].set_title("loss"); ax[0].legend()
        ax[1].plot([r["epoch"] for r in history], [r["val_pr_auc"] for r in history], label="PR-AUC")
        ax[1].plot([r["epoch"] for r in history], [r["val_patch_hit_rate"] for r in history],
                   label="patch hit")
        ax[1].set_title("val"); ax[1].legend()
        fig.tight_layout()
        fig.savefig(cfg["paths"]["reports"] + "/training_curves.png", dpi=120)
        plt.close(fig)
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo guardar training_curves: %s", exc)

    write_json(models_dir / ("last_metrics_smoke.json" if args.smoke else "last_metrics.json"),
               {"best_metric": best_metric, "history": history})
    log.info("Listo. Mejor métrica=%.4f", best_metric)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
