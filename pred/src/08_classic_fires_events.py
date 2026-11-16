"""Etapa 08 — derivación clásica de incendios y eventos desde hotspots predichos.

Reutiliza la lógica de `prep/src/04_fires.py` y `05_events.py` adaptada a
hotspots predichos en celdas de 1 km:
  - incendios: contacto de píxeles (radio sintético de 1 km) por día;
  - eventos: unión de incendios a <=5 días y <=2 km (buffer clásico).
No se usa como entidad de entrenamiento: es post-procesamiento.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ensure_dir, load_config, parse_args, read_json, setup_logging, write_json  # noqa: E402

TM = "+proj=tmerc +lat_0=-90 +lon_0=-63 +k=1 +x_0=500000 +y_0=0 +datum=WGS84 +units=m"
FIRE_R_M = 500.0 * np.sqrt(2.0)  # semidiagonal de una celda de 1 km
EARTH_KM_PER_DEG = 111.32


def _id(prefix: str, parts) -> str:
    h = hashlib.blake2b(digest_size=10)
    h.update("|".join(map(str, parts)).encode())
    return f"{prefix}-{h.hexdigest()}"


def project(lon, lat):
    tr = Transformer.from_crs("EPSG:4326", TM, always_xy=True)
    x, y = tr.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.asarray(x), np.asarray(y)


def derive_fires(hotspots: pd.DataFrame, cfg: dict, log=None) -> pd.DataFrame:
    """Agrupa hotspots predichos por día y contacto de píxeles."""
    if len(hotspots) == 0:
        return pd.DataFrame()
    hs = hotspots.copy()
    hs["date"] = pd.to_datetime(hs["date"]).dt.floor("D")
    x, y = project(hs["lon"].to_numpy(), hs["lat"].to_numpy())
    hs["x"], hs["y"] = x, y
    rows = []
    for day, g in hs.groupby("date", sort=True):
        g = g.reset_index(drop=True)
        if len(g) == 1:
            labels = np.array([0])
        else:
            tree = cKDTree(np.c_[g["x"], g["y"]])
            pairs = tree.query_pairs(r=2.0 * FIRE_R_M, output_type="ndarray")
            if len(pairs) == 0:
                labels = np.arange(len(g))
            else:
                n = len(g)
                data = np.ones(len(pairs), dtype=np.int8)
                mat = coo_matrix((data, (pairs[:, 0], pairs[:, 1])), shape=(n, n))
                _, labels = connected_components(mat, directed=False)
        for lab in np.unique(labels):
            m = labels == lab
            sub = g.loc[m]
            lat = float(sub["lat"].mean())
            lon = float(sub["lon"].mean())
            prob = float(sub["prob"].mean()) if "prob" in sub else 0.5
            rows.append({
                "incendio_id": _id("PINC", [str(day.date()), round(lon, 5), round(lat, 5),
                                            m.sum()]),
                "pass_bin": f"{day.date()}_D",
                "t_inicio": day + pd.Timedelta(hours=12),
                "t_fin": day + pd.Timedelta(hours=12),
                "n_hotspots": int(m.sum()),
                "area_pixeles_km2": float(m.sum()),  # 1 km² por celda
                "confidence": 100.0 * prob,
                "centroid_lon": lon,
                "centroid_lat": lat,
                "day": day,
            })
    fires = pd.DataFrame(rows)
    if log:
        log.info("Incendios clásicos: %d desde %d hotspots", len(fires), len(hs))
    return fires


def derive_events(fires: pd.DataFrame, cfg: dict, log=None) -> pd.DataFrame:
    """Une incendios a <=5 días y <=2 km (buffer clásico simplificado)."""
    if len(fires) == 0:
        return pd.DataFrame()
    f = fires.sort_values("t_inicio").reset_index(drop=True)
    n = len(f)
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    days = (f["day"] - f["day"].min()).dt.days.to_numpy()
    # Distancia aproximada en km (suficiente para el enlace).
    lat0 = np.deg2rad(f["centroid_lat"].mean())
    fx = f["centroid_lon"].to_numpy() * EARTH_KM_PER_DEG * np.cos(lat0)
    fy = f["centroid_lat"].to_numpy() * 110.57
    tree = cKDTree(np.c_[fx, fy])
    max_days = int(cfg["classic"]["event_link_window_days"])
    max_km = float(cfg["classic"]["event_buffer_km"]) + 1.0  # buffer + radio de celda
    for i in range(n):
        idx = tree.query_ball_point((fx[i], fy[i]), max_km)
        for j in idx:
            if j > i and abs(int(days[j]) - int(days[i])) <= max_days:
                union(i, int(j))
    roots = np.array([find(i) for i in range(n)])
    rows = []
    for root in np.unique(roots):
        m = roots == root
        sub = f.loc[m]
        rows.append({
            "evento_id": _id("PEVT", [str(sub["day"].min().date()),
                                      round(float(sub["centroid_lon"].mean()), 5),
                                      round(float(sub["centroid_lat"].mean()), 5)]),
            "inicio": sub["t_inicio"].min(),
            "fin": sub["t_fin"].max(),
            "n_incendios": int(m.sum()),
            "area_pixeles_km2": float(sub["area_pixeles_km2"].sum()),
            "confidence": float(sub["confidence"].mean()),
            "centroid_lon": float(sub["centroid_lon"].mean()),
            "centroid_lat": float(sub["centroid_lat"].mean()),
            "incendios": ",".join(sub["incendio_id"].tolist()),
        })
    events = pd.DataFrame(rows)
    if log:
        log.info("Eventos clásicos: %d desde %d incendios", len(events), len(fires))
    return events


def _match(pred: pd.DataFrame, real: pd.DataFrame, max_km: float,
           day_tol: int, pred_day: str, real_day: str,
           pred_lat="centroid_lat", pred_lon="centroid_lon",
           real_lat="centroid_lat", real_lon="centroid_lon") -> dict:
    if len(pred) == 0 or len(real) == 0:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0,
                "n_pred": int(len(pred)), "n_real": int(len(real)), "n_match": 0,
                "missed_rate": 1.0 if len(real) else 0.0}
    p = pred.copy(); r = real.copy()
    p[pred_day] = pd.to_datetime(p[pred_day]).dt.floor("D")
    r[real_day] = pd.to_datetime(r[real_day]).dt.floor("D")
    lat0 = np.deg2rad(float(p[pred_lat].mean()))
    px = p[pred_lon].to_numpy() * EARTH_KM_PER_DEG * np.cos(lat0)
    py = p[pred_lat].to_numpy() * 110.57
    rx = r[real_lon].to_numpy() * EARTH_KM_PER_DEG * np.cos(lat0)
    ry = r[real_lat].to_numpy() * 110.57
    rtree = cKDTree(np.c_[rx, ry])
    used = set()
    matched = 0
    for i, row in p.iterrows():
        idx = rtree.query_ball_point((px[i], py[i]), max_km)
        best = None
        for j in idx:
            if j in used:
                continue
            if abs((row[pred_day] - r.iloc[j][real_day]).days) <= day_tol:
                best = j
                break
        if best is not None:
            used.add(best)
            matched += 1
    prec = matched / max(len(p), 1)
    rec = matched / max(len(r), 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    return {"precision": float(prec), "recall": float(rec), "f1": float(f1),
            "n_pred": int(len(p)), "n_real": int(len(r)), "n_match": int(matched),
            "missed_rate": float(1.0 - rec)}


def compare_to_real(fires: pd.DataFrame, events: pd.DataFrame, cfg: dict,
                    t0: pd.Timestamp | None = None,
                    start: pd.Timestamp | str | None = None,
                    end: pd.Timestamp | str | None = None, log=None) -> dict:
    prep = Path(cfg["paths"]["prep_processed"])
    cor = read_json(Path(cfg["paths"]["static"]) / "departments.json")
    # No hay columna de departamento en los reales; filtramos por bbox/provincia
    # usando los centroides y la máscara provincial ya aplicada en la predicción.
    start = pd.Timestamp(start if start is not None else cfg["periods"]["val_start"])
    end = pd.Timestamp(end if end is not None else cfg["periods"]["val_end"]) + pd.Timedelta(days=1)
    real_f = pd.read_parquet(prep / "incendios.parquet",
                             columns=["incendio_id", "t_inicio", "t_fin",
                                      "centroid_lon", "centroid_lat",
                                      "area_pixeles_km2", "confidence"])
    real_f = real_f[(real_f["t_inicio"] >= start) & (real_f["t_inicio"] < end)]
    real_e = pd.read_parquet(prep / "eventos.parquet",
                             columns=["evento_id", "inicio", "fin",
                                      "centroid_lon", "centroid_lat",
                                      "area_pixeles_km2", "confidence", "n_incendios"])
    real_e = real_e[(real_e["inicio"] >= start) & (real_e["inicio"] < end)]
    # Recorte aproximado al bbox de Córdoba (los reales no traen departamento).
    def _bbox(df, lat="centroid_lat", lon="centroid_lon"):
        return df[(df[lon].between(-66.0, -61.5)) & (df[lat].between(-35.2, -29.3))]
    real_f = _bbox(real_f)
    real_e = _bbox(real_e)
    out = {
        "fires": _match(fires, real_f, 1.0, 1, "day", "t_inicio"),
        "events": _match(events, real_e, 2.0, 1, "inicio", "inicio"),
        "n_real_fires": int(len(real_f)),
        "n_real_events": int(len(real_e)),
    }
    # Continuación vs nuevo sobre eventos emparejados.
    if t0 is not None and len(events) and len(real_e):
        t0 = pd.Timestamp(t0)
        ev = events.copy()
        ev["inicio"] = pd.to_datetime(ev["inicio"]).dt.floor("D")
        matched = []
        r = real_e.copy()
        r["inicio"] = pd.to_datetime(r["inicio"]).dt.floor("D")
        r["fin"] = pd.to_datetime(r["fin"]).dt.floor("D")
        lat0 = np.deg2rad(float(ev["centroid_lat"].mean()))
        ex = ev["centroid_lon"].to_numpy() * EARTH_KM_PER_DEG * np.cos(lat0)
        ey = ev["centroid_lat"].to_numpy() * 110.57
        rtree = cKDTree(np.c_[r["centroid_lon"].to_numpy() * EARTH_KM_PER_DEG * np.cos(lat0),
                              r["centroid_lat"].to_numpy() * 110.57])
        n_continuacion = n_nuevo = n_sin = 0
        for i, row in ev.iterrows():
            idx = rtree.query_ball_point((ex[i], ey[i]), 2.0)
            # Un evento real "existe" el día d si inicio <= d <= fin.
            d = pd.Timestamp(row["inicio"])
            active = [k for k in idx
                      if r.iloc[k]["inicio"] <= d + pd.Timedelta(days=1)
                      and r.iloc[k]["fin"] >= d - pd.Timedelta(days=1)]
            if not active:
                n_sin += 1
                continue
            j = min(active, key=lambda k: abs((d - r.iloc[k]["inicio"]).days))
            # Pronóstico emitido ~7 días antes de la primera fecha predicha.
            t0_issue = d - pd.Timedelta(days=7)
            cont = bool(r.iloc[j]["inicio"] <= t0_issue)
            n_continuacion += int(cont)
            n_nuevo += int(not cont)
            matched.append({"pred_evento": row["evento_id"],
                            "real_evento": r.iloc[j]["evento_id"],
                            "real_inicio": r.iloc[j]["inicio"],
                            "real_fin": r.iloc[j]["fin"],
                            "t0_issue": t0_issue,
                            "continuacion": cont})
        df = pd.DataFrame(matched)
        out["link"] = {
            "n_pred_eventos": int(len(ev)),
            "n_matched": int(len(df)),
            "n_continuacion": int(n_continuacion),
            "n_nuevo": int(n_nuevo),
            "n_sin_evento_real": int(n_sin),
        }
        out["link_matches"] = df.to_dict(orient="records") if len(df) else []
    if log:
        log.info("Comparación: incendios %s", out["fires"])
        log.info("Comparación: eventos %s", out["events"])
    return out


def main() -> int:
    args = parse_args("Derivación clásica de incendios/eventos")
    cfg = load_config(args.config)
    data_dir = ensure_dir(cfg["paths"]["data"])
    rep = ensure_dir(cfg["paths"]["reports"])
    log = setup_logging("08_classic", data_dir / "logs" / "08_classic.log",
                        cfg["run"]["log_level"])
    hs_path = Path(args.config).parent / ".." / "data" / "reports" / "predicted_hotspots_val.parquet"
    hs_path = rep / "predicted_hotspots_val.parquet"
    if not hs_path.exists():
        log.error("Falta %s; correr 07_evaluate primero", hs_path)
        return 1
    hotspots = pd.read_parquet(hs_path)
    fires = derive_fires(hotspots, cfg, log)
    events = derive_events(fires, cfg, log)
    fires.to_parquet(rep / "predicted_fires.parquet", index=False)
    events.to_parquet(rep / "predicted_events.parquet", index=False)
    t0 = pd.Timestamp(cfg["periods"]["val_end"])
    comp = compare_to_real(fires, events, cfg, t0=t0, log=log)
    write_json(rep / "classic_metrics.json", comp)
    log.info("Escrito en %s", rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
