"""
Builds the static data consumed by the web tool (webtool/public/data/).

Inputs (from the repo):
  data/processed/detections_raw.parquet      raw FIRMS hotspots (MODIS + VIIRS, 2000-11 → 2026-11)
  data/boundaries/ign_provincia.geojson      IGN boundaries
  data/boundaries/ign_departamento.geojson
  Pipeline outputs (branch prep-firms, PLAN.md §4), first match wins:
    prep/data/processed/{hotspots,incendios,eventos}.parquet   full run
    data/prep/{hotspots,incendios,eventos}.parquet             full run copied here
    data/prep/fuego*.gpkg                                      GeoPackage (e.g. the 2025 smoke run)
  Days covered by the pipeline use its hotspots, fires (incendios) and events (eventos);
  the remaining days fall back to the raw detections with the provisional rules below.

Outputs:
  public/data/meta.json                      date range, harmonization factor, last data date
  public/data/geo/provinces.json             simplified boundaries (GeoJSON)
  public/data/geo/departments.json
  public/data/regions.json                   search index (country, provinces, departments)
  public/data/series/<region>.json           daily series per region (active days only)
  public/data/fires/<YYYY-MM>.json           fires (incendios) that started in the month: attributes, simplified
                                             polygon (delta-encoded) and the events (eventos) they belong to
  public/data/hotspots/<YYYY-MM>.json        monthly hotspots, column-oriented (alternative map view)

Harmonization (all days):
  - Metric = burning pixel area on the VIIRS scale (see below).
  - Pipeline days: per-hotspot confidence = confidence of its fire (PLAN §4.8).

PROVISIONAL rules for days NOT covered by the pipeline:
  - Vegetation only: type == 0; NRT rows (no type) are kept as inferred (PLAN T6/T20, without the 365-day filter).
  - Metric = burning pixel area (Σ scan·track, km²), not counts (PLAN §4.8 item 5) — same on pipeline days.
  - VIIRS scale (PLAN T8): from 2012-01-20 the VIIRS area is used; before that, MODIS area × k,
    with k = Σ VIIRS area / Σ MODIS area over the overlap period (2012-01-20 → 2025-12-31).
  - Per-hotspot confidence = p(class) · w_sensor, with the values of PLAN §4.8 (no fire grouping).

Usage:
  pipeline/.venv/bin/python webtool/scripts/build_data.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "webtool" / "public" / "data"
DETECTIONS = REPO / "data" / "processed" / "detections_raw.parquet"
PROVINCES = REPO / "data" / "boundaries" / "ign_provincia.geojson"
DEPARTMENTS = REPO / "data" / "boundaries" / "ign_departamento.geojson"
PIPELINE_PARQUET_DIRS = [REPO / "prep" / "data" / "processed", REPO / "data" / "prep"]
PIPELINE_GPKG_DIR = REPO / "data" / "prep"

FIRE_SIMPLIFY_DEG = 0.0005   # ~50 m: fire polygons for the web
COORD_SCALE = 10_000         # 1e-4 degrees ≈ 11 m

START = pd.Timestamp("2000-11-01")
VIIRS_START = pd.Timestamp("2012-01-20")
OVERLAP_END = pd.Timestamp("2025-12-31")

# PLAN §4.8
P_CLASS = {"l": 0.15, "n": 0.55, "h": 0.90}
W_SENSOR = {"MODIS": 0.80, "VIIRS": 1.00}

SIMPLIFY_PROVINCE = 0.01     # degrees (~1 km), for drawing
SIMPLIFY_DEPARTMENT = 0.004  # degrees (~400 m), for drawing
SIMPLIFY_JOIN = 0.0005       # degrees (~50 m), for assigning hotspots


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)  # fail loudly on NaN


def round_coords(geom_json, nd=4):
    def r(c):
        if isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]
    geom_json["coordinates"] = r(geom_json["coordinates"])
    return geom_json


# ---------------------------------------------------------------- boundaries
def build_boundaries():
    log("Reading IGN boundaries…")
    prov = gpd.read_file(PROVINCES)[["in1", "nam", "geometry"]].rename(columns={"in1": "id", "nam": "name"})
    dept = gpd.read_file(DEPARTMENTS)[["in1", "nam", "geometry"]].rename(columns={"in1": "id", "nam": "name"})
    dept["province"] = dept["id"].str[:2]
    prov_names = dict(zip(prov["id"], prov["name"]))
    dept["province_name"] = dept["province"].map(prov_names)
    # Prefixes keep province and department ids apart.
    prov["id"] = "p" + prov["id"]
    dept["id"] = "d" + dept["id"]
    dept["province"] = "p" + dept["province"]

    join = dept[["id", "province", "geometry"]].copy()
    join["geometry"] = join.geometry.simplify(SIMPLIFY_JOIN, preserve_topology=True)

    log("Simplifying for the web…")
    prov_s = prov.copy()
    prov_s["geometry"] = prov_s.geometry.simplify(SIMPLIFY_PROVINCE, preserve_topology=True)
    dept_s = dept.copy()
    dept_s["geometry"] = dept_s.geometry.simplify(SIMPLIFY_DEPARTMENT, preserve_topology=True)
    for name, g, cols in (("provinces", prov_s, ["id", "name"]), ("departments", dept_s, ["id", "name", "province"])):
        fc = json.loads(g[cols + ["geometry"]].to_json(drop_id=True))
        for f in fc["features"]:
            round_coords(f["geometry"])
        write_json(OUT / "geo" / f"{name}.json", fc)

    regions = [{"id": "AR", "kind": "country", "name": "Argentina", "subtitle": "País completo",
                "bbox": [-73.6, -55.1, -53.6, -21.8], "children": int(len(prov))}]
    for _, r in prov.iterrows():
        b = r.geometry.bounds
        if r["id"] == "p94":  # Tierra del Fuego: leave Antarctica out of the bbox
            b = (max(b[0], -74.0), -55.2, min(b[2], -63.0), b[3])
        regions.append({"id": r["id"], "kind": "province", "name": r["name"], "subtitle": "Provincia · Argentina",
                        "bbox": [round(x, 3) for x in b],
                        "children": int((dept["province"] == r["id"]).sum())})
    for _, r in dept.iterrows():
        regions.append({"id": r["id"], "kind": "department", "name": r["name"],
                        "subtitle": f"Departamento · {r['province_name']}", "province": r["province"],
                        "bbox": [round(x, 3) for x in r.geometry.bounds]})
    return join, regions


# ---------------------------------------------------------------- hotspots
def raw_date_range() -> tuple:
    r = duckdb.sql(f"select min(acq_date), max(acq_date) from '{DETECTIONS}'").fetchall()[0]
    return pd.Timestamp(r[0]), pd.Timestamp(r[1])


def load_raw_hotspots(outside: tuple | None) -> pd.DataFrame:
    """Raw detections, only for the days the pipeline does not cover (`outside` = covered range to skip)."""
    log("Reading raw hotspots (type 0 + NRT) for days not covered by the pipeline…")
    where = ""
    if outside is not None:
        where = f"and (acq_date < DATE '{outside[0].date()}' or acq_date > DATE '{outside[1].date()}')"
    q = f"""
    select latitude as lat, longitude as lon, scan, track, acq_date, acq_time, satellite,
           instrument, confidence, is_nrt
    from '{DETECTIONS}'
    where (type = 0 or (is_nrt and type is null)) {where}
    """
    df = duckdb.sql(q).df()
    log(f"  {len(df):,} rows")
    if df.empty:
        return pd.DataFrame(columns=["lat", "lon", "scan", "track", "acq_date", "acq_time", "sensor", "p", "incendio_id", "evento_id"])
    # Dedup (PLAN §4.2): key (satellite, lat, lon, date, time); archive/SP wins over NRT.
    df["acq_time"] = df["acq_time"].astype(str).str.zfill(4)
    df = df.sort_values("is_nrt").drop_duplicates(["satellite", "lat", "lon", "acq_date", "acq_time"], keep="first")
    df["acq_date"] = pd.to_datetime(df["acq_date"])
    df["sensor"] = np.where(df["instrument"] == "MODIS", "MODIS", "VIIRS")
    # Common l/n/h class (PLAN §4.4, intermediate value)
    conf_num = pd.to_numeric(df["confidence"], errors="coerce")
    modis_class = np.select([conf_num < 30, conf_num < 80], ["l", "n"], "h")
    cls = np.where(df["sensor"] == "MODIS", modis_class, df["confidence"].str.lower())
    p = pd.Series(cls).map(P_CLASS).fillna(0.15).to_numpy()
    w = np.where(df["sensor"] == "MODIS", W_SENSOR["MODIS"], W_SENSOR["VIIRS"])
    df["p"] = np.round(100 * p * w).astype(np.int16)
    df["incendio_id"] = None
    df["evento_id"] = None
    return df[["lat", "lon", "scan", "track", "acq_date", "acq_time", "sensor", "p", "incendio_id", "evento_id"]].reset_index(drop=True)


def add_pixel_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df["area"] = df["scan"].astype(float) * df["track"].astype(float)  # nominal pixel km²
    df["r_m"] = np.round(500 * np.sqrt(df["scan"].astype(float) ** 2 + df["track"].astype(float) ** 2)).astype(np.int32)  # half-diagonal (PLAN T11)
    return df


# ---------------------------------------------------------------- pipeline outputs
HS_COLS = ["latitude", "longitude", "scan_km", "track_km", "scan", "track", "ts_utc", "sensor",
           "instrument", "incendio_id", "evento_id", "confidence_incendio"]
FIRE_COLS = ["incendio_id", "t_inicio", "t_fin", "n_hotspots", "n_hotspots_modis", "n_hotspots_viirs",
             "satelites_presentes", "area_pixeles_km2", "area_poligono_km2", "confidence", "evento_id",
             "en_area_protegida", "ap_nombres", "es_bosque", "centroid_lon", "centroid_lat"]
EVENT_COLS = ["evento_id", "inicio", "fin", "duracion_dias", "n_incendios", "area_pixeles_km2",
              "area_poligono_km2", "en_area_protegida", "es_bosque", "buffer_km", "confidence"]


def _read_parquet_cols(path: Path, wanted: list[str]) -> pd.DataFrame:
    import pyarrow.parquet as pq
    have = set(pq.read_schema(path).names)
    return pd.read_parquet(path, columns=[c for c in wanted if c in have])


def find_pipeline():
    """('parquet', dir) or ('gpkg', path) or None."""
    for d in PIPELINE_PARQUET_DIRS:
        if all((d / f"{n}.parquet").exists() for n in ("hotspots", "incendios", "eventos")):
            return "parquet", d
    gpkgs = sorted(PIPELINE_GPKG_DIR.glob("fuego*.gpkg")) if PIPELINE_GPKG_DIR.exists() else []
    return ("gpkg", gpkgs[-1]) if gpkgs else None


def load_pipeline(found):
    kind, where = found
    if kind == "parquet":
        log(f"Reading pipeline parquet from {where.relative_to(REPO)}…")
        hs = _read_parquet_cols(where / "hotspots.parquet", HS_COLS)
        fires = _read_parquet_cols(where / "incendios.parquet", FIRE_COLS)
        events = _read_parquet_cols(where / "eventos.parquet", EVENT_COLS)
    else:
        import pyogrio
        log(f"Reading pipeline GeoPackage {where.name}…")
        hs = pyogrio.read_dataframe(where, layer="hotspots")
        hs["longitude"] = hs.geometry.x
        hs["latitude"] = hs.geometry.y
        hs = pd.DataFrame(hs.drop(columns="geometry"))
        fires = pd.DataFrame(pyogrio.read_dataframe(where, layer="incendios", read_geometry=False))
        events = pd.DataFrame(pyogrio.read_dataframe(where, layer="eventos", read_geometry=False))
        fires = fires[[c for c in FIRE_COLS if c in fires.columns]]
        events = events[[c for c in EVENT_COLS if c in events.columns]]
    log(f"  {len(hs):,} hotspots · {len(fires):,} fires · {len(events):,} events")

    ts = pd.to_datetime(hs["ts_utc"])
    hs["acq_date"] = ts.dt.normalize()
    hs["acq_time"] = ts.dt.strftime("%H%M")
    hs = hs.rename(columns={"latitude": "lat", "longitude": "lon", "scan_km": "scan", "track_km": "track"})
    if "sensor" not in hs.columns:
        hs["sensor"] = np.where(hs["instrument"] == "MODIS", "MODIS", "VIIRS")
    if not {"scan", "track"} <= set(hs.columns):
        # The GeoPackage has no pixel size: take it from the raw detection at the same place and minute.
        key = ["lat5", "lon5", "acq_date", "acq_time"]
        r = duckdb.sql(f"select latitude as lat, longitude as lon, scan, track, acq_date, acq_time from '{DETECTIONS}'").df()
        r["acq_date"] = pd.to_datetime(r["acq_date"])
        r["acq_time"] = r["acq_time"].astype(str).str.zfill(4)
        for df_ in (r, hs):
            df_["lat5"] = df_["lat"].round(5)
            df_["lon5"] = df_["lon"].round(5)
        r = r.drop_duplicates(key)
        hs = hs.merge(r[key + ["scan", "track"]], on=key, how="left").drop(columns=["lat5", "lon5"])
        miss = hs["scan"].isna()
        log(f"  pixel size joined from raw detections; {miss.sum():,} unmatched → nominal size")
        hs.loc[miss & (hs["sensor"] == "MODIS"), ["scan", "track"]] = 1.0
        hs.loc[miss & (hs["sensor"] != "MODIS"), ["scan", "track"]] = 0.375
    hs["p"] = np.round(hs["confidence_incendio"].astype(float)).clip(0, 100).astype(np.int16)
    keep = ["lat", "lon", "scan", "track", "acq_date", "acq_time", "sensor", "p", "incendio_id", "evento_id"]
    return hs[keep].reset_index(drop=True), fires, events, f"{kind}:{where.relative_to(REPO)}"


def assign_regions(df: pd.DataFrame, join: gpd.GeoDataFrame, lat="lat", lon="lon", keep_outside=False) -> pd.DataFrame:
    pts = gpd.GeoDataFrame(df[[lat, lon]].copy(), geometry=gpd.points_from_xy(df[lon], df[lat]), crs="EPSG:4326")
    res = gpd.sjoin(pts, join, how="left", predicate="within")
    res = res[~res.index.duplicated(keep="first")]
    df = df.join(res[["id", "province"]].rename(columns={"id": "department"}))
    log(f"  {df['department'].notna().sum():,} of {len(df):,} inside Argentina")
    return df if keep_outside else df[df["department"].notna()].copy()


# ---------------------------------------------------------------- series
def build_series(df: pd.DataFrame, fires: pd.DataFrame | None, covered: tuple | None) -> float:
    log("Computing MODIS → VIIRS factor…")
    overlap = df[(df["acq_date"] >= VIIRS_START) & (df["acq_date"] <= OVERLAP_END)]
    a = overlap.groupby("sensor")["area"].sum()
    k = float(a.get("VIIRS", 0) / a.get("MODIS", 1))
    log(f"  k = {k:.4f}  (Σ VIIRS area / Σ MODIS area, {VIIRS_START.date()} → {OVERLAP_END.date()})")

    df["day"] = (df["acq_date"] - START).dt.days.astype(np.int32)
    df["isM"] = (df["sensor"] == "MODIS").astype(np.int32)
    df["isV"] = 1 - df["isM"]
    df["aM"] = df["area"] * df["isM"]
    df["aV"] = df["area"] * df["isV"]
    viirs_day = (VIIRS_START - START).days
    df["_all"] = "AR"

    # Fires per day (by start date, UTC, and centroid department); -1 = day not covered by the pipeline.
    if fires is not None and len(fires):
        fires["day"] = (pd.to_datetime(fires["t_inicio"]).dt.normalize() - START).dt.days.astype(np.int32)
        fires["_all"] = "AR"
        cov = ((covered[0] - START).days, (covered[1] - START).days)
    else:
        cov = None

    def agg(key):
        g = df.groupby([key, "day"], sort=True).agg(nM=("isM", "sum"), nV=("isV", "sum"), aM=("aM", "sum"), aV=("aV", "sum")).reset_index()
        g["h"] = np.where(g["day"] >= viirs_day, g["aV"], g["aM"] * k)
        g["nF"] = -1
        if cov is not None:
            f = fires.groupby([key, "day"]).size().rename("nF_").reset_index()
            g = g.merge(f, on=[key, "day"], how="outer")
            inside = (g["day"] >= cov[0]) & (g["day"] <= cov[1])
            g["nF"] = np.where(inside, g["nF_"].fillna(0), -1)
            g[["nM", "nV", "h"]] = g[["nM", "nV", "h"]].fillna(0)
        return g.sort_values([key, "day"])

    def dump(region_id, g):
        rows = [[int(r.day), int(r.nM), int(r.nV), round(float(r.h), 3), int(r.nF)] for r in g.itertuples()]
        write_json(OUT / "series" / f"{region_id}.json", {"region": region_id, "cols": ["day", "nModis", "nViirs", "km2", "nFires"], "rows": rows})

    for key, label in (("department", "department"), ("province", "province"), ("_all", "country")):
        log(f"Series per {label}…")
        for rid, g in agg(key).groupby(key):
            dump(rid, g)
    return k


def iso_min(s: pd.Series) -> list:
    return pd.to_datetime(s).dt.strftime("%Y-%m-%dT%H:%M").tolist()


def short_id(s: pd.Series) -> list:
    """'INC-0123456789abcdef0123' → '0123456789ab' (12 hex are plenty to tell fires apart in a month)."""
    return s.astype(str).str.split("-", n=1).str[-1].str[:12].tolist()


# ---------------------------------------------------------------- fire polygons
def encode_ring(coords, origin) -> list:
    """Ring → [dx0, dy0, dx1, dy1, …] in 1e-4 degree integers: the first vertex relative to `origin`
    (the fire centroid, also stored in the file), the rest relative to the previous vertex; closing point dropped."""
    a = np.round(np.asarray(coords)[:-1] * COORD_SCALE).astype(np.int64)
    if len(a) == 0:
        return []
    d = np.vstack([a[:1] - np.asarray(origin, dtype=np.int64), np.diff(a, axis=0)])
    return d.ravel().tolist()


def fire_geometries(found, wanted: dict, origins: dict) -> dict:
    """incendio_id → encoded outer ring, simplified for the web. Reads the WKT in batches."""
    import shapely
    import pyarrow.parquet as pq
    kind, where = found
    out: dict = {}
    if kind == "parquet":
        pf = pq.ParquetFile(where / "incendios.parquet")
        batches = (b.to_pandas() for b in pf.iter_batches(batch_size=200_000, columns=["incendio_id", "geometry_wkt"]))
    else:
        import pyogrio
        g = pyogrio.read_dataframe(where, layer="incendios", columns=["incendio_id"])
        batches = [pd.DataFrame({"incendio_id": g["incendio_id"], "geometry_wkt": shapely.to_wkt(g.geometry.values)})]
    for b in batches:
        b = b[b["incendio_id"].isin(wanted)]
        geoms = shapely.from_wkt(b["geometry_wkt"].to_numpy())
        geoms = shapely.simplify(geoms, FIRE_SIMPLIFY_DEG, preserve_topology=True)
        for fid, g in zip(b["incendio_id"].to_numpy(), geoms):
            if g is None or g.is_empty:
                continue
            if g.geom_type == "MultiPolygon":
                g = max(g.geoms, key=lambda x: x.area)
            out[fid] = encode_ring(g.exterior.coords, origins[fid])
        log(f"  {len(out):,} polygons")
    return out


def build_monthly_fires(fires: pd.DataFrame, events: pd.DataFrame, found) -> dict:
    """Writes fires/<YYYY-MM>.json and returns incendio_id → (ym, row) for linking hotspots."""
    log("Fire polygons…")
    f = fires.copy()
    f["ym"] = pd.to_datetime(f["t_inicio"]).dt.strftime("%Y-%m")
    f = f.sort_values(["ym", "confidence"])  # higher confidence drawn on top
    f["row"] = f.groupby("ym").cumcount()
    f["lon"] = f["centroid_lon"].astype(float).round(4)
    f["lat"] = f["centroid_lat"].astype(float).round(4)
    origins = dict(zip(f["incendio_id"], zip(np.round(f["lon"] * COORD_SCALE).astype(np.int64), np.round(f["lat"] * COORD_SCALE).astype(np.int64))))
    geoms = fire_geometries(found, set(f["incendio_id"]), origins)
    events_i = events.set_index("evento_id")
    link = dict(zip(f["incendio_id"], zip(f["ym"], f["row"])))
    log("Monthly fire files…")
    for ym, g in f.groupby("ym"):
        ev_ids = [x for x in g["evento_id"].dropna().unique() if x in events_i.index]
        ev = events_i.reindex(ev_ids)
        epos = {eid: i for i, eid in enumerate(ev_ids)}
        start = pd.to_datetime(g["t_inicio"])
        write_json(OUT / "fires" / f"{ym}.json", {
            "month": ym,
            "n": int(len(g)),
            "id": short_id(g["incendio_id"]),
            "start": iso_min(start),                                       # UTC
            "d": start.dt.day.astype(int).tolist(),                         # day of month (UTC)
            "conf": g["confidence"].astype(float).round(1).tolist(),        # PLAN §4.8
            "nh": g["n_hotspots"].fillna(0).astype(int).tolist(),
            "nM": g["n_hotspots_modis"].fillna(0).astype(int).tolist(),
            "nV": g["n_hotspots_viirs"].fillna(0).astype(int).tolist(),
            "sats": g["satelites_presentes"].fillna("").astype(str).tolist(),
            "km2": g["area_pixeles_km2"].astype(float).round(3).tolist(),
            "polyKm2": g["area_poligono_km2"].astype(float).round(3).tolist(),
            "pa": g["en_area_protegida"].fillna(False).astype(bool).astype(int).tolist(),
            "paName": g["ap_nombres"].fillna("").astype(str).tolist(),
            "forest": g["es_bosque"].fillna(False).astype(bool).astype(int).tolist(),
            "lon": g["lon"].tolist(),                                       # centroid
            "lat": g["lat"].tolist(),
            "geom": [geoms.get(x, []) for x in g["incendio_id"]],          # ring, 1e-4° deltas from the centroid
            "event": [epos.get(x, -1) for x in g["evento_id"]],
            "events": {
                "id": short_id(pd.Series(ev_ids)),
                "start": iso_min(ev["inicio"]),
                "end": iso_min(ev["fin"]),
                "days": ev["duracion_dias"].astype(float).round(1).tolist(),
                "nFires": ev["n_incendios"].fillna(0).astype(int).tolist(),
                "km2": ev["area_pixeles_km2"].astype(float).round(2).tolist(),
                "polyKm2": ev["area_poligono_km2"].astype(float).round(2).tolist(),
                "pa": ev["en_area_protegida"].fillna(False).astype(bool).astype(int).tolist(),
                "forest": ev["es_bosque"].fillna(False).astype(bool).astype(int).tolist(),
                "bufferKm": ev["buffer_km"].astype(float).tolist(),
                "conf": ev["confidence"].astype(float).round(1).tolist(),
            },
        })
    return link


def build_monthly_hotspots(df: pd.DataFrame, link: dict | None) -> dict:
    log("Monthly hotspot files…")
    df["ym"] = df["acq_date"].dt.strftime("%Y-%m")
    sizes = {}
    for ym, g in df.groupby("ym"):
        g = g.sort_values("p")  # higher confidence drawn on top
        obj = {
            "month": ym,
            "n": int(len(g)),
            "lat": np.round(g["lat"].to_numpy(), 4).tolist(),
            "lon": np.round(g["lon"].to_numpy(), 4).tolist(),
            "s": (g["sensor"] == "VIIRS").astype(int).tolist(),   # 0 MODIS, 1 VIIRS
            "p": g["p"].astype(int).tolist(),                     # confidence 0–100 (of its fire, PLAN §4.8)
            "r": g["r_m"].astype(int).tolist(),                   # radius in m (half-diagonal)
            "d": g["acq_date"].dt.day.astype(int).tolist(),       # day of month
        }
        if link:
            # Row of the hotspot's fire in fires/<same month>.json (-1 = no fire, or the fire started the month before).
            obj["fire"] = [(lambda t: t[1] if t and t[0] == ym else -1)(link.get(x)) for x in g["incendio_id"]]
        write_json(OUT / "hotspots" / f"{ym}.json", obj)
        sizes[ym] = int(len(g))
    return sizes


def main():
    t0 = time.time()
    if not DETECTIONS.exists():
        sys.exit(f"Missing {DETECTIONS}")
    OUT.mkdir(parents=True, exist_ok=True)
    join, regions = build_boundaries()
    write_json(OUT / "regions.json", regions)

    found = find_pipeline()
    fires = events = None
    pipeline_meta = None
    covered = None
    parts = []
    if found is not None:
        hs_p, fires, events, source = load_pipeline(found)
        covered = (hs_p["acq_date"].min(), hs_p["acq_date"].max())
        log(f"  pipeline covers {covered[0].date()} → {covered[1].date()}")
        parts.append(hs_p)
        log("Assigning fire departments (centroids)…")
        fires = assign_regions(fires, join, lat="centroid_lat", lon="centroid_lon")
        pipeline_meta = {"source": source, "from": str(covered[0].date()), "to": str(covered[1].date()),
                         "fires": int(len(fires)), "events": int(len(events))}
    else:
        log("No pipeline outputs found: using raw detections only.")
    raw_from, raw_to = raw_date_range()
    if covered is None or raw_from < covered[0] or raw_to > covered[1]:
        parts.append(load_raw_hotspots(covered))
    df = pd.concat([p for p in parts if len(p)], ignore_index=True)
    df = add_pixel_metrics(df)
    log("Assigning hotspot departments (sjoin)…")
    df = assign_regions(df.reset_index(drop=True), join)
    k = build_series(df, fires, covered)
    link = build_monthly_fires(fires, events, found) if fires is not None else None
    months = build_monthly_hotspots(df, link)
    write_json(OUT / "meta.json", {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "start": str(START.date()),
        "lastDate": str(df["acq_date"].max().date()),
        "viirsStart": str(VIIRS_START.date()),
        "kModisToViirs": round(k, 5),
        "hotspots": int(len(df)),
        "months": months,
        "source": "NASA FIRMS (MODIS C6.1, VIIRS S-NPP / NOAA-20 / NOAA-21), límites IGN",
        "pipeline": pipeline_meta,
        "provisional": pipeline_meta is None or pipeline_meta["from"] > str(START.date()),
    })
    log(f"Done in {time.time() - t0:.0f} s → {OUT}")


if __name__ == "__main__":
    main()
