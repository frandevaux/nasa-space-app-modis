"""Etapa 02 — dedup, filtro de vegetación e inferencia de type en NRT.

- Dedup por (satellite, lat, lon, ts_utc), prioridad archive > SP > NRT.
- Archive/SP: se conserva type == 0; type != 0 queda como referencia.
- NRT (sin type): se descarta si toca un hotspot histórico type != 0 de los
  365 días anteriores con d_ij <= r_i + r_j.
- Asigna hotspot_id determinístico y hotspot_pk.

Salidas:
  prep/data/interim/02_hotspots_clean.parquet
  prep/data/interim/02_nrt_discards.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo  # noqa: E402
import ids  # noqa: E402
from common import RunContext, open_duckdb, write_parquet_atomic  # noqa: E402
from gpu import knn_gpu  # noqa: E402

LOOKBACK_DAYS = 365
DAY_NS = 24 * 3600 * 10**9


def dedup_and_split(ctx: RunContext) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    con = open_duckdb(ctx)
    src = ctx.interim("01_hotspots_raw.parquet")
    raw_count = con.execute(f"SELECT count(*) FROM read_parquet('{src}')").fetchone()[0]
    con.execute(f"""
        CREATE TEMP TABLE dedup AS
        SELECT * EXCLUDE rn FROM (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY satellite, latitude, longitude, ts_utc
                       ORDER BY priority, source_file, source_row
                   ) AS rn
            FROM read_parquet('{src}')
        ) WHERE rn = 1
    """)
    dedup_count = con.execute("SELECT count(*) FROM dedup").fetchone()[0]
    known = con.execute("""
        SELECT * FROM dedup WHERE product IN ('archive', 'SP')
    """).df()
    nrt = con.execute("""
        SELECT * FROM dedup WHERE product = 'NRT'
    """).df()
    stats = {
        "rows_raw": int(raw_count),
        "rows_dedup": int(dedup_count),
        "duplicates": int(raw_count - dedup_count),
        "known_rows": int(len(known)),
        "nrt_rows": int(len(nrt)),
    }
    return known, nrt, pd.DataFrame(), stats


def _project(df: pd.DataFrame, transformer) -> pd.DataFrame:
    x, y = geo.project_points(df["longitude"].to_numpy(), df["latitude"].to_numpy(), transformer)
    out = df.copy()
    out["x"] = x
    out["y"] = y
    out["r_m"] = geo.radius_m(df["scan_km"].to_numpy(), df["track_km"].to_numpy())
    return out


def _candidates_cpu(tree: cKDTree, xy: np.ndarray, r: np.ndarray,
                    r_hist_max: float) -> list[np.ndarray]:
    return tree.query_ball_point(xy, r=r + r_hist_max)


def _candidates_gpu(hist_xy: np.ndarray, xy: np.ndarray, r: np.ndarray,
                    r_hist_max: float, tree: cKDTree, gpu) -> tuple[list[np.ndarray], int]:
    """candidatos GPU con verificación exacta en CPU para puntos saturados."""
    n_hist = len(hist_xy)
    k = int(min(32, n_hist))
    dist, idx = knn_gpu(hist_xy, xy, k, gpu=gpu)
    out: list[np.ndarray] = []
    n_fallback = 0
    for i in range(len(xy)):
        row_idx = idx[i]
        row_dist = dist[i]
        # Si el k-ésimo vecino está dentro del radio, puede haber más.
        saturated = bool(row_dist[-1] <= (r[i] + r_hist_max + 1.0))
        if saturated:
            out.append(np.asarray(tree.query_ball_point(xy[i], r=r[i] + r_hist_max),
                                  dtype=np.int64))
            n_fallback += 1
        else:
            out.append(row_idx.astype(np.int64, copy=False))
    return out, n_fallback


def infer_nrt(ctx: RunContext, known: pd.DataFrame, nrt: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Devuelve (nrt_keep, nrt_discards, stats)."""
    transformer = geo.make_transformer(ctx.cfg)
    hist = _project(known[known["type"].isin([1, 2, 3])].reset_index(drop=True), transformer)
    nrtp = _project(nrt.reset_index(drop=True), transformer)

    lookback_ns = int(ctx.cfg["type_inference"]["lookback_days"]) * DAY_NS
    min_gpu_rows = int(ctx.cfg.get("gpu", {}).get("min_type_inference_rows", 1_000_000))
    use_gpu = bool(ctx.gpu and ctx.gpu.available and ctx.gpu.has_cuml
                   and len(nrtp) >= min_gpu_rows)
    discard = np.zeros(len(nrtp), dtype=bool)
    nearest = np.full(len(nrtp), -1, dtype=np.int64)
    nearest_dist = np.full(len(nrtp), np.nan, dtype=float)
    n_fallback = 0

    if len(hist) == 0 or len(nrtp) == 0:
        stats = {"nrt_total": int(len(nrtp)), "discarded": 0, "kept": int(len(nrtp)),
                 "gpu": use_gpu, "gpu_saturated_fallback": 0}
        nrtp["type"] = 0
        nrtp["type_inferred"] = True
        return nrtp, nrtp.iloc[0:0].copy(), stats

    hist_ts = hist["ts_utc"].astype("datetime64[ns]").astype("int64").to_numpy()
    hist_r = hist["r_m"].to_numpy()
    hist_x = hist["x"].to_numpy()
    hist_y = hist["y"].to_numpy()
    hist_xy = np.column_stack([hist_x, hist_y])
    r_hist_max = float(hist_r.max())

    # Se procesa por mes para que el subconjunto histórico respete la ventana
    # de 365 días y el kNN/KD-tree sea exacto y chico.
    months = nrtp["ts_utc"].dt.to_period("M")
    for period in sorted(months.unique()):
        nrt_mask = (months == period).to_numpy()
        idx_nrt = np.flatnonzero(nrt_mask)
        if idx_nrt.size == 0:
            continue
        month_start = period.start_time
        month_end = period.end_time
        hist_mask = ((hist["ts_utc"] >= month_start - pd.Timedelta(days=LOOKBACK_DAYS)) &
                     (hist["ts_utc"] < month_end)).to_numpy()
        hidx = np.flatnonzero(hist_mask)
        if hidx.size == 0:
            continue
        hxy = hist_xy[hidx]
        hr = hist_r[hidx]
        hts = hist_ts[hidx]
        tree = cKDTree(hxy)
        qxy = nrtp.loc[idx_nrt, ["x", "y"]].to_numpy()
        qr = nrtp.loc[idx_nrt, "r_m"].to_numpy()
        qts = nrtp.loc[idx_nrt, "ts_utc"].astype("datetime64[ns]").astype("int64").to_numpy()

        if use_gpu:
            try:
                cands, fb = _candidates_gpu(hxy, qxy, qr, float(hr.max()), tree, ctx.gpu)
                n_fallback += fb
            except Exception as exc:  # noqa: BLE001
                ctx.log.warning("kNN GPU falló (%s); se usa CPU", exc)
                cands = _candidates_cpu(tree, qxy, qr, float(hr.max()))
        else:
            cands = _candidates_cpu(tree, qxy, qr, float(hr.max()))

        for local_i, global_i in enumerate(idx_nrt):
            c = cands[local_i]
            if len(c) == 0:
                continue
            c = np.asarray(c, dtype=np.int64)
            # ventana temporal: [ts_i - 365d, ts_i)
            ok_t = (hts[c] >= qts[local_i] - lookback_ns) & (hts[c] < qts[local_i])
            if not ok_t.any():
                continue
            c = c[ok_t]
            d = np.hypot(hxy[c, 0] - qxy[local_i, 0], hxy[c, 1] - qxy[local_i, 1])
            ok_d = d <= (qr[local_i] + hr[c])
            if not ok_d.any():
                continue
            d = d[ok_d]
            c = c[ok_d]
            best = int(np.argmin(d))
            discard[global_i] = True
            nearest[global_i] = hidx[c[best]]
            nearest_dist[global_i] = float(d[best])

    nrtp["type"] = 0
    nrtp["type_inferred"] = True
    nrtp.loc[discard, "type_inferred"] = False

    keep = nrtp.loc[~discard].copy()
    dropped = nrtp.loc[discard].copy()
    if len(dropped):
        src = hist.iloc[nearest[discard]].reset_index(drop=True)
        dropped = dropped.reset_index(drop=True)
        dropped["nearest_hist_lat"] = src["latitude"].to_numpy()
        dropped["nearest_hist_lon"] = src["longitude"].to_numpy()
        dropped["nearest_hist_ts"] = src["ts_utc"].to_numpy()
        dropped["nearest_hist_type"] = src["type"].to_numpy()
        dropped["nearest_dist_m"] = nearest_dist[discard]
    stats = {
        "nrt_total": int(len(nrtp)),
        "discarded": int(discard.sum()),
        "kept": int((~discard).sum()),
        "gpu": use_gpu,
        "gpu_saturated_fallback": int(n_fallback),
    }
    return keep, dropped, stats


def assign_ids(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    lat = df["latitude"].map(lambda v: f"{0.0 if abs(v) < 1e-12 else v:.6f}")
    lon = df["longitude"].map(lambda v: f"{0.0 if abs(v) < 1e-12 else v:.6f}")
    ts = df["ts_utc"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    text = ("v1|" + df["satellite"].astype(str) + "|" + lat + "|" + lon + "|" + ts)
    df["hotspot_id"] = text.map(lambda s: "HS-" + ids._digest(s))
    df = df.sort_values(["ts_utc", "satellite", "latitude", "longitude"],
                        kind="stable").reset_index(drop=True)
    df["hotspot_pk"] = np.arange(len(df), dtype=np.int64)
    return df


def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("02_clean", argv)
    try:
        ctx.init_gpu()
        known, nrt, _, stats = dedup_and_split(ctx)
        ctx.stats.add("clean.rows_raw", stats["rows_raw"])
        ctx.stats.add("clean.rows_dedup", stats["rows_dedup"])
        ctx.stats.add("clean.duplicates", stats["duplicates"])

        # Archive/SP: separar type 0 de fuentes no vegetales.
        null_type = int(known["type"].isna().sum())
        if null_type:
            ctx.stats.warn(f"Archive/SP con type NULL: {null_type}; se descartan")
        known = known[known["type"].notna()].copy()
        known_zero = known[known["type"] == 0].copy()
        known_zero["type_inferred"] = False
        known_nonzero = known[known["type"] != 0].copy()
        ctx.stats.add("clean.known_zero", int(len(known_zero)))
        ctx.stats.add("clean.known_nonzero", int(len(known_nonzero)))
        ctx.stats.table("clean.known_nonzero_by_type",
                        known_nonzero.groupby("type").size().reset_index(name="rows").to_dict("records"))

        nrt_keep, nrt_discards, infer_stats = infer_nrt(ctx, known, nrt)
        ctx.stats.add("clean.nrt_total", infer_stats["nrt_total"])
        ctx.stats.add("clean.nrt_discarded", infer_stats["discarded"])
        ctx.stats.add("clean.nrt_kept", infer_stats["kept"])
        ctx.stats.add("clean.gpu_type_inference", infer_stats["gpu"])
        ctx.stats.add("clean.gpu_saturated_fallback", infer_stats["gpu_saturated_fallback"])

        combined = pd.concat([known_zero, nrt_keep], ignore_index=True)
        combined = assign_ids(combined)
        ctx.stats.add("clean.rows_final", int(len(combined)))
        ctx.stats.table("clean.final_by_product",
                        combined.groupby("product").size().reset_index(name="rows").to_dict("records"))

        out = ctx.interim("02_hotspots_clean.parquet")
        write_parquet_atomic(combined, out)
        if len(nrt_discards):
            d = nrt_discards.drop(columns=[c for c in ("x", "y", "r_m") if c in nrt_discards.columns])
            write_parquet_atomic(d, ctx.interim("02_nrt_discards.parquet"))

        ctx.stats.flush()
        ctx.log.info("Etapa 02 OK: %d filas finales (%d duplicados, %d NRT descartados)",
                     len(combined), stats["duplicates"], infer_stats["discarded"])
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 02 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
