"""Etapa 07 — export final: parquet WGS84, GeoPackage y report.md.

- Parquet: hotspots, incendios y eventos con geometría WKT en EPSG:4326.
- GeoPackage: areas_protegidas_ign, limites_provincia, eventos, incendios,
  hotspots.
- report.md: conteos por etapa, QC de polígonos, confidence, tiempos y
  tamaños de artefactos.
"""

from __future__ import annotations

import gc
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo  # noqa: E402
from common import RunContext, write_parquet_atomic  # noqa: E402


def to_wgs84_wkt(wkbs: pd.Series, transformer_inv) -> list[str]:
    geoms = geo.transform_wkb(wkbs.tolist(), transformer_inv)
    return geo.to_wkt(geoms, rounding_precision=7)


def transform_centroids(x: np.ndarray, y: np.ndarray, transformer_inv) -> tuple[np.ndarray, np.ndarray]:
    lon, lat = transformer_inv.transform(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return np.asarray(lon), np.asarray(lat)


def load_and_transform(ctx: RunContext) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cfg = ctx.cfg
    inv = geo.make_transformer(cfg, direction="inverse")

    fires = pd.read_parquet(ctx.interim("06_incendios_final.parquet"))
    fire_event = pd.read_parquet(ctx.interim("05_fire_event_map.parquet"))
    fires = fires.merge(fire_event, on="incendio_id", how="left", validate="one_to_one")
    fires_ar = fires[fires["en_argentina"]].copy()

    events = pd.read_parquet(ctx.interim("06_eventos_final.parquet"))
    events = events[events["incendios_argentina"] > 0].copy()

    hs = pd.read_parquet(ctx.interim("06_hotspots_final.parquet"))
    hs = hs[hs["incendio_id"].isin(set(fires_ar["incendio_id"]))].copy()

    # Geometrías WGS84.
    fires_ar["geometry_wkt"] = to_wgs84_wkt(fires_ar["geometry_wkb"], inv)
    events["geometry_wkt"] = to_wgs84_wkt(events["geometry_wkb"], inv)
    fires_ar["centroid_lon"], fires_ar["centroid_lat"] = transform_centroids(
        fires_ar["centroid_x"].to_numpy(), fires_ar["centroid_y"].to_numpy(), inv)

    ev_geoms = shapely.from_wkb(events["geometry_wkb"].tolist())
    ev_cent = shapely.centroid(ev_geoms)
    events["centroid_lon"], events["centroid_lat"] = transform_centroids(
        shapely.get_x(ev_cent), shapely.get_y(ev_cent), inv)

    fires_ar = fires_ar.drop(columns=["geometry_wkb"])
    events = events.drop(columns=["geometry_wkb"])
    return hs, fires_ar, events


def write_gpkg(ctx: RunContext, hs: pd.DataFrame, fires: pd.DataFrame, events: pd.DataFrame) -> Path:
    cfg = ctx.cfg
    gpkg = ctx.qgis_dir() / "fuego.gpkg"
    if gpkg.exists():
        gpkg.unlink()

    # Capas chicas primero. append=False crea una capa nueva sin borrar las
    # anteriores del GeoPackage.
    ap = gpd.read_file(ctx.paths.get("protected_areas"))
    ap["geometry"] = ap.geometry.make_valid()
    keep_ap = [c for c in ["gid", "fna", "nam", "fdc", "sag", "geometry"] if c in ap.columns]
    pyogrio.write_dataframe(ap[keep_ap], gpkg, layer="areas_protegidas_ign",
                            driver="GPKG", append=False,
                            layer_options={"SPATIAL_INDEX": "YES"})

    prov = gpd.read_file(ctx.paths.get("boundaries", "province"))
    pyogrio.write_dataframe(prov, gpkg, layer="limites_provincia",
                            driver="GPKG", append=False,
                            layer_options={"SPATIAL_INDEX": "YES"})

    ev_gdf = gpd.GeoDataFrame(
        events.drop(columns=["geometry_wkt"]),
        geometry=gpd.GeoSeries.from_wkt(events["geometry_wkt"]),
        crs="EPSG:4326",
    )
    pyogrio.write_dataframe(ev_gdf, gpkg, layer="eventos", driver="GPKG",
                            promote_to_multi=True, append=False,
                            layer_options={"SPATIAL_INDEX": "YES"})

    fire_gdf = gpd.GeoDataFrame(
        fires.drop(columns=["geometry_wkt"]),
        geometry=gpd.GeoSeries.from_wkt(fires["geometry_wkt"]),
        crs="EPSG:4326",
    )
    pyogrio.write_dataframe(fire_gdf, gpkg, layer="incendios", driver="GPKG",
                            append=False, layer_options={"SPATIAL_INDEX": "YES"})

    hs_cols = ["hotspot_pk", "hotspot_id", "latitude", "longitude", "ts_utc",
               "satellite", "sensor", "conf_class", "incendio_id", "evento_id",
               "confidence_incendio", "confidence_evento"]
    hs_cols = [c for c in hs_cols if c in hs.columns]
    chunk = 500_000
    first = True
    for start in range(0, len(hs), chunk):
        part = hs.iloc[start:start + chunk][hs_cols]
        gdf = gpd.GeoDataFrame(
            part.drop(columns=["longitude", "latitude"]),
            geometry=gpd.points_from_xy(part["longitude"], part["latitude"]),
            crs="EPSG:4326",
        )
        pyogrio.write_dataframe(gdf, gpkg, layer="hotspots", driver="GPKG",
                                append=not first,
                                layer_options={"SPATIAL_INDEX": "YES"} if first else None)
        first = False
    return gpkg


def _geom_summary(wkts: pd.Series, chunk: int = 2000) -> tuple[np.ndarray, bool]:
    """Parsea WKT por chunks para no crear un array Unicode gigante."""
    types: list[np.ndarray] = []
    valid = True
    for start in range(0, len(wkts), chunk):
        part = wkts.iloc[start:start + chunk].tolist()
        geoms = shapely.from_wkt(part)
        types.append(shapely.get_type_id(geoms))
        if not bool(shapely.is_valid(geoms).all()):
            valid = False
    arr = np.concatenate(types) if types else np.array([], dtype=np.int64)
    return arr, valid


def validate(ctx: RunContext, hs_summary: dict, fires: pd.DataFrame,
             events: pd.DataFrame) -> dict:
    out: dict = {}
    out["counts"] = {"hotspots": int(hs_summary["hotspots"]),
                     "incendios": int(len(fires)), "eventos": int(len(events))}
    out["hotspots_nulls"] = hs_summary["nulls"]
    out["confidence_range"] = {
        "fires_min": float(fires["confidence"].min()),
        "fires_max": float(fires["confidence"].max()),
        "events_min": float(events["confidence"].min()),
        "events_max": float(events["confidence"].max()),
    }
    pre = fires[fires["era"] == "solo_MODIS"]
    out["pre_viirs_max"] = float(pre["confidence"].max()) if len(pre) else None
    out["confidence_nulls"] = {
        "fires": int(fires["confidence"].isna().sum()),
        "events": int(events["confidence"].isna().sum()),
    }
    out["area_violations"] = int((fires["area_pixeles_km2"] >
                                  fires["area_poligono_km2"]).sum())
    out["area_violation_fraction"] = float(out["area_violations"] / max(1, len(fires)))
    fire_types, fire_valid = _geom_summary(fires["geometry_wkt"])
    event_types, event_valid = _geom_summary(events["geometry_wkt"])
    out["fire_geom_types"] = pd.Series(fire_types).value_counts().to_dict()
    out["event_geom_types"] = pd.Series(event_types).value_counts().to_dict()
    out["fire_geom_valid"] = bool(fire_valid)
    out["event_geom_valid"] = bool(event_valid)
    out["fire_geom_single_polygon"] = bool((fire_types == 3).all())
    out["event_multipolygon"] = int((event_types == 6).sum())
    return out


def render_report(ctx: RunContext, validations: dict, artifacts: list[Path]) -> Path:
    stats_dir = ctx.stats_dir()
    lines = ["# Reporte de preprocesamiento FIRMS", ""]
    lines.append(f"- Etapa: `{ctx.stage}`")
    lines.append(f"- Smoke: `{ctx.smoke}` / caso: `{ctx.smoke_case}`")
    lines.append(f"- run_id: `{ctx.run_id}`")
    lines.append("")
    lines.append("## Conteos por etapa")
    lines.append("")
    lines.append("| Etapa | Duración (s) | Métricas clave | Warnings |")
    lines.append("|---|---:|---|---|")
    for path in sorted(stats_dir.glob("*.json")):
        data = json.loads(path.read_text())
        metrics = data.get("metrics", {})
        keys = [k for k in metrics if any(x in k for x in (
            "rows", "total", "argentina", "discarded", "fires", "events",
            "pass_bins", "hotspots", "duplicates"))][:6]
        summary = "; ".join(f"{k}={metrics[k]}" for k in keys)
        lines.append(f"| {data.get('stage')} | {data.get('duration_s')} | {summary} | "
                     f"{len(data.get('warnings', []))} |")
    lines.append("")
    lines.append("## Validaciones")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(validations, indent=2, ensure_ascii=False, default=str))
    lines.append("```")
    lines.append("")
    lines.append("## Artefactos")
    lines.append("")
    lines.append("| Archivo | Bytes |")
    lines.append("|---|---:|")
    for path in artifacts:
        if path.exists():
            lines.append(f"| `{path}` | {path.stat().st_size} |")
    lines.append("")
    lines.append("## Cómo abrir en QGIS")
    lines.append("")
    lines.append(f"1. Abrir `{ctx.qgis_dir() / 'fuego.gpkg'}`.")
    lines.append("2. Colorear `eventos` por `evento_id` y usar transparencia por `confidence`.")
    lines.append("3. Revisar `incendios` en parques nacionales y el flag `es_bosque`.")
    lines.append("")
    dest = (ctx._smoke_root() / "report.md") if ctx.smoke else (ctx.prep_root / "report.md")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def _hs_summary(hs: pd.DataFrame) -> dict:
    return {
        "hotspots": int(len(hs)),
        "nulls": {
            "incendio_id": int(hs["incendio_id"].isna().sum()),
            "evento_id": int(hs["evento_id"].isna().sum()),
            "conf_inc": int(hs["confidence_incendio"].isna().sum()),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("07_export", argv)
    try:
        proc = ctx.processed_dir()
        if ctx.report_only:
            ctx.log.info("Modo report-only: no se reescriben parquet ni GPKG")
            fires = pd.read_parquet(proc / "incendios.parquet")
            events = pd.read_parquet(proc / "eventos.parquet")
            hs = pd.read_parquet(proc / "hotspots.parquet",
                                 columns=["incendio_id", "evento_id", "confidence_incendio"])
            summary = _hs_summary(hs)
            del hs
            gc.collect()
            gpkg = ctx.qgis_dir() / "fuego.gpkg"
            if not gpkg.exists():
                raise FileNotFoundError(f"No existe el GPKG para el reporte: {gpkg}")
        else:
            hs, fires, events = load_and_transform(ctx)
            write_parquet_atomic(hs, proc / "hotspots.parquet")
            write_parquet_atomic(fires, proc / "incendios.parquet")
            write_parquet_atomic(events, proc / "eventos.parquet")
            gpkg = write_gpkg(ctx, hs, fires, events)
            summary = _hs_summary(hs)
            del hs
            gc.collect()

        validations = validate(ctx, summary, fires, events)
        artifacts = [proc / "hotspots.parquet", proc / "incendios.parquet",
                     proc / "eventos.parquet", gpkg]
        report = render_report(ctx, validations, artifacts)

        ctx.stats.add("export.hotspots", int(summary["hotspots"]))
        ctx.stats.add("export.incendios", int(len(fires)))
        ctx.stats.add("export.eventos", int(len(events)))
        ctx.stats.add("export.gpkg", str(gpkg))
        ctx.stats.add("export.report", str(report))
        ctx.stats.add("export.validations", validations)
        ctx.stats.flush()
        ctx.log.info("Etapa 07 OK: %d hotspots, %d incendios, %d eventos -> %s",
                     summary["hotspots"], len(fires), len(events), gpkg)
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 07 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
