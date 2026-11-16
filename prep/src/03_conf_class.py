"""Etapa 03 — conf_class, pass_bin, era, proyección y radios.

- VIIRS conserva l/n/h; MODIS numérico -> l/n/h con cortes 30/80.
- pass_bin local UTC-3: día [07:00,19:00), noche [19:00,07:00) con fecha
  de inicio; se guardan bin_start_utc y bin_end_utc.
- Proyección TM lon_0=-63 y r_i = 0.5*sqrt(scan^2+track^2)*1000.

Salida:
  prep/data/interim/03_hotspots_classified.parquet
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo  # noqa: E402
from common import RunContext, write_parquet_atomic  # noqa: E402


def add_conf_class(df: pd.DataFrame, cfg: dict, ctx: RunContext) -> pd.DataFrame:
    df = df.copy()
    classes = pd.Series(pd.NA, index=df.index, dtype="string")
    viirs_mask = df["sensor"] == "VIIRS"
    raw = df["conf_raw"].astype("string").str.strip().str.lower()
    classes.loc[viirs_mask] = raw.loc[viirs_mask]
    valid_viirs = set(cfg["conf_class"]["viirs_values"])
    bad_viirs = viirs_mask & ~raw.isin(valid_viirs)
    if bad_viirs.any():
        ctx.stats.warn(f"VIIRS con confianza inválida: {int(bad_viirs.sum())}")

    modis_mask = df["sensor"] == "MODIS"
    numeric = pd.to_numeric(raw.loc[modis_mask], errors="coerce")
    bins = cfg["conf_class"]["modis_bins"]
    modis_class = pd.Series(pd.NA, index=df.loc[modis_mask].index, dtype="string")
    for rule in bins:
        lo = float(rule["min"])
        if "max_exclusive" in rule:
            mask = (numeric >= lo) & (numeric < float(rule["max_exclusive"]))
        else:
            mask = (numeric >= lo) & (numeric <= float(rule["max_inclusive"]))
        modis_class.loc[mask] = rule["class"]
    bad_modis = modis_mask & numeric.isna()
    if bad_modis.any():
        ctx.stats.warn(f"MODIS con confianza no numérica: {int(bad_modis.sum())}")
    classes.loc[modis_mask] = modis_class.to_numpy()
    df["conf_class"] = classes
    df["conf_numeric"] = np.nan
    df.loc[modis_mask, "conf_numeric"] = numeric.to_numpy()
    ctx.stats.table("class.by_conf_class",
                    df.groupby("conf_class", dropna=False).size().reset_index(name="rows").to_dict("records"))
    return df


def add_pass_bin(df: pd.DataFrame, cfg: dict, ctx: RunContext) -> pd.DataFrame:
    df = df.copy()
    local = pd.to_datetime(df["ts_local"])
    offset = int(cfg["pass_bin"]["utc_offset_hours"])
    day_start = int(cfg["pass_bin"]["day_start_hour"])
    night_start = int(cfg["pass_bin"]["night_start_hour"])
    day_label = cfg["pass_bin"]["day_label"]
    night_label = cfg["pass_bin"]["night_label"]

    hour = local.dt.hour
    day_mask = (hour >= day_start) & (hour < night_start)
    date = local.dt.normalize()
    night_date = date - pd.to_timedelta((hour < day_start).astype(int), unit="D")
    bin_date = date.where(day_mask, night_date)
    label = np.where(day_mask, day_label, night_label)
    df["pass_bin"] = bin_date.dt.strftime("%Y-%m-%d") + "_" + label
    start_hour = np.where(day_mask, day_start, night_start)
    start_local = bin_date + pd.to_timedelta(start_hour, unit="h")
    # local = UTC + offset  =>  UTC = local - offset
    df["bin_start_utc"] = start_local - pd.Timedelta(hours=offset)
    df["bin_end_utc"] = df["bin_start_utc"] + pd.Timedelta(hours=12)

    ts = pd.to_datetime(df["ts_utc"])
    outside = ((ts < df["bin_start_utc"]) | (ts >= df["bin_end_utc"]))
    if outside.any():
        ctx.stats.warn(f"pass_bin: {int(outside.sum())} filas fuera de su ventana")
    return df


def add_era(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    df = df.copy()
    ts = pd.to_datetime(df["ts_utc"])
    start_viirs = pd.Timestamp(cfg["eras"]["MODIS+VIIRS"]["start"])
    start_solo_viirs = pd.Timestamp(cfg["eras"]["solo_VIIRS"]["start"])
    df["era"] = np.select(
        [ts < start_viirs, ts < start_solo_viirs],
        ["solo_MODIS", "MODIS+VIIRS"],
        default="solo_VIIRS",
    )
    standby = pd.Timestamp(cfg["operational_periods"]["modis"]["Terra"]["standby"])
    df["terra_post_standby"] = (df["satellite"] == "Terra") & (ts >= standby)
    return df


def pass_bin_diagnostics(df: pd.DataFrame, cfg: dict, ctx: RunContext) -> pd.DataFrame:
    local = pd.to_datetime(df["ts_local"])
    hist = (df.assign(bin15=local.dt.floor("15min"))
              .groupby(["satellite", "bin15"], observed=True)
              .size().reset_index(name="rows"))
    hist_path = ctx.stats_dir() / "pass_bin_histogram_15min.csv"
    hist.to_csv(hist_path, index=False)
    ctx.stats.add("pass_bin.histogram_csv", str(hist_path))

    minute_of_day = local.dt.hour * 60 + local.dt.minute + local.dt.second / 60.0
    guard = int(cfg["pass_bin"]["validate"]["guard_minutes"])
    cuts = np.array([int(cfg["pass_bin"]["day_start_hour"]) * 60,
                     int(cfg["pass_bin"]["night_start_hour"]) * 60])
    dist = np.min(np.abs(minute_of_day.to_numpy()[:, None] - cuts[None, :]), axis=1)
    frac_near = float((dist <= guard).mean())
    ctx.stats.add("pass_bin.fraction_near_cut", frac_near)
    limit = float(cfg["pass_bin"]["validate"]["max_fraction_near_cut"])
    if frac_near > limit:
        ctx.stats.warn(f"pass_bin: {frac_near:.4%} de los puntos está a <={guard} min de un corte")

    medians = (df.assign(local_hour=local.dt.hour)
                 .groupby(["satellite", "era"], observed=True)["local_hour"]
                 .median().reset_index())
    ctx.stats.table("pass_bin.median_local_hour", medians.to_dict("records"))
    return hist


def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("03_conf_class", argv)
    try:
        cfg = ctx.cfg
        src = ctx.interim("02_hotspots_clean.parquet")
        df = pd.read_parquet(src)
        ctx.stats.add("class.rows_in", int(len(df)))
        df = add_conf_class(df, cfg, ctx)
        df = add_pass_bin(df, cfg, ctx)
        df = add_era(df, cfg)

        transformer = geo.make_transformer(cfg)
        x, y = geo.project_points(df["longitude"].to_numpy(), df["latitude"].to_numpy(), transformer)
        df["x"] = x
        df["y"] = y
        df["r_m"] = geo.radius_m(df["scan_km"].to_numpy(), df["track_km"].to_numpy())
        df = df.sort_values(["pass_bin", "ts_utc", "hotspot_pk"], kind="stable").reset_index(drop=True)

        pass_bin_diagnostics(df, cfg, ctx)
        ctx.stats.add("class.rows_out", int(len(df)))
        ctx.stats.add("class.pass_bins", int(df["pass_bin"].nunique()))
        ctx.stats.add("class.terra_post_standby", int(df["terra_post_standby"].sum()))
        ctx.stats.table("class.by_era",
                        df.groupby("era").size().reset_index(name="rows").to_dict("records"))
        ctx.stats.table("class.by_pass_bin_top",
                        df.groupby("pass_bin").size().sort_values(ascending=False)
                          .head(20).reset_index(name="rows").to_dict("records"))
        ctx.stats.add("class.radius_m_min", float(df["r_m"].min()))
        ctx.stats.add("class.radius_m_max", float(df["r_m"].max()))

        out = ctx.interim("03_hotspots_classified.parquet")
        write_parquet_atomic(df, out)
        ctx.stats.flush()
        ctx.log.info("Etapa 03 OK: %d filas, %d pass_bins -> %s",
                     len(df), df["pass_bin"].nunique(), out)
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 03 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
