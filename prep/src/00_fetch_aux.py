"""Etapa 00 — auxiliares.

- Trae `ign_area_protegida` de la rama RaMarti del repo (NO usa WFS).
- Valida la capa (506 features) y los boundaries existentes.
- Construye y valida el manifest de MCD12Q1 (LC_Type1 + QC).

Salidas:
  prep/data/boundaries/ign_area_protegida.geojson
  prep/data/interim/aux/boundary_manifest.json
  prep/data/interim/aux/landcover_manifest.parquet
  prep/data/interim/stats/00_fetch_aux.json
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Antes de importar geopandas/pyogrio/GDAL.
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RunContext, atomic_write_json, sha256_file, write_parquet_atomic  # noqa: E402


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check)


def fetch_protected_areas(ctx: RunContext) -> Path:
    cfg = ctx.cfg
    repo = ctx.prep_root.parent
    dest = ctx.paths.get("protected_areas")
    branch = cfg["repo"]["ap_branch"]
    glob = cfg["repo"]["ap_search_glob"].lower()

    if dest.exists() and not ctx.force:
        ctx.log.info("AP ya existe en %s; se reutiliza (usar --force para refrescar)", dest)
        return dest

    # Actualiza sólo refs; no toca el working tree.
    fetch = _git(repo, "fetch", "origin", branch, check=False)
    if fetch.returncode != 0:
        ctx.stats.warn(f"git fetch origin {branch} falló: {fetch.stderr.strip()}")
    ref = f"origin/{branch}"

    tree = _git(repo, "ls-tree", "-r", "--name-only", ref)
    candidates = [line for line in tree.stdout.splitlines()
                  if fnmatch.fnmatch(line.lower(), glob)]
    if not candidates:
        raise FileNotFoundError(
            f"No se encontró una capa que coincida con {glob!r} en {ref}. "
            "No se descarga del WFS por decisión del equipo."
        )
    # Preferir el nombre canónico si hay varios.
    canonical = [p for p in candidates if p.lower().endswith("ign_area_protegida.geojson")]
    rel_path = (canonical or candidates)[0]

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with tmp.open("wb") as fh:
        shown = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{rel_path}"],
                               stdout=fh, stderr=subprocess.PIPE, check=True)
    if tmp.stat().st_size < 1000:
        head = tmp.read_bytes()[:200]
        if b"git-lfs.github.com" in head or head.startswith(b"version https://git-lfs"):
            tmp.unlink(missing_ok=True)
            raise RuntimeError("La capa es un puntero Git LFS; hace falta git lfs pull")
    tmp.replace(dest)
    ctx.log.info("AP extraída de %s:%s (%s bytes)", ref, rel_path, dest.stat().st_size)
    ctx.stats.add("aux.ap.source_ref", ref)
    ctx.stats.add("aux.ap.source_path", rel_path)
    return dest


def validate_protected_areas(ctx: RunContext, path: Path) -> dict:
    cfg = ctx.cfg["aux"]["protected_areas"]
    gdf = gpd.read_file(path)
    expected = int(cfg["expected_features"])
    result = {
        "path": str(path),
        "features": int(len(gdf)),
        "expected": expected,
        "crs": str(gdf.crs),
        "fields": list(gdf.columns),
        "geom_types": sorted(gdf.geom_type.dropna().unique().tolist()),
        "invalid_geoms": int((~gdf.geometry.is_valid).sum()),
        "sha256": sha256_file(path),
        "bbox": [float(v) for v in gdf.total_bounds],
    }
    if len(gdf) != expected:
        raise ValueError(f"AP: se esperaban {expected} features, llegaron {len(gdf)}")
    if str(gdf.crs).upper() not in {"EPSG:4326", "WGS 84"}:
        raise ValueError(f"AP: CRS inesperado {gdf.crs}")
    bad = set(result["geom_types"]) - {"Polygon", "MultiPolygon"}
    if bad:
        raise ValueError(f"AP: geometrías inesperadas {bad}")
    fields = set(gdf.columns)
    missing = {cfg["id_field"], cfg["name_field"]} - fields
    if missing:
        raise ValueError(f"AP: faltan campos {missing}")
    if result["invalid_geoms"]:
        ctx.stats.warn(f"AP: {result['invalid_geoms']} geometrías inválidas")
    return result


def validate_boundaries(ctx: RunContext) -> dict:
    expected = {"country": 1, "province": 24, "department": 529}
    out: dict[str, dict] = {}
    for key, exp in expected.items():
        path = ctx.paths.get("boundaries", key)
        gdf = gpd.read_file(path, columns=None)
        rec = {
            "path": str(path),
            "features": int(len(gdf)),
            "expected": exp,
            "crs": str(gdf.crs),
            "geom_types": sorted(gdf.geom_type.dropna().unique().tolist()),
        }
        if len(gdf) != exp:
            raise ValueError(f"boundary {key}: se esperaban {exp}, llegaron {len(gdf)}")
        out[key] = rec
    return out


def scan_landcover(ctx: RunContext) -> pd.DataFrame:
    cfg = ctx.cfg["aux"]["landcover"]
    root = ctx.paths.get("raw_landcover")
    year_re = re.compile(cfg["year_regex"])
    rows: list[dict] = []
    for layer in ("LC_Type1", "QC"):
        for path in sorted(root.glob(f"MCD12Q1.061_{layer}_doy*001000000_aid0001.tif")):
            m = year_re.search(path.name)
            if not m:
                continue
            rows.append({"layer": layer, "year": int(m.group(1)),
                         "path": str(path), "size_bytes": path.stat().st_size})
    if not rows:
        raise FileNotFoundError(f"No hay GeoTIFF MCD12Q1 en {root}")
    manifest = pd.DataFrame(rows).sort_values(["layer", "year"]).reset_index(drop=True)
    return manifest


def validate_landcover(ctx: RunContext, manifest: pd.DataFrame) -> dict:
    import rasterio

    cfg = ctx.cfg["aux"]["landcover"]
    expected_years = set(int(y) for y in cfg["years_expected"])
    lc = manifest[manifest["layer"] == "LC_Type1"]
    qc = manifest[manifest["layer"] == "QC"]
    missing_lc = sorted(expected_years - set(lc["year"]))
    missing_qc = sorted(expected_years - set(qc["year"]))
    if missing_lc or missing_qc:
        raise ValueError(f"Landcover incompleto: LC falta {missing_lc}, QC falta {missing_qc}")
    if len(lc) != len(expected_years) or len(qc) != len(expected_years):
        raise ValueError(f"Landcover: años duplicados o extra (LC={len(lc)}, QC={len(qc)})")

    checks = []
    for _, row in lc.iterrows():
        with rasterio.open(row["path"]) as ds:
            checks.append({
                "year": int(row["year"]),
                "crs": str(ds.crs),
                "nodata": ds.nodata,
                "dtype": ds.dtypes[0],
                "width": ds.width,
                "height": ds.height,
                "bounds": [float(v) for v in ds.bounds],
            })
    first = checks[0]
    for rec in checks[1:]:
        for key in ("crs", "nodata", "dtype", "width", "height"):
            if rec[key] != first[key]:
                raise ValueError(f"Landcover {rec['year']}: {key} distinto ({rec[key]} vs {first[key]})")
    if first["crs"].upper() not in {"EPSG:4326", "WGS 84"}:
        raise ValueError(f"Landcover: CRS inesperado {first['crs']}")
    if int(first["nodata"]) != int(cfg["nodata"]):
        raise ValueError(f"Landcover: NoData {first['nodata']} != {cfg['nodata']}")

    return {
        "files": int(len(manifest)),
        "years": sorted(int(y) for y in lc["year"]),
        "qc_files": int(len(qc)),
        "crs": first["crs"],
        "nodata": first["nodata"],
        "dtype": first["dtype"],
        "shape": [first["height"], first["width"]],
        "bounds": first["bounds"],
    }


def main(argv: list[str] | None = None) -> int:
    ctx = RunContext.from_cli("00_fetch_aux", argv)
    try:
        ap_path = fetch_protected_areas(ctx)
        ap = validate_protected_areas(ctx, ap_path)
        boundaries = validate_boundaries(ctx)
        lc_manifest = scan_landcover(ctx)
        lc = validate_landcover(ctx, lc_manifest)

        aux_dir = ctx.aux_dir()
        write_parquet_atomic(lc_manifest, aux_dir / "landcover_manifest.parquet")
        atomic_write_json(aux_dir / "boundary_manifest.json", {
            "protected_areas": ap,
            "boundaries": boundaries,
            "landcover": lc,
        })

        ctx.stats.add("aux.ap.features", ap["features"])
        ctx.stats.add("aux.ap.sha256", ap["sha256"])
        ctx.stats.add("aux.ap.invalid_geoms", ap["invalid_geoms"])
        ctx.stats.add("aux.boundaries", {k: v["features"] for k, v in boundaries.items()})
        ctx.stats.add("aux.landcover.files", lc["files"])
        ctx.stats.add("aux.landcover.years", lc["years"])
        ctx.stats.add("aux.landcover.shape", lc["shape"])
        ctx.stats.flush()
        ctx.log.info("Etapa 00 OK: AP=%d, boundaries=%s, LC=%d archivos",
                     ap["features"], {k: v["features"] for k, v in boundaries.items()}, lc["files"])
        return 0
    except Exception as exc:  # noqa: BLE001
        ctx.log.exception("Etapa 00 falló: %s", exc)
        ctx.stats.warn(str(exc))
        ctx.stats.flush()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
