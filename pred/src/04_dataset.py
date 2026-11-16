"""Dataset PyTorch de parches de hotspots.

Cada muestra es un hotspot ancla. El patch es 32x32 celdas de 1 km; la
historia es de 14 días y el horizonte de 7. No se usan incendios/eventos.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy.ndimage import distance_transform_edt, gaussian_filter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (crop_pad, load_config, read_json, seed_everything)  # noqa: E402


def derived_weather(raw: np.ndarray) -> dict[str, np.ndarray]:
    """raw: (..., 51, 6) -> dict de derivados con la misma forma temporal."""
    t2m = raw[..., 0]
    rh = raw[..., 2]
    precip = raw[..., 3]
    es = 0.6108 * np.exp(17.27 * t2m / (t2m + 237.3))
    vpd = es * (1.0 - rh / 100.0)
    wet = precip >= 1.0
    days_since = np.zeros_like(precip, dtype=np.float32)
    count = np.zeros(precip.shape[:-1], dtype=np.float32)
    n_days = precip.shape[-1]
    for t in range(n_days):
        count = np.where(wet[..., t], 0.0, np.minimum(count + 1.0, 30.0))
        days_since[..., t] = count
    p7 = np.zeros_like(precip, dtype=np.float32)
    p30 = np.zeros_like(precip, dtype=np.float32)
    for t in range(n_days):
        p7[..., t] = np.nansum(precip[..., max(0, t - 6):t + 1], axis=-1)
        p30[..., t] = np.nansum(precip[..., max(0, t - 29):t + 1], axis=-1)
    return {"vpd": vpd, "days_since_rain": days_since,
            "precip_7d": p7, "precip_30d": p30}


def shift2d(arr: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """Desplaza las dos últimas dimensiones, rellenando con ceros."""
    out = np.zeros_like(arr)
    h, w = arr.shape[-2], arr.shape[-1]
    if abs(dy) >= h or abs(dx) >= w:
        return out
    src_y0, src_y1 = max(0, -dy), min(h, h - dy)
    dst_y0, dst_y1 = max(0, dy), min(h, h + dy)
    src_x0, src_x1 = max(0, -dx), min(w, w - dx)
    dst_x0, dst_x1 = max(0, dx), min(w, w + dx)
    out[..., dst_y0:dst_y1, dst_x0:dst_x1] = arr[..., src_y0:src_y1, src_x0:src_x1]
    return out


def load_oni(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=r"\s+", engine="python")
    df.columns = [c.strip() for c in df.columns]
    ends = {
        "DJF": (2, 28), "JFM": (3, 31), "FMA": (4, 30), "MAM": (5, 31),
        "AMJ": (6, 30), "MJJ": (7, 31), "JJA": (8, 31), "JAS": (9, 30),
        "ASO": (10, 31), "SON": (11, 30), "OND": (12, 31), "NDJ": (1, 31),
    }
    rows = []
    for r in df.itertuples(index=False):
        seas = str(getattr(r, "SEAS")).strip().upper()
        yr = int(getattr(r, "YR"))
        if seas not in ends:
            continue
        m, d = ends[seas]
        year = yr + 1 if seas == "NDJ" else yr
        rows.append((pd.Timestamp(year=year, month=m, day=d), float(getattr(r, "ANOM"))))
    return pd.DataFrame(rows, columns=["end", "anom"]).sort_values("end").reset_index(drop=True)


def oni_prev(t0: pd.Timestamp, oni: pd.DataFrame) -> float:
    x = oni[oni["end"] <= t0]
    return float(x["anom"].iloc[-1]) if len(x) else 0.0


class FireHotspotDataset(torch.utils.data.Dataset):
    def __init__(self, cfg: dict, split: str, smoke: bool = False):
        self.cfg = cfg
        self.split = split
        self.patch = int(cfg["grid"]["patch_cells"])
        self.half = self.patch // 2
        self.hist = int(cfg["grid"]["history_days"])
        self.horizon = int(cfg["grid"]["horizon_days"])
        self.pad = int(cfg["grid"]["weather_pad_days"])
        self.t0_idx = self.pad + self.hist - 1  # índice 43 en weather (-43..7)
        self.root = Path(cfg["paths"]["hotspots"])
        self.index = pd.read_parquet(self.root / "index.parquet")
        self.index = self.index[self.index["split"] == split].reset_index(drop=True)
        if smoke:
            self.index = self.index.head(64).reset_index(drop=True)
        self.long = pd.read_parquet(
            self.root / "hotspots_long.parquet",
            columns=["anchor_idx", "day_offset", "dx", "dy", "frp",
                     "confidence", "sensor_code", "daynight_code"],
        )
        if not self.long["anchor_idx"].is_monotonic_increasing:
            self.long = self.long.sort_values("anchor_idx").reset_index(drop=True)
        self.weather = np.load(self.root / "weather.npy")
        # Descarta anclas sin clima completo de historia/futuro (típicamente
        # los últimos días de test, fuera de la cobertura POWER).
        a_idx = self.index["anchor_idx"].to_numpy()
        hi_ok = np.isfinite(
            self.weather[a_idx, self.t0_idx - self.hist + 1:self.t0_idx + 1]
        ).all(axis=(1, 2))
        fu_ok = np.isfinite(
            self.weather[a_idx, self.t0_idx + 1:self.t0_idx + self.horizon + 1]
        ).all(axis=(1, 2))
        valid = hi_ok & fu_ok
        if not valid.all():
            self.index = self.index.loc[valid].reset_index(drop=True)
        self.stats = read_json(self.root / "stats.json")
        self.channels = read_json(self.root / "channels.json")
        self.static_dir = Path(cfg["paths"]["static"])
        self.mask = np.load(self.static_dir / "cordoba_mask.npy")
        self.dept = np.load(self.static_dir / "dept_id.npy")
        self.ap = np.load(self.static_dir / "ap.npy")
        self.clim = np.load(self.static_dir / "fire_climatology.npy")
        self.landcover = {}
        for f in self.static_dir.glob("landcover_*.npy"):
            try:
                year = int(f.stem.split("_")[-1])
            except ValueError:
                continue
            self.landcover[year] = np.load(f)
        self.oni = load_oni(cfg["paths"]["oni"])
        self.augment = bool(cfg["model"].get("augment", True)) and split == "train"
        self.rng = np.random.default_rng(int(cfg["project"]["seed"]) + (0 if split == "train" else 1))
        seed_everything(int(cfg["project"]["seed"]))

        self.raw_names = list(cfg["weather"]["variables"])
        # Estadísticas de canales meteorológicos.
        self.wstats = self.stats
        self._precompute_vectors()

    def _precompute_vectors(self) -> None:
        idx = self.index
        self.vec = np.zeros((len(idx), 17), dtype=np.float32)
        sat_map = {"Terra": 0, "Aqua": 1, "SNPP": 2, "N": 2,
                   "NOAA20": 3, "N20": 3, "NOAA21": 4, "N21": 4}
        for i, r in enumerate(idx.itertuples(index=False)):
            hour = float(getattr(r, "hora_local")) if pd.notna(getattr(r, "hora_local")) else 12.0
            doy = float(getattr(r, "doy")) if pd.notna(getattr(r, "doy")) else 1.0
            dept_id = int(self.dept[int(r.row), int(r.col)])
            oni = oni_prev(pd.Timestamp(r.t0), self.oni)
            self.vec[i] = [
                np.log1p(max(float(r.frp), 0.0)) / 5.0,
                float(r.confidence_incendio) / 100.0,
                1.0 if str(r.sensor) == "VIIRS" else 0.0,
                sat_map.get(str(r.satellite), 0) / 4.0,
                1.0 if str(r.daynight) == "N" else 0.0,
                float(r.scan_km) / 5.0,
                float(r.track_km) / 5.0,
                float(r.bright_main) / 350.0,
                float(r.bright_aux) / 350.0,
                np.sin(2 * np.pi * hour / 24.0),
                np.cos(2 * np.pi * hour / 24.0),
                np.sin(2 * np.pi * doy / 366.0),
                np.cos(2 * np.pi * doy / 366.0),
                0.0, 0.0,  # patch count/frp at t0 (se llenan en getitem)
                dept_id / 26.0,
                oni / 2.0,
            ]

    def __len__(self) -> int:
        return len(self.index)

    def _z(self, name: str, arr: np.ndarray) -> np.ndarray:
        s = self.wstats[name]
        return np.clip((arr - s["mean"]) / (s["std"] + 1e-6), -5.0, 5.0)

    def _static_landcover(self, year: int) -> np.ndarray:
        candidates = sorted(self.landcover)
        if not candidates:
            raise RuntimeError("No hay landcover estático")
        use = year - 1
        if use not in self.landcover:
            use = min(candidates, key=lambda y: abs(y - use))
        return self.landcover[use]

    def __getitem__(self, i: int) -> dict[str, torch.Tensor]:
        r = self.index.iloc[i]
        anchor = int(r["anchor_idx"])
        start = int(r["long_start"])
        count = int(r["long_count"])
        rows = self.long.iloc[start:start + count]

        P = self.patch
        H = self.hist
        F = self.horizon
        cnt = np.zeros((H, P, P), dtype=np.float32)
        frp_sum = np.zeros((H, P, P), dtype=np.float32)
        frp_max = np.zeros((H, P, P), dtype=np.float32)
        conf_sum = np.zeros((H, P, P), dtype=np.float32)
        conf_max = np.zeros((H, P, P), dtype=np.float32)
        n_total = np.zeros((H, P, P), dtype=np.float32)
        n_modis = np.zeros((H, P, P), dtype=np.float32)
        n_night = np.zeros((H, P, P), dtype=np.float32)
        y = np.zeros((F, P, P), dtype=np.float32)
        y_count = np.zeros((F, P, P), dtype=np.float32)

        off = rows["day_offset"].to_numpy(np.int16)
        dx = rows["dx"].to_numpy(np.int16)
        dy = rows["dy"].to_numpy(np.int16)
        frp = rows["frp"].to_numpy(np.float32)
        conf = rows["confidence"].to_numpy(np.float32)
        sensor = rows["sensor_code"].to_numpy(np.int8)
        dn = rows["daynight_code"].to_numpy(np.int8)

        hist_m = (off >= -H) & (off <= 0)
        if hist_m.any():
            d = off[hist_m] + H - 1
            rr = dy[hist_m] + self.half
            cc = dx[hist_m] + self.half
            np.add.at(cnt, (d, rr, cc), 1.0)
            np.add.at(frp_sum, (d, rr, cc), frp[hist_m])
            np.maximum.at(frp_max, (d, rr, cc), frp[hist_m])
            np.add.at(conf_sum, (d, rr, cc), conf[hist_m])
            np.maximum.at(conf_max, (d, rr, cc), conf[hist_m])
            np.add.at(n_total, (d, rr, cc), 1.0)
            np.add.at(n_modis, (d, rr, cc), (sensor[hist_m] == 0).astype(np.float32))
            np.add.at(n_night, (d, rr, cc), (dn[hist_m] == 1).astype(np.float32))

        fut_m = (off >= 1) & (off <= F)
        if fut_m.any():
            d = off[fut_m] - 1
            rr = dy[fut_m] + self.half
            cc = dx[fut_m] + self.half
            y[d, rr, cc] = 1.0
            np.add.at(y_count, (d, rr, cc), 1.0)

        presence = (cnt > 0).astype(np.float32)
        density1 = gaussian_filter(presence, sigma=(0, 1, 1))
        density2 = gaussian_filter(presence, sigma=(0, 2, 2))
        denom = np.maximum(n_total, 1.0)

        # Meteorología: historia -13..0 y futuro 1..7.
        raw = self.weather[anchor]
        der = derived_weather(raw[None, ...])
        hi = slice(self.t0_idx - H + 1, self.t0_idx + 1)
        fi = slice(self.t0_idx + 1, self.t0_idx + F + 1)

        x_hist = np.zeros((H, len(self.channels["hist"]), P, P), dtype=np.float32)
        x_hist[:, 0] = np.clip(cnt / 10.0, 0, 1)
        x_hist[:, 1] = presence
        x_hist[:, 2] = np.clip(density1 / 10.0, 0, 1)
        x_hist[:, 3] = np.clip(density2 / 10.0, 0, 1)
        x_hist[:, 4] = np.log1p(frp_sum) / 5.0
        x_hist[:, 5] = np.log1p(frp_max) / 5.0
        x_hist[:, 6] = conf_sum / denom / 100.0
        x_hist[:, 7] = conf_max / 100.0
        # known_mask: hotspots del día t0 (último frame de historia)
        x_hist[:, 8] = np.broadcast_to(presence[-1][None, :, :], (H, P, P))
        x_hist[:, 9] = n_modis / denom
        x_hist[:, 10] = n_night / denom
        # Canales meteorológicos 11..19 (9 canales): se llenan por día.
        w_hist = {
            "t2m_max": self._z("T2M_MAX", raw[hi, 1]),
            "rh2m": self._z("RH2M", raw[hi, 2]),
            "precip": self._z("PRECTOTCORR", raw[hi, 3]),
            "ws10m_max": self._z("WS10M_MAX", raw[hi, 4]),
            "gwettop": self._z("GWETTOP", raw[hi, 5]),
            "vpd": self._z("vpd", der["vpd"][0, hi]),
            "days_since_rain": self._z("days_since_rain", der["days_since_rain"][0, hi]),
            "precip_7d": self._z("precip_7d", der["precip_7d"][0, hi]),
            "precip_30d": self._z("precip_30d", der["precip_30d"][0, hi]),
        }
        for k, name in enumerate(["t2m_max", "rh2m", "precip", "ws10m_max",
                                  "gwettop", "vpd", "days_since_rain",
                                  "precip_7d", "precip_30d"]):
            x_hist[:, 11 + k] = w_hist[name][:, None, None]

        x_fut = np.zeros((F, len(self.channels["future"]), P, P), dtype=np.float32)
        w_fut = {
            "t2m_max": self._z("T2M_MAX", raw[fi, 1]),
            "rh2m": self._z("RH2M", raw[fi, 2]),
            "precip": self._z("PRECTOTCORR", raw[fi, 3]),
            "ws10m_max": self._z("WS10M_MAX", raw[fi, 4]),
            "gwettop": self._z("GWETTOP", raw[fi, 5]),
            "vpd": self._z("vpd", der["vpd"][0, fi]),
            "days_since_rain": self._z("days_since_rain", der["days_since_rain"][0, fi]),
        }
        for k, name in enumerate(self.channels["future"]):
            x_fut[:, k] = w_fut[name][:, None, None]

        # Estáticos.
        row, col = int(r["row"]), int(r["col"])
        lc = self._static_landcover(int(pd.Timestamp(r["t0"]).year))
        lc_p = crop_pad(lc, row, col, P, fill=255)
        groups = [
            np.isin(lc_p, [1, 2, 3, 4, 5]),
            np.isin(lc_p, [6, 7]),
            np.isin(lc_p, [8, 9, 10]),
            np.isin(lc_p, [11, 12, 14]),
            ~np.isin(lc_p, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14]),
        ]
        mask_p = crop_pad(self.mask, row, col, P).astype(np.float32)
        dept_p = crop_pad(self.dept, row, col, P).astype(np.float32) / 26.0
        ap_p = crop_pad(self.ap, row, col, P).astype(np.float32)
        month = int(pd.Timestamp(r["t0"]).month) - 1
        clim_p = crop_pad(self.clim[month], row, col, P).astype(np.float32)
        yy, xx = np.mgrid[0:P, 0:P]
        dist_center = np.sqrt((yy - (P - 1) / 2.0) ** 2 +
                              (xx - (P - 1) / 2.0) ** 2) / (P / 2.0)
        known_t0 = presence[-1] if len(presence) else np.zeros((P, P), np.float32)
        if known_t0.any():
            dist_known = distance_transform_edt(known_t0 < 0.5) / (P / 2.0)
        else:
            dist_known = np.ones((P, P), dtype=np.float32)
        days_since_hs = np.full((P, P), float(H), dtype=np.float32)
        for d in range(H):
            days_since_hs[presence[d] > 0] = float(H - 1 - d)
        days_since_hs /= float(H)

        x_static = np.stack([
            mask_p, dept_p,
            groups[0].astype(np.float32), groups[1].astype(np.float32),
            groups[2].astype(np.float32), groups[3].astype(np.float32),
            groups[4].astype(np.float32),
            ap_p, clim_p, dist_center.astype(np.float32),
            dist_known.astype(np.float32), days_since_hs,
        ], axis=0).astype(np.float32)

        v = self.vec[i].copy()
        # patch count/frp en t0
        v[13] = np.clip(cnt[-1].sum() / 50.0, 0, 10)
        v[14] = np.log1p(frp_sum[-1].sum()) / 10.0
        v = np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)

        if self.augment:
            k = int(self.rng.integers(0, 4))
            if k:
                x_hist = np.rot90(x_hist, k, axes=(2, 3))
                x_fut = np.rot90(x_fut, k, axes=(2, 3))
                x_static = np.rot90(x_static, k, axes=(1, 2))
                y = np.rot90(y, k, axes=(1, 2))
                y_count = np.rot90(y_count, k, axes=(1, 2))
                mask_p = np.rot90(mask_p, k)
            if bool(self.cfg["model"].get("flips", True)):
                if bool(self.rng.integers(0, 2)):
                    x_hist = x_hist[..., ::-1, :]
                    x_fut = x_fut[..., ::-1, :]
                    x_static = x_static[..., ::-1, :]
                    y = y[..., ::-1, :]
                    y_count = y_count[..., ::-1, :]
                    mask_p = mask_p[::-1, :]
                if bool(self.rng.integers(0, 2)):
                    x_hist = x_hist[..., :, ::-1]
                    x_fut = x_fut[..., :, ::-1]
                    x_static = x_static[..., :, ::-1]
                    y = y[..., :, ::-1]
                    y_count = y_count[..., :, ::-1]
                    mask_p = mask_p[:, ::-1]
            tr = int(self.cfg["model"].get("translate_cells", 0))
            if tr > 0:
                dy = int(self.rng.integers(-tr, tr + 1))
                dx = int(self.rng.integers(-tr, tr + 1))
                if dy or dx:
                    x_hist = shift2d(x_hist, dy, dx)
                    x_fut = shift2d(x_fut, dy, dx)
                    x_static = shift2d(x_static, dy, dx)
                    y = shift2d(y, dy, dx)
                    y_count = shift2d(y_count, dy, dx)
                    mask_p = shift2d(mask_p, dy, dx)

        return {
            "x_hist": torch.from_numpy(np.ascontiguousarray(x_hist)),
            "x_fut": torch.from_numpy(np.ascontiguousarray(x_fut)),
            "x_static": torch.from_numpy(np.ascontiguousarray(x_static)),
            "v": torch.from_numpy(np.ascontiguousarray(v.astype(np.float32))),
            "y": torch.from_numpy(np.ascontiguousarray(y)),
            "y_count": torch.from_numpy(np.ascontiguousarray(y_count)),
            "mask": torch.from_numpy(np.ascontiguousarray(mask_p)),
            "anchor_idx": torch.tensor(anchor, dtype=torch.long),
        }


def build_datasets(cfg: dict, smoke: bool = False):
    train = FireHotspotDataset(cfg, "train", smoke=smoke)
    val = FireHotspotDataset(cfg, "val", smoke=smoke)
    return train, val


if __name__ == "__main__":
    cfg = load_config("config/params.yaml")
    ds = FireHotspotDataset(cfg, "train")
    print("len", len(ds))
    s = ds[0]
    for k, v in s.items():
        print(k, tuple(v.shape), v.dtype)
    print("y sum", float(s["y"].sum()), "pos rate", float(s["y"].mean()))
