"""Etapa 06 — métrica confidence para incendios y eventos.

Implementa la métrica de confidence:
  p_i = p(class_i) * w_sensor
  P   = 1 - (1-p_M)*(1-p_V)
  P   = 1 - (1-P)*(1-rho)^(k-1)
  confidence = 100 * P * f_size * f_miss

Salidas:
  prep/data/interim/06_hotspots_final.parquet
  prep/data/interim/06_incendios_final.parquet
  prep/data/interim/06_eventos_final.parquet
  prep/data/interim/stats/confidence_by_era.csv
  prep/data/interim/stats/confidence_by_sensor_mix.csv
  prep/data/interim/stats/confidence_sensitivity.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RunContext, write_parquet_atomic  # noqa: E402


def fire_hotspot_aggregates(ctx: RunContext) -> pd.DataFrame:
    cfg = ctx.cfg
    p_class = {k: float(v) for k, v in cfg["confidence"]["p_class"].items()}
    w_sensor = {k: float(v) for k, v in cfg["confidence"]["w_sensor"].items()}
    fmap = pd.read_parquet(ctx.interim("04_fire_hotspot_map.parquet"))
    hs = pd.read_parquet(
        ctx.interim("03_hotspots_classified.parquet"),
        columns=["hotspot_pk", "sensor", "satellite", "conf_class", "terra_post_standby"],
    )
    df = fmap.merge(hs, on="hotspot_pk", how="left", validate="many_to_one")
    df["p_class"] = df["conf_class"].map(p_class).fillna(0.0).astype(float)
    df["p_sensor"] = df["sensor"].map(w_sensor).fillna(0.0).astype(float)
    if bool(cfg["confidence"].get("exclude_terra_post_standby", False)):
        df.loc[df["terra_post_standby"].fillna(False), "p_sensor"] = 0.0
    df["p"] = df["p_class"] * df["p_sensor"]
    df["p_modis"] = np.where(df["sensor"] == "MODIS", df["p"], 0.0)
    df["p_viirs"] = np.where(df["sensor"] == "VIIRS", df["p"], 0.0)
    df["p_class_modis"] = np.where(df["sensor"] == "MODIS", df["p_class"], 0.0)
    df["p_class_viirs"] = np.where(df["sensor"] == "VIIRS", df["p_class"], 0.0)
    df["is_aqua"] = (df["satellite"] == "Aqua").astype(np.int8)
    df["is_terra"] = (df["satellite"] == "Terra").astype(np.int8)
    df["is_viirs"] = (df["sensor"] == "VIIRS").astype(np.int8)
    agg = df.groupby("incendio_id", observed=True).agg(
        p_M=("p_modis", "max"),
        p_V=("p_viirs", "max"),
        p_class_M=("p_class_modis", "max"),
        p_class_V=("p_class_viirs", "max"),
        has_aqua=("is_aqua", "max"),
        has_terra=("is_terra", "max"),
        has_viirs=("is_viirs", "max"),
    )
    return agg


def fire_confidence(fires: pd.DataFrame, agg: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    conf = cfg["confidence"]
    rho = float(conf["rho"])
    base = float(conf["f_size"]["base"])
    gain = float(conf["f_size"]["gain"])
    scale = float(conf["f_size"]["scale_km2"])
    fmiss = conf["f_miss"]
    pre_viirs_end = pd.Timestamp(conf["pre_viirs_end_exclusive"])

    fires = fires.merge(agg, left_on="incendio_id", right_index=True, how="left")
    for col in ("p_M", "p_V", "p_class_M", "p_class_V", "has_aqua", "has_terra", "has_viirs"):
        if col not in fires:
            fires[col] = 0
        fires[col] = fires[col].fillna(0)

    pM = fires["p_M"].to_numpy(dtype=float)
    pV = fires["p_V"].to_numpy(dtype=float)
    P = 1.0 - (1.0 - pM) * (1.0 - pV)
    k = fires["n_pasadas"].to_numpy(dtype=float)
    P = 1.0 - (1.0 - P) * np.power(1.0 - rho, np.maximum(k - 1.0, 0.0))

    area = fires["area_pixeles_km2"].to_numpy(dtype=float)
    f_size = base + gain * (1.0 - np.exp(-area / scale))

    ts = pd.to_datetime(fires["t_inicio"])
    viirs_operative = ts >= pd.Timestamp(cfg["operational_periods"]["viirs_reference_start"])
    no_viirs = fires["has_viirs"].to_numpy(dtype=int) == 0
    has_modis = (fires["n_hotspots_modis"].to_numpy(dtype=int) > 0)
    f_miss = np.ones(len(fires), dtype=float)
    aqua_only = no_viirs & viirs_operative.to_numpy() & has_modis & (fires["has_aqua"].to_numpy(dtype=int) > 0)
    terra_only = no_viirs & viirs_operative.to_numpy() & has_modis & (fires["has_aqua"].to_numpy(dtype=int) == 0)
    f_miss[aqua_only] = float(fmiss["modis_aqua_only"])
    f_miss[terra_only] = float(fmiss["modis_terra_only"])

    confidence = 100.0 * P * f_size * f_miss
    pre_viirs = ts < pre_viirs_end
    confidence = np.where(pre_viirs.to_numpy(), np.minimum(confidence, float(conf["pre_viirs_cap"])),
                          confidence)
    confidence = np.clip(confidence, 0.0, 100.0)

    fires["p_M"] = pM
    fires["p_V"] = pV
    fires["P_base"] = P
    fires["k_pasadas"] = k
    fires["f_size"] = f_size
    fires["f_miss"] = f_miss
    fires["confidence"] = confidence
    fires["pre_viirs"] = pre_viirs.to_numpy()
    return fires


def event_confidence(events: pd.DataFrame, fires: pd.DataFrame,
                     fire_event: pd.DataFrame) -> pd.DataFrame:
    w = fires[["incendio_id", "area_pixeles_km2", "confidence"]].merge(
        fire_event, on="incendio_id", how="left", validate="many_to_one")
    w["weight"] = w["area_pixeles_km2"].clip(lower=1e-9)
    w["weighted"] = w["confidence"] * w["weight"]
    g = w.groupby("evento_id", observed=True).agg(
        sum_w=("weight", "sum"),
        sum_c=("weighted", "sum"),
        confidence_min=("confidence", "min"),
        confidence_max=("confidence", "max"),
    )
    g["confidence"] = np.where(g["sum_w"] > 0, g["sum_c"] / g["sum_w"],
                               events.set_index("evento_id")["confidence"].mean()
                               if "confidence" in events else 0.0)
    out = events.merge(g[["confidence", "confidence_min", "confidence_max"]],
                       left_on="evento_id", right_index=True, how="left")
    out["confidence"] = out["confidence"].fillna(0.0).clip(0.0, 100.0)
    return out


def sensitivity_table(fires: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    conf = cfg["confidence"]
    rho0 = float(conf["rho"])
    w_modis0 = float(conf["w_sensor"]["MODIS"])
    w_viirs = float(conf["w_sensor"]["VIIRS"])
    fmiss0 = float(conf["f_miss"]["modis_aqua_only"])
    p_class_M = fires["p_class_M"].to_numpy(dtype=float)
    p_class_V = fires["p_class_V"].to_numpy(dtype=float)
    k = fires["n_pasadas"].to_numpy(dtype=float)
    area = fires["area_pixeles_km2"].to_numpy(dtype=float)
    f_size = float(conf["f_size"]["base"]) + float(conf["f_size"]["gain"]) * (
        1.0 - np.exp(-area / float(conf["f_size"]["scale_km2"])))
    base_fmiss = fires["f_miss"].to_numpy(dtype=float)
    pre = fires["pre_viirs"].to_numpy(dtype=bool)

    rows = []
    variants = [
        ("base", w_modis0, rho0, fmiss0),
        ("w_MODIS-0.1", w_modis0 - 0.1, rho0, fmiss0),
        ("w_MODIS+0.1", w_modis0 + 0.1, rho0, fmiss0),
        ("rho-0.1", w_modis0, max(0.0, rho0 - 0.1), fmiss0),
        ("rho+0.1", w_modis0, rho0 + 0.1, fmiss0),
        ("f_miss-0.1", w_modis0, rho0, max(0.0, fmiss0 - 0.1)),
        ("f_miss+0.1", w_modis0, rho0, min(1.0, fmiss0 + 0.1)),
    ]
    for name, wm, rho, fm in variants:
        pM = p_class_M * wm
        pV = p_class_V * w_viirs
        P = 1.0 - (1.0 - pM) * (1.0 - pV)
        P = 1.0 - (1.0 - P) * np.power(1.0 - rho, np.maximum(k - 1.0, 0.0))
        fmiss = base_fmiss.copy()
        # Reemplaza solo el caso MODIS+Aqua sin VIIRS.
        aqua_case = (pV <= 0) & (pM > 0) & (fires["has_aqua"].to_numpy(dtype=int) > 0)
        fmiss[aqua_case] = fm
        c = 100.0 * P * f_size * fmiss
        c = np.where(pre, np.minimum(c, float(conf["pre_viirs_cap"])), c)
        c = np.clip(c, 0.0, 100.0)
        rows.append({
            "variant": name, "n": int(len(c)),
            "mean": float(np.mean(c)), "median": float(np.median(c)),
            "p10": float(np.percentile(c, 10)), "p90": float(np.percentile(c, 90)),
            "pre_viirs_max": float(np.max(c[pre])) if pre.any() else None,
        })
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("06_confidence", argv)
    try:
        cfg = ctx.cfg
        fires = pd.read_parquet(ctx.interim("04_fires_core.parquet"))
        lc = pd.read_parquet(ctx.interim("04_fire_landcover.parquet"))
        fires = fires.merge(lc, on="incendio_id", how="left")

        agg = fire_hotspot_aggregates(ctx)
        fires = fire_confidence(fires, agg, cfg)

        events = pd.read_parquet(ctx.interim("05_events_core.parquet"))
        fire_event = pd.read_parquet(ctx.interim("05_fire_event_map.parquet"))
        events = event_confidence(events, fires, fire_event)
        events_ar = events[events["incendios_argentina"] > 0].copy()

        # Hotspots finales con incendio, evento y confianzas.
        hs = pd.read_parquet(ctx.interim("03_hotspots_classified.parquet"))
        fmap = pd.read_parquet(ctx.interim("04_fire_hotspot_map.parquet"))
        emap = pd.read_parquet(ctx.interim("05_fire_event_map.parquet"))
        hs = hs.merge(fmap, on="hotspot_pk", how="left", validate="one_to_one")
        hs = hs.merge(emap, on="incendio_id", how="left", validate="many_to_one")
        fc = fires.set_index("incendio_id")[["confidence"]].rename(
            columns={"confidence": "confidence_incendio"})
        ec = events.set_index("evento_id")[["confidence"]].rename(
            columns={"confidence": "confidence_evento"})
        hs = hs.merge(fc, left_on="incendio_id", right_index=True, how="left")
        hs = hs.merge(ec, left_on="evento_id", right_index=True, how="left")

        write_parquet_atomic(hs, ctx.interim("06_hotspots_final.parquet"))
        write_parquet_atomic(fires, ctx.interim("06_incendios_final.parquet"))
        write_parquet_atomic(events, ctx.interim("06_eventos_final.parquet"))
        write_parquet_atomic(events_ar, ctx.interim("06_eventos_interim.parquet"))

        # Auditorías.
        by_era = fires.groupby("era").agg(
            n=("confidence", "size"), mean=("confidence", "mean"),
            median=("confidence", "median"), p10=("confidence", lambda s: s.quantile(0.1)),
            p90=("confidence", lambda s: s.quantile(0.9)),
        ).reset_index()
        by_era.to_csv(ctx.stats_dir() / "confidence_by_era.csv", index=False)

        fires["mix"] = np.select(
            [(fires["n_hotspots_modis"] > 0) & (fires["n_hotspots_viirs"] > 0),
             fires["n_hotspots_modis"] > 0],
            ["MODIS+VIIRS", "solo_MODIS"], default="solo_VIIRS")
        by_mix = fires.groupby("mix").agg(
            n=("confidence", "size"), mean=("confidence", "mean"),
            median=("confidence", "median"),
        ).reset_index()
        by_mix.to_csv(ctx.stats_dir() / "confidence_by_sensor_mix.csv", index=False)

        sens = sensitivity_table(fires, cfg)
        sens.to_csv(ctx.stats_dir() / "confidence_sensitivity.csv", index=False)

        c = fires["confidence"]
        ctx.stats.add("confidence.fires", int(len(c)))
        ctx.stats.add("confidence.min", float(c.min()))
        ctx.stats.add("confidence.max", float(c.max()))
        ctx.stats.add("confidence.median", float(c.median()))
        ctx.stats.add("confidence.mean", float(c.mean()))
        ctx.stats.add("confidence.events", int(len(events)))
        ctx.stats.add("confidence.event_median", float(events["confidence"].median()))
        pre = fires["pre_viirs"].to_numpy(dtype=bool)
        ctx.stats.add("confidence.pre_viirs_max",
                      float(fires.loc[pre, "confidence"].max()) if pre.any() else None)
        ctx.stats.table("confidence.by_era", by_era.to_dict("records"))
        ctx.stats.table("confidence.by_mix", by_mix.to_dict("records"))
        ctx.stats.table("confidence.sensitivity", sens.to_dict("records"))
        ctx.stats.flush()
        ctx.log.info("Etapa 06 OK: confidence incendios [%.1f, %.1f], mediana %.1f; "
                     "eventos mediana %.1f",
                     c.min(), c.max(), c.median(), events["confidence"].median())
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 06 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
