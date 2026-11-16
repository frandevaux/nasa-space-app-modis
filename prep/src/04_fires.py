"""Etapa 04 — clustering hotspots -> incendios, polígonos y flags.

- Cluster por pass_bin con contacto de píxeles (GPU si está disponible).
- Polígono = unión de círculos de radio r_i; se exige un Polygon válido.
- Argentina: incendio conservado si >=1 hotspot cae dentro de ign_pais.
- AP: flag si >=1 hotspot cae dentro de un área protegida.
- Bosque: clase mayoritaria de LC_Type1 bajo el polígono.

Salidas principales:
  prep/data/interim/04_fires_core.parquet
  prep/data/interim/04_fire_hotspot_map.parquet
  prep/data/interim/04_hotspot_argentina.parquet
  prep/data/interim/04_hotspot_ap.parquet
  prep/data/interim/04_fire_landcover.parquet
  prep/data/interim/04_incendios_interim.parquet
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
import shapely
from rasterio.features import rasterize

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo  # noqa: E402
import ids  # noqa: E402
from common import RunContext, write_parquet_atomic  # noqa: E402
from gpu import _cpu_cluster, cluster_labels_gpu  # noqa: E402

FIRE_SCHEMA = pa.schema([
    ("incendio_id", pa.string()),
    ("pass_bin", pa.string()),
    ("t_inicio", pa.timestamp("us")),
    ("t_fin", pa.timestamp("us")),
    ("n_hotspots", pa.int64()),
    ("n_hotspots_modis", pa.int64()),
    ("n_hotspots_viirs", pa.int64()),
    ("sensores_presentes", pa.string()),
    ("satelites_presentes", pa.string()),
    ("n_pasadas", pa.int64()),
    ("n_satelites", pa.int64()),
    ("area_pixeles_km2", pa.float64()),
    ("area_poligono_km2", pa.float64()),
    ("frp_sum", pa.float64()),
    ("centroid_x", pa.float64()),
    ("centroid_y", pa.float64()),
    ("geometry_wkb", pa.binary()),
    ("en_argentina", pa.bool_()),
    ("en_area_protegida", pa.bool_()),
    ("ap_gids", pa.string()),
    ("ap_nombres", pa.string()),
    ("era", pa.string()),
])

MAP_SCHEMA = pa.schema([
    ("hotspot_pk", pa.int64()),
    ("incendio_id", pa.string()),
])

BIN_COLUMNS = [
    "pass_bin", "hotspot_pk", "hotspot_id", "x", "y", "r_m",
    "scan_km", "track_km", "frp", "sensor", "satellite",
    "ts_utc", "ts_local", "era",
]


# ---------------------------------------------------------------------------
# Flags por hotspot: Argentina y áreas protegidas
# ---------------------------------------------------------------------------

def build_hotspot_flags(ctx: RunContext) -> dict:
    cfg = ctx.cfg
    classified = ctx.interim("03_hotspots_classified.parquet")
    country_path = ctx.paths.get("boundaries", "country")
    ap_path = ctx.paths.get("protected_areas")

    country = gpd.read_file(country_path)
    country_geom = country.geometry.union_all()
    shapely.prepare(country_geom)
    ctx.log.info("País: %s con %d vértices", country_geom.geom_type,
                 shapely.get_num_coordinates(country_geom))

    ap_raw = gpd.read_file(ap_path)
    n_invalid_ap = int((~ap_raw.geometry.is_valid).sum())
    ap = ap_raw.copy()
    ap["geometry"] = ap.geometry.make_valid()
    ap_geoms = ap.geometry.values
    ap_gids = ap[cfg["aux"]["protected_areas"]["id_field"]].astype(str).to_numpy()
    ap_names = ap[cfg["aux"]["protected_areas"]["name_field"]].astype(str).to_numpy()
    tree = shapely.STRtree(ap_geoms)
    ctx.log.info("AP: %d polígonos, %d inválidos reparados", len(ap), n_invalid_ap)

    ar_pks: list[np.ndarray] = []
    ar_flags: list[np.ndarray] = []
    ap_pks: list[np.ndarray] = []
    ap_gi: list[np.ndarray] = []

    pf = pq.ParquetFile(classified)
    for batch in pf.iter_batches(batch_size=500_000,
                                 columns=["hotspot_pk", "longitude", "latitude"]):
        df = batch.to_pandas()
        lon = df["longitude"].to_numpy()
        lat = df["latitude"].to_numpy()
        pks = df["hotspot_pk"].to_numpy(dtype=np.int64)
        ar = shapely.intersects_xy(country_geom, lon, lat)
        ar_pks.append(pks)
        ar_flags.append(np.asarray(ar, dtype=bool))

        pi, gi = tree.query(shapely.points(lon, lat), predicate="intersects")
        if len(pi):
            ap_pks.append(pks[np.asarray(pi, dtype=np.int64)])
            ap_gi.append(np.asarray(gi, dtype=np.int64))

    ar_df = pd.DataFrame({
        "hotspot_pk": np.concatenate(ar_pks),
        "en_argentina": np.concatenate(ar_flags),
    })
    write_parquet_atomic(ar_df, ctx.interim("04_hotspot_argentina.parquet"))

    if ap_pks:
        ap_df = pd.DataFrame({
            "hotspot_pk": np.concatenate(ap_pks),
            "ap_gid": ap_gids[np.concatenate(ap_gi)],
            "ap_nombre": ap_names[np.concatenate(ap_gi)],
        }).drop_duplicates()
    else:
        ap_df = pd.DataFrame(columns=["hotspot_pk", "ap_gid", "ap_nombre"])
    write_parquet_atomic(ap_df, ctx.interim("04_hotspot_ap.parquet"))

    stats = {
        "hotspots": int(len(ar_df)),
        "argentina": int(ar_df["en_argentina"].sum()),
        "ap_pairs": int(len(ap_df)),
        "ap_hotspots": int(ap_df["hotspot_pk"].nunique()) if len(ap_df) else 0,
        "ap_polygons": int(len(ap)),
    }
    ctx.log.info("Flags: %d hotspots, %d en Argentina, %d pares AP",
                 stats["hotspots"], stats["argentina"], stats["ap_pairs"])
    return stats


# ---------------------------------------------------------------------------
# Lectura por pass_bin
# ---------------------------------------------------------------------------

def iter_bins(path: Path, columns: list[str], batch_size: int = 200_000) -> Iterator[tuple[str, pd.DataFrame]]:
    pf = pq.ParquetFile(path)
    current: str | None = None
    frames: list[pd.DataFrame] = []
    for batch in pf.iter_batches(batch_size=batch_size, columns=columns):
        df = batch.to_pandas()
        for bin_name, group in df.groupby("pass_bin", sort=False):
            if current is None:
                current = bin_name
            if bin_name != current:
                yield current, pd.concat(frames, ignore_index=True)
                frames = []
                current = bin_name
            frames.append(group)
    if frames:
        yield current, pd.concat(frames, ignore_index=True)


def cluster_bin(ctx: RunContext, bin_df: pd.DataFrame) -> tuple[np.ndarray, str]:
    x = bin_df["x"].to_numpy()
    y = bin_df["y"].to_numpy()
    r = bin_df["r_m"].to_numpy()
    n = len(bin_df)
    if n <= 1:
        return np.zeros(n, dtype=np.int32), "trivial"
    min_gpu_points = int(ctx.cfg.get("gpu", {}).get("min_bin_points", 50000))
    if ctx.gpu and ctx.gpu.available and n >= min_gpu_points:

        try:
            labels = cluster_labels_gpu(
                x, y, r,
                tile_points=int(ctx.cfg["clustering"]["gpu_tile_points"]),
                max_edges=int(ctx.cfg["clustering"]["max_edges_warn"]),
                gpu=ctx.gpu,
            )
            return labels, "gpu"
        except Exception as exc:  # noqa: BLE001
            ctx.log.warning("clustering GPU falló en %s (%s); se usa CPU",
                            bin_df["pass_bin"].iloc[0], exc)
    return _cpu_cluster(x, y, r), "cpu"


# ---------------------------------------------------------------------------
# Procesamiento de un bin
# ---------------------------------------------------------------------------

def process_bin(ctx: RunContext, bin_df: pd.DataFrame, ar_series: pd.Series,
                ap_map: dict[int, tuple[list[str], list[str]]],
                fire_writer: pq.ParquetWriter, map_writer: pq.ParquetWriter) -> dict:
    pass_bin = str(bin_df["pass_bin"].iloc[0])
    labels, engine = cluster_bin(ctx, bin_df)
    n_fires = int(labels.max()) + 1 if len(labels) else 0
    if n_fires == 0:
        return {"bins": 0, "fires": 0, "singletons": 0, "area_violations": 0,
                "polygon_errors": 0, "gpu_bins": 0, "cpu_bins": 0}

    circles = geo.build_circles(
        bin_df["x"].to_numpy(), bin_df["y"].to_numpy(), bin_df["r_m"].to_numpy(),
        quad_segs=int(ctx.cfg["polygon"]["quad_segs"]),
        epsilon_m=float(ctx.cfg["polygon"]["inflation_epsilon_m"]),
    )
    wkbs, poly_audit = geo.union_fire_polygons(
        circles, labels,
        simplify_m=float(ctx.cfg["polygon"]["simplify_m"]),
        preserve_topology=bool(ctx.cfg["polygon"]["preserve_topology"]),
        repair_attempts_m=ctx.cfg["polygon"]["repair_inflation_attempts_m"],
        simplify_fallback_m=ctx.cfg["polygon"]["simplify_fallback_m"],
        on_failure=ctx.cfg["polygon"]["on_failure"],
    )
    del circles

    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    starts = np.flatnonzero(np.diff(sorted_labels)) + 1
    groups = np.split(order, starts)

    pks = bin_df["hotspot_pk"].to_numpy(dtype=np.int64)
    hids = bin_df["hotspot_id"].to_numpy()
    ts = bin_df["ts_utc"].to_numpy()
    sensors = bin_df["sensor"].to_numpy()
    sats = bin_df["satellite"].to_numpy()
    frp = bin_df["frp"].to_numpy(dtype=float)
    pixel_area = (bin_df["scan_km"].to_numpy(dtype=float) *
                  bin_df["track_km"].to_numpy(dtype=float))
    local_hour = pd.to_datetime(bin_df["ts_local"]).dt.hour.to_numpy()
    pass_key = np.array([f"{s}|{h}" for s, h in zip(sats, local_hour)], dtype=object)
    era = bin_df["era"].to_numpy()
    xs = bin_df["x"].to_numpy()
    ys = bin_df["y"].to_numpy()
    ar = bin_df["hotspot_pk"].map(ar_series).fillna(False).to_numpy(dtype=bool)

    fire_rows: list[dict] = []
    map_rows: list[dict] = []
    area_violations = 0
    singletons = 0
    for label in range(n_fires):
        pos = groups[label]
        if len(pos) == 1:
            singletons += 1
        if wkbs[label] is None:
            continue
        geom = shapely.from_wkb(wkbs[label])
        area_poly = float(shapely.area(geom)) / 1e6
        area_pix = float(pixel_area[pos].sum())
        if area_pix > area_poly:
            area_violations += 1
        member_ids = hids[pos]
        inc_id = ids.fire_id(pass_bin, member_ids)
        n_modis = int((sensors[pos] == "MODIS").sum())
        n_viirs = int((sensors[pos] == "VIIRS").sum())
        if n_modis and n_viirs:
            sensores = "MODIS+VIIRS"
        elif n_modis:
            sensores = "MODIS"
        else:
            sensores = "VIIRS"
        sat_list = sorted(set(sats[pos].tolist()))
        gid_set: set[str] = set()
        name_set: set[str] = set()
        for pk in pks[pos]:
            ap_rec = ap_map.get(int(pk))
            if ap_rec:
                gid_set.update(ap_rec[0])
                name_set.update(ap_rec[1])
        t = ts[pos]
        fire_rows.append({
            "incendio_id": inc_id,
            "pass_bin": pass_bin,
            "t_inicio": pd.Timestamp(t.min()),
            "t_fin": pd.Timestamp(t.max()),
            "n_hotspots": int(len(pos)),
            "n_hotspots_modis": n_modis,
            "n_hotspots_viirs": n_viirs,
            "sensores_presentes": sensores,
            "satelites_presentes": ",".join(sat_list),
            "n_pasadas": int(len(set(pass_key[pos].tolist()))),
            "n_satelites": int(len(sat_list)),
            "area_pixeles_km2": area_pix,
            "area_poligono_km2": area_poly,
            "frp_sum": float(np.nansum(frp[pos])),
            "centroid_x": float(xs[pos].mean()),
            "centroid_y": float(ys[pos].mean()),
            "geometry_wkb": wkbs[label],
            "en_argentina": bool(ar[pos].any()),
            "en_area_protegida": bool(gid_set),
            "ap_gids": ",".join(sorted(gid_set)),
            "ap_nombres": ",".join(sorted(name_set)),
            "era": str(era[pos][0]),
        })
        for pk in pks[pos]:
            map_rows.append({"hotspot_pk": int(pk), "incendio_id": inc_id})

    if fire_rows:
        fire_writer.write_table(pa.Table.from_pylist(fire_rows, schema=FIRE_SCHEMA))
    if map_rows:
        map_writer.write_table(pa.Table.from_pylist(map_rows, schema=MAP_SCHEMA))

    return {
        "bins": 1,
        "fires": len(fire_rows),
        "singletons": singletons,
        "area_violations": area_violations,
        "polygon_errors": len(poly_audit["errors"]),
        "gpu_bins": 1 if engine == "gpu" else 0,
        "cpu_bins": 1 if engine == "cpu" else 0,
    }


# ---------------------------------------------------------------------------
# Landcover
# ---------------------------------------------------------------------------

def fill_landcover(ctx: RunContext) -> dict:
    cfg = ctx.cfg["aux"]["landcover"]
    forest = set(int(c) for c in cfg["forest_classes"])
    fires = pd.read_parquet(ctx.interim("04_fires_core.parquet"),
                            columns=["incendio_id", "t_inicio", "geometry_wkb"])
    manifest = pd.read_parquet(ctx.aux_dir() / "landcover_manifest.parquet")
    lc_paths = {int(y): p for y, p in zip(
        manifest.loc[manifest["layer"] == "LC_Type1", "year"],
        manifest.loc[manifest["layer"] == "LC_Type1", "path"],
    )}
    t = pd.to_datetime(fires["t_inicio"])
    years = t.dt.year.to_numpy()
    year_min, year_max = min(lc_paths), max(lc_paths)
    used_year = np.clip(years, year_min, year_max)
    exact = used_year == years
    transformer = geo.make_transformer(ctx.cfg, direction="inverse")

    rows: list[pd.DataFrame] = []
    for year in sorted(set(used_year.tolist())):
        mask = used_year == year
        sub = fires.loc[mask]
        wkbs = sub["geometry_wkb"].tolist()
        geoms = geo.transform_wkb(wkbs, transformer)
        geoms = np.array([shapely.make_valid(g) if not g.is_valid else g for g in geoms],
                         dtype=object)
        n = len(geoms)
        with rasterio.open(lc_paths[year]) as ds:
            lc = ds.read(1)
            fire_raster = rasterize(
                ((g, i + 1) for i, g in enumerate(geoms)),
                out_shape=lc.shape, transform=ds.transform,
                fill=0, dtype=np.int32, all_touched=False,
            )
            cls, counts = geo.majority_class(fire_raster, lc, n_classes=32)
            metodo = np.full(n, "polygon", dtype=object)

            zero = counts == 0
            if zero.any():
                idx = np.flatnonzero(zero)
                fr2 = rasterize(
                    ((geoms[i], j + 1) for j, i in enumerate(idx)),
                    out_shape=lc.shape, transform=ds.transform,
                    fill=0, dtype=np.int32, all_touched=True,
                )
                cls2, counts2 = geo.majority_class(fr2, lc, n_classes=32)
                cls[idx] = cls2
                counts[idx] = counts2
                metodo[idx] = "all_touched"

            zero = counts == 0
            if zero.any():
                for i in np.flatnonzero(zero):
                    cent = shapely.centroid(geoms[i])
                    row, col = ds.index(shapely.get_x(cent), shapely.get_y(cent))
                    if 0 <= row < lc.shape[0] and 0 <= col < lc.shape[1]:
                        value = int(lc[row, col])
                        if value != int(cfg["nodata"]) and 0 <= value < 32:
                            cls[i] = value
                            metodo[i] = "centroid"
                        else:
                            cls[i] = -1
                            metodo[i] = "none"
                    else:
                        cls[i] = -1
                        metodo[i] = "none"

        rows.append(pd.DataFrame({
            "incendio_id": sub["incendio_id"].to_numpy(),
            "lc_clase": cls.astype(np.int16),
            "lc_anio_usado": np.full(n, year, dtype=np.int16),
            "lc_anio_exacto": exact[mask],
            "lc_metodo": metodo,
            "es_bosque": np.isin(cls, list(forest)),
        }))
        ctx.log.info("Landcover %d: %d incendios", year, n)

    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["incendio_id", "lc_clase", "lc_anio_usado", "lc_anio_exacto",
                 "lc_metodo", "es_bosque"])
    write_parquet_atomic(out, ctx.interim("04_fire_landcover.parquet"))
    return {
        "fires": int(len(out)),
        "methods": out["lc_metodo"].value_counts().to_dict() if len(out) else {},
        "forest": int(out["es_bosque"].sum()) if len(out) else 0,
        "year_min": int(out["lc_anio_usado"].min()) if len(out) else None,
        "year_max": int(out["lc_anio_usado"].max()) if len(out) else None,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("04_fires", argv)
    try:
        ctx.init_gpu()
        cfg = ctx.cfg
        ctx.stats.add("fires.engine_gpu", bool(ctx.gpu and ctx.gpu.available))

        with ctx.stats.timing("flags"):
            flag_stats = build_hotspot_flags(ctx)
        ctx.stats.add("flags", flag_stats)

        ar_series = pd.read_parquet(ctx.interim("04_hotspot_argentina.parquet")) \
            .set_index("hotspot_pk")["en_argentina"]
        ap_df = pd.read_parquet(ctx.interim("04_hotspot_ap.parquet"))
        ap_map: dict[int, tuple[list[str], list[str]]] = {}
        if len(ap_df):
            grouped = ap_df.groupby("hotspot_pk")
            for pk, part in grouped:
                ap_map[int(pk)] = (part["ap_gid"].tolist(), part["ap_nombre"].tolist())

        fire_tmp = ctx.interim("04_fires_core.parquet.tmp")
        map_tmp = ctx.interim("04_fire_hotspot_map.parquet.tmp")
        fire_writer = pq.ParquetWriter(fire_tmp, FIRE_SCHEMA, compression="zstd")
        map_writer = pq.ParquetWriter(map_tmp, MAP_SCHEMA, compression="zstd")
        totals = {"bins": 0, "fires": 0, "singletons": 0, "area_violations": 0,
                  "polygon_errors": 0, "gpu_bins": 0, "cpu_bins": 0}
        try:
            with ctx.stats.timing("clustering"):
                for bin_name, bin_df in iter_bins(
                        ctx.interim("03_hotspots_classified.parquet"), BIN_COLUMNS):
                    rec = process_bin(ctx, bin_df, ar_series, ap_map, fire_writer, map_writer)
                    for k in totals:
                        totals[k] += rec[k]
                    if totals["bins"] % 1000 == 0:
                        ctx.log.info("Bins procesados: %d, incendios=%d",
                                     totals["bins"], totals["fires"])
        finally:
            fire_writer.close()
            map_writer.close()
        os.replace(fire_tmp, ctx.interim("04_fires_core.parquet"))
        os.replace(map_tmp, ctx.interim("04_fire_hotspot_map.parquet"))

        with ctx.stats.timing("landcover"):
            lc_stats = fill_landcover(ctx)
        ctx.stats.add("landcover", lc_stats)

        fires = pd.read_parquet(ctx.interim("04_fires_core.parquet"))
        lc = pd.read_parquet(ctx.interim("04_fire_landcover.parquet"))
        interim = fires.merge(lc, on="incendio_id", how="left")
        interim_ar = interim[interim["en_argentina"]].copy()
        write_parquet_atomic(interim_ar, ctx.interim("04_incendios_interim.parquet"))

        ctx.stats.add("fires.total", int(len(fires)))
        ctx.stats.add("fires.argentina", int(fires["en_argentina"].sum()))
        ctx.stats.add("fires.singletons", int(totals["singletons"]))
        ctx.stats.add("fires.singleton_fraction",
                      float(totals["singletons"] / max(1, len(fires))))
        ctx.stats.add("fires.area_violations", int(totals["area_violations"]))
        ctx.stats.add("fires.area_violation_fraction",
                      float(totals["area_violations"] / max(1, len(fires))))
        ctx.stats.add("fires.polygon_errors", int(totals["polygon_errors"]))
        ctx.stats.add("fires.bins_processed", int(totals["bins"]))
        ctx.stats.add("fires.gpu_bins", int(totals["gpu_bins"]))
        ctx.stats.add("fires.cpu_bins", int(totals["cpu_bins"]))
        ctx.stats.add("fires.ap", int(fires["en_area_protegida"].sum()))
        ctx.stats.add("fires.forest", int(interim["es_bosque"].fillna(False).sum()))
        ctx.stats.table("fires.size_hist",
                        fires.groupby("n_hotspots").size().head(20).reset_index(name="fires").to_dict("records"))
        ctx.stats.flush()
        ctx.log.info("Etapa 04 OK: %d incendios (%d Argentina, %.2f%% violaciones de área)",
                     len(fires), int(fires["en_argentina"].sum()),
                     100.0 * totals["area_violations"] / max(1, len(fires)))
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 04 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
