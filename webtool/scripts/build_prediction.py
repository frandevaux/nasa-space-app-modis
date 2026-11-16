"""
Builds the forecast consumed by the web tool: public/data/prediction/index.json.

Input: the operational prediction of the pred-hotspots branch (pred/PLAN.md, src/10_predict_latest.py),
first match wins:
  pred/predictions/latest_*/                    if the branch is checked out (newest folder)
  data/pred/                                    copy extracted with git show (see webtool/README.md)
with predicted_{hotspots,fires,events}.parquet and summary.json.

Output (one small JSON, column-oriented):
  model, t0, dates[]             forecast days (YYYY-MM-DD) and the model / weather settings
  coverage                       regions the model covers (today only Córdoba)
  hotspots {d, lat, lon, p, ev, fire}  d = index into dates, p = probability 0-100, ev / fire = index into
                                 events / fires (-1 = none)
  fires {id, d, ev, n, km2, polyKm2, conf, lat, lon, ring}   predicted fires with their OUTLINE
  events {id, start, end, nFires, km2, conf, lat, lon}
  counts {region: {fires: [...], hotspots: [...]}}   per forecast day, for AR, provinces and departments

Fire outlines: the prediction only exports fire centroids, so the fires are rebuilt here with the exact rule of
pred/src/08_classic_fires_events.py (same day, cells in contact within 2·r, r = 500·√2 m = half the diagonal of
a 1 km cell) and their outline is the union of the cell circles of radius r (as the historical fires, PLAN T16).
The fire id is recomputed with the same hash, so hotspot → fire → event links are exact.

Usage:
  pipeline/.venv/bin/python webtool/scripts/build_prediction.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import hashlib

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.geometry import Point
from shapely.ops import unary_union

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "webtool" / "public" / "data" / "prediction"
DEPARTMENTS = REPO / "data" / "boundaries" / "ign_departamento.geojson"
PROVINCE_NAMES = REPO / "webtool" / "public" / "data" / "regions.json"

# Same projection, cell radius and id hash as pred/src/08_classic_fires_events.py
TM = "+proj=tmerc +lat_0=-90 +lon_0=-63 +k=1 +x_0=500000 +y_0=0 +datum=WGS84 +units=m"
FIRE_R_M = 500.0 * np.sqrt(2.0)
SIMPLIFY_M = 40.0
TO_TM = Transformer.from_crs("EPSG:4326", TM, always_xy=True)
TO_LL = Transformer.from_crs(TM, "EPSG:4326", always_xy=True)


def pred_id(prefix: str, parts) -> str:
    h = hashlib.blake2b(digest_size=10)
    h.update("|".join(map(str, parts)).encode())
    return f"{prefix}-{h.hexdigest()}"


def rebuild_fires(hs: pd.DataFrame) -> pd.DataFrame:
    """Groups hotspots into fires exactly as stage 08 does, and adds each fire's outline."""
    hs["x"], hs["y"] = TO_TM.transform(hs["lon"].to_numpy(float), hs["lat"].to_numpy(float))
    hs["fire_id"] = ""
    rows = []
    for day, g in hs.groupby(pd.to_datetime(hs["date"]).dt.floor("D"), sort=True):
        idx = g.index.to_numpy()
        if len(g) == 1:
            labels = np.array([0])
        else:
            pairs = cKDTree(g[["x", "y"]].to_numpy()).query_pairs(r=2.0 * FIRE_R_M, output_type="ndarray")
            if len(pairs) == 0:
                labels = np.arange(len(g))
            else:
                mat = coo_matrix((np.ones(len(pairs), dtype=np.int8), (pairs[:, 0], pairs[:, 1])), shape=(len(g), len(g)))
                _, labels = connected_components(mat, directed=False)
        for lab in np.unique(labels):
            m = labels == lab
            sub = g.loc[idx[m]]
            fid = pred_id("PINC", [str(day.date()), round(float(sub["lon"].mean()), 5), round(float(sub["lat"].mean()), 5), int(m.sum())])
            hs.loc[idx[m], "fire_id"] = fid
            shape = unary_union([Point(x, y).buffer(FIRE_R_M, 16) for x, y in zip(sub["x"], sub["y"])])
            shape = shape.simplify(SIMPLIFY_M)
            if shape.geom_type == "MultiPolygon":  # touching circles always merge; keep the largest just in case
                shape = max(shape.geoms, key=lambda p: p.area)
            xs, ys = np.asarray(shape.exterior.coords).T
            lons, lats = TO_LL.transform(xs, ys)
            ring = [[round(float(lo), 5), round(float(la), 5)] for lo, la in zip(lons, lats)]
            rows.append({"incendio_id": fid, "ring": ring, "poly_km2": shape.area / 1e6})
    return pd.DataFrame(rows)


def find_prediction() -> Path:
    latest = sorted((REPO / "pred" / "predictions").glob("latest_*"))
    for d in [*reversed(latest), REPO / "data" / "pred"]:
        if (d / "predicted_hotspots.parquet").exists() and (d / "summary.json").exists():
            return d
    sys.exit("No prediction found (pred/predictions/latest_* or data/pred/).")


def stamp(s: pd.Series) -> list:
    return pd.to_datetime(s).dt.strftime("%Y-%m-%dT%H:%M").tolist()


def assign(df: pd.DataFrame, join: gpd.GeoDataFrame, lat: str, lon: str) -> pd.DataFrame:
    pts = gpd.GeoDataFrame(df[[lat, lon]].copy(), geometry=gpd.points_from_xy(df[lon], df[lat]), crs="EPSG:4326")
    res = gpd.sjoin(pts, join, how="left", predicate="within")
    res = res[~res.index.duplicated(keep="first")]
    return df.join(res[["department", "province"]])


def main():
    src = find_prediction()
    print(f"Reading prediction from {src.relative_to(REPO)}")
    summary = json.loads((src / "summary.json").read_text())
    dates = list(summary["dates"])
    hs = pd.read_parquet(src / "predicted_hotspots.parquet")
    fires = pd.read_parquet(src / "predicted_fires.parquet")
    events = pd.read_parquet(src / "predicted_events.parquet").sort_values("inicio").reset_index(drop=True)

    dept = gpd.read_file(DEPARTMENTS)[["in1", "geometry"]]
    dept["department"] = "d" + dept["in1"]
    dept["province"] = "p" + dept["in1"].str[:2]
    join = dept[["department", "province", "geometry"]]

    # fire → event
    fire_event = {}
    for j, ids in enumerate(events["incendios"]):
        for fid in str(ids).split(","):
            fire_event[fid.strip()] = j
    fires["ev"] = fires["incendio_id"].map(fire_event).fillna(-1).astype(int)
    fires["date"] = pd.to_datetime(fires["day"]).dt.strftime("%Y-%m-%d")

    # Rebuild the fires (same rule and ids as stage 08) to get exact memberships and outlines.
    shapes = rebuild_fires(hs)
    fires = fires.merge(shapes, on="incendio_id", how="left")
    missing = int(fires["ring"].isna().sum())
    if missing:
        sys.exit(f"{missing} predicted fires could not be rebuilt: the fire rule changed in pred/src/08?")
    fire_pos = {fid: i for i, fid in enumerate(fires["incendio_id"])}
    hs["fire"] = hs["fire_id"].map(fire_pos).fillna(-1).astype(int)
    hs["ev"] = [int(fires["ev"].iat[i]) if i >= 0 else -1 for i in hs["fire"]]

    # The model output repeats some cells on the same day (same row / col, different score: overlapping
    # patches). The rows above are kept as they are so fire ids match stage 08; from here on each cell counts
    # once (highest score), and a fire's size is its number of distinct cells.
    raw = len(hs)
    hs = hs.sort_values("prob", ascending=False).drop_duplicates(["date", "row", "col"]).sort_index()
    cells = hs.groupby("fire").size()
    fires["cells"] = [int(cells.get(i, 0)) for i in range(len(fires))]
    print(f"  {raw - len(hs)} repeated cells dropped ({raw} rows → {len(hs)} distinct cells per day)")

    # per-region daily counts (fires by centroid, hotspots by position)
    hs = assign(hs, join, "lat", "lon")
    fires = assign(fires, join, "centroid_lat", "centroid_lon")
    day_of = {d: i for i, d in enumerate(dates)}
    counts: dict[str, dict[str, list[int]]] = {}

    def add(region, kind, date):
        if not isinstance(region, str) or date not in day_of:
            return
        c = counts.setdefault(region, {"fires": [0] * len(dates), "hotspots": [0] * len(dates)})
        c[kind][day_of[date]] += 1

    for _, r in fires.iterrows():
        for reg in ("AR", r["province"], r["department"]):
            add(reg, "fires", r["date"])
    for _, r in hs.iterrows():
        for reg in ("AR", r["province"], r["department"]):
            add(reg, "hotspots", r["date"])

    names = {r["id"]: r["name"] for r in json.loads(PROVINCE_NAMES.read_text())} if PROVINCE_NAMES.exists() else {}
    covered = sorted({p for p in hs["province"].dropna()})
    out = {
        "model": f"Red neuronal (época {summary.get('model_epoch')}), umbral {summary.get('threshold')}, clima {summary.get('forecast')}",
        "t0": summary["t0"],
        "dates": dates,
        "coverage": {"regions": covered, "name": ", ".join(names.get(p, p) for p in covered)},
        "hotspots": {
            "d": [day_of[d] for d in hs["date"]],
            "lat": hs["lat"].round(5).tolist(),
            "lon": hs["lon"].round(5).tolist(),
            "p": (hs["prob"] * 100).round(1).tolist(),
            "ev": hs["ev"].astype(int).tolist(),
            "fire": hs["fire"].astype(int).tolist(),
        },
        "fires": {
            "id": fires["incendio_id"].str.replace("PINC-", "", regex=False).str[:12].tolist(),
            "d": [day_of.get(d, -1) for d in fires["date"]],
            "ev": fires["ev"].astype(int).tolist(),
            "n": fires["cells"].astype(int).tolist(),
            "km2": fires["cells"].astype(float).tolist(),  # 1 km² per distinct cell
            "polyKm2": fires["poly_km2"].round(2).tolist(),
            "conf": fires["confidence"].round(1).tolist(),
            "lat": fires["centroid_lat"].round(5).tolist(),
            "lon": fires["centroid_lon"].round(5).tolist(),
            "ring": fires["ring"].tolist(),
        },
        "events": {
            "id": events["evento_id"].str.replace("PEVT-", "", regex=False).str[:12].str.lower().tolist(),
            "start": stamp(events["inicio"]),
            "end": stamp(events["fin"]),
            "nFires": events["n_incendios"].astype(int).tolist(),
            "km2": events["area_pixeles_km2"].round(2).tolist(),
            "conf": events["confidence"].round(1).tolist(),
            "lat": events["centroid_lat"].round(5).tolist(),
            "lon": events["centroid_lon"].round(5).tolist(),
        },
        "counts": counts,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "index.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    linked = int((hs["fire"] >= 0).sum())
    print(f"  {len(dates)} days ({dates[0]} → {dates[-1]}), {len(hs)} hotspots ({linked} in a rebuilt fire), "
          f"{len(fires)} fires, {len(events)} events, coverage {out['coverage']['name']}")
    print(f"  → {(OUT / 'index.json').relative_to(REPO)} ({(OUT / 'index.json').stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
