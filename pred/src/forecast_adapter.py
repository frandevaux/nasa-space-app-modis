"""Adaptador de clima: POWER observado (train) y Open-Meteo (inferencia).

Esquema canónico diario:
  date, t2m, t2m_max, rh2m, precip, ws10m_max, soil_moisture,
  vpd, days_since_rain, precip_7d

`make forecast-check` compara POWER vs Open-Meteo y escribe
`data/reports/forecast_compat.json`. No se usa en el entrenamiento.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ensure_dir, load_config, parse_args, setup_logging, write_json  # noqa: E402

CANON = ["date", "t2m", "t2m_max", "rh2m", "precip", "ws10m_max",
         "soil_moisture", "vpd", "days_since_rain", "precip_7d"]


def _derive(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    t2m = df["t2m"].to_numpy(float)
    rh = df["rh2m"].to_numpy(float)
    precip = df["precip"].to_numpy(float)
    es = 0.6108 * np.exp(17.27 * t2m / (t2m + 237.3))
    df["vpd"] = es * (1.0 - rh / 100.0)
    wet = precip >= 1.0
    ds = np.zeros(len(df), dtype=float)
    c = 0.0
    for i in range(len(df)):
        c = 0.0 if wet[i] else min(c + 1.0, 30.0)
        ds[i] = c
    df["days_since_rain"] = ds
    df["precip_7d"] = pd.Series(precip).rolling(7, min_periods=1).sum().to_numpy()
    return df


def _nearest_power_file(cfg: dict, lat: float, lon: float) -> Path:
    files = sorted(Path(cfg["paths"]["raw_power"]).glob("power_*.csv"))
    best, bestd = None, 1e9
    for f in files:
        stem = f.stem.replace("power_", "")
        la, lo = (float(x) for x in stem.split("_"))
        d = (la - lat) ** 2 + ((lo - lon) * np.cos(np.deg2rad(lat))) ** 2
        if d < bestd:
            best, bestd = f, d
    if best is None:
        raise FileNotFoundError("No hay CSV POWER")
    return best


class PowerObservedProvider:
    name = "power-observed"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def get(self, lat: float, lon: float, start: str | pd.Timestamp,
            days: int = 7) -> pd.DataFrame:
        start = pd.Timestamp(start).floor("D")
        f = _nearest_power_file(self.cfg, lat, lon)
        df = pd.read_csv(f, skiprows=14)
        df["date"] = pd.to_datetime(
            df["YEAR"].astype(str) + df["DOY"].astype(str).str.zfill(3),
            format="%Y%j")
        df = df.rename(columns={
            "T2M": "t2m", "T2M_MAX": "t2m_max", "RH2M": "rh2m",
            "PRECTOTCORR": "precip", "WS10M_MAX": "ws10m_max",
            "GWETTOP": "soil_moisture",
        })
        for c in ["t2m", "t2m_max", "rh2m", "precip", "ws10m_max", "soil_moisture"]:
            df[c] = pd.to_numeric(df[c], errors="coerce").replace(
                float(self.cfg["weather"]["missing_value"]), np.nan)
        lo = start - pd.Timedelta(days=30)
        hi = start + pd.Timedelta(days=days)
        df = df[(df["date"] >= lo) & (df["date"] <= hi)].sort_values("date")
        df = _derive(df)
        return df[df["date"] > start][CANON].reset_index(drop=True)


class OpenMeteoForecastProvider:
    name = "open-meteo"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def get(self, lat: float, lon: float, start: str | pd.Timestamp,
            days: int = 7) -> pd.DataFrame:
        start = pd.Timestamp(start).floor("D")
        url = self.cfg["forecast"]["open_meteo_url"]
        params = {
            "latitude": lat, "longitude": lon,
            "daily": ",".join([
                "temperature_2m_max", "temperature_2m_mean",
                "precipitation_sum", "wind_speed_10m_max",
            ]),
            "hourly": "relative_humidity_2m,soil_moisture_0_to_1cm",
            "timezone": self.cfg["forecast"]["timezone"],
            "wind_speed_unit": self.cfg["forecast"]["wind_speed_unit"],
            "past_days": 30,
            "forecast_days": int(days),
        }
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        js = r.json()
        daily = pd.DataFrame(js["daily"])
        daily["date"] = pd.to_datetime(daily["time"]).dt.floor("D")
        daily = daily.rename(columns={
            "temperature_2m_max": "t2m_max",
            "temperature_2m_mean": "t2m",
            "precipitation_sum": "precip",
            "wind_speed_10m_max": "ws10m_max",
        })
        # RH y humedad de suelo horarias -> medias diarias.
        hourly = pd.DataFrame(js.get("hourly", {}))
        if "time" in hourly:
            hourly["date"] = pd.to_datetime(hourly["time"]).dt.floor("D")
            cols = {}
            if "relative_humidity_2m" in hourly:
                cols["relative_humidity_2m"] = "rh2m"
            if "soil_moisture_0_to_1cm" in hourly:
                cols["soil_moisture_0_to_1cm"] = "soil_moisture"
            if cols:
                agg = hourly.groupby("date")[list(cols)].mean().reset_index().rename(columns=cols)
                daily = daily.merge(agg, on="date", how="left")
        if "rh2m" not in daily:
            daily["rh2m"] = np.nan
        if "soil_moisture" not in daily:
            daily["soil_moisture"] = np.nan
        for c in ["t2m", "t2m_max", "rh2m", "precip", "ws10m_max", "soil_moisture"]:
            if c not in daily:
                daily[c] = np.nan
            daily[c] = pd.to_numeric(daily[c], errors="coerce")
        daily = _derive(daily.sort_values("date"))
        return daily[daily["date"] > start][CANON].reset_index(drop=True)


def get_provider(cfg: dict, name: str | None = None):
    name = (name or cfg["forecast"]["provider"]).lower()
    if name in ("power", "power-observed"):
        return PowerObservedProvider(cfg)
    if name in ("open-meteo", "openmeteo"):
        return OpenMeteoForecastProvider(cfg)
    raise ValueError(f"Proveedor de pronóstico desconocido: {name}")


def compatibility_check(cfg: dict, log) -> dict:
    """Compara POWER vs Open-Meteo en puntos de Córdoba y escribe JSON."""
    points = [(-31.42, -64.18), (-30.60, -62.10), (-33.10, -64.30)]
    days = int(cfg["forecast"]["check_days"])
    end = pd.Timestamp("2026-11-01")  # fecha reciente con datos POWER estables
    start = end - pd.Timedelta(days=days)
    power = PowerObservedProvider(cfg)
    rows = []
    for lat, lon in points:
        try:
            p = power.get(lat, lon, start, days=days)
            # Para compatibilidad se comparan las fechas comunes de POWER vs
            # el histórico de Open-Meteo (no el forecast futuro).
            u = cfg["forecast"].get("open_meteo_archive_url",
                                    "https://archive-api.open-meteo.com/v1/archive")
            params = {
                "latitude": lat, "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_mean,precipitation_sum,wind_speed_10m_max",
                "hourly": "relative_humidity_2m,soil_moisture_0_to_1cm",
                "timezone": cfg["forecast"]["timezone"],
                "wind_speed_unit": "ms",
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": end.strftime("%Y-%m-%d"),
            }
            r = requests.get(u, params=params, timeout=60)
            r.raise_for_status()
            js = r.json()
            d = pd.DataFrame(js["daily"])
            d["date"] = pd.to_datetime(d["time"]).dt.floor("D")
            d = d.rename(columns={
                "temperature_2m_max": "t2m_max", "temperature_2m_mean": "t2m",
                "precipitation_sum": "precip", "wind_speed_10m_max": "ws10m_max",
            })
            h = pd.DataFrame(js.get("hourly", {}))
            if "time" in h:
                h["date"] = pd.to_datetime(h["time"]).dt.floor("D")
                cols = {}
                if "relative_humidity_2m" in h:
                    cols["relative_humidity_2m"] = "rh2m"
                if "soil_moisture_0_to_1cm" in h:
                    cols["soil_moisture_0_to_1cm"] = "soil_moisture"
                if cols:
                    agg = h.groupby("date")[list(cols)].mean().reset_index().rename(columns=cols)
                    d = d.merge(agg, on="date", how="left")
            if "rh2m" not in d:
                d["rh2m"] = np.nan
            if "soil_moisture" not in d:
                d["soil_moisture"] = np.nan
            m = p.merge(d, on="date", suffixes=("_power", "_om"))
            for var in ["t2m_max", "rh2m", "precip", "ws10m_max", "soil_moisture"]:
                a = m[f"{var}_power"].to_numpy(float)
                b = m[f"{var}_om"].to_numpy(float)
                ok = np.isfinite(a) & np.isfinite(b)
                if ok.sum() > 2:
                    corr = float(np.corrcoef(a[ok], b[ok])[0, 1])
                    bias = float(np.mean(b[ok] - a[ok]))
                    rmse = float(np.sqrt(np.mean((b[ok] - a[ok]) ** 2)))
                else:
                    corr = bias = rmse = float("nan")
                rows.append({"lat": lat, "lon": lon, "variable": var,
                             "n": int(ok.sum()), "corr": corr, "bias_om_minus_power": bias,
                             "rmse": rmse})
        except Exception as exc:  # noqa: BLE001
            log.warning("Compatibilidad falló en %.2f,%.2f: %s", lat, lon, exc)
            rows.append({"lat": lat, "lon": lon, "error": str(exc)})
    df = pd.DataFrame(rows)
    out = {
        "points": points,
        "period": [str(start.date()), str(end.date())],
        "rows": df.to_dict(orient="records"),
        "notes": [
            "POWER es una celda 0.5x0.625; Open-Meteo es un punto.",
            "soil_moisture: GWETTOP (MERRA-2, 0-1) vs ERA5-Land 0-1 cm (m3/m3); "
            "no son directamente comparables.",
            "Open-Meteo diario se agregó con el timezone de Argentina.",
        ],
    }
    rep = ensure_dir(cfg["paths"]["reports"])
    write_json(Path(rep) / "forecast_compat.json", out)
    return out


def main() -> int:
    args = parse_args("Adaptador de pronóstico")
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--check", action="store_true")
    known, _ = ap.parse_known_args()
    cfg = load_config(args.config)
    log = setup_logging("forecast_adapter", Path(cfg["paths"]["data"]) / "logs" /
                        "forecast_adapter.log", cfg["run"]["log_level"])
    if known.check:
        out = compatibility_check(cfg, log)
        log.info("Compatibilidad: %s", out["rows"])
        return 0
    provider = get_provider(cfg)
    df = provider.get(-31.42, -64.18, "2016-01-04", days=7)
    print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
