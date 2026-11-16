"""Geometría: proyección, radios de píxel, círculos, polígonos y joins."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import shapely
from pyproj import Transformer


class PolygonError(RuntimeError):
    pass


def make_transformer(cfg: dict, direction: str = "forward") -> Transformer:
    """WGS84 (lon/lat) <-> TM única lon_0=-63."""
    tmerc = cfg["projection"]["tmerc"]
    if direction == "forward":
        return Transformer.from_crs("EPSG:4326", tmerc, always_xy=True)
    return Transformer.from_crs(tmerc, "EPSG:4326", always_xy=True)


def project_points(lon: np.ndarray, lat: np.ndarray,
                   transformer: Transformer) -> tuple[np.ndarray, np.ndarray]:
    x, y = transformer.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    return np.asarray(x, dtype=float), np.asarray(y, dtype=float)


def radius_m(scan_km: np.ndarray, track_km: np.ndarray) -> np.ndarray:
    """Semidiagonal del píxel, en metros."""
    return 0.5 * np.sqrt(np.asarray(scan_km, dtype=float) ** 2 +
                         np.asarray(track_km, dtype=float) ** 2) * 1000.0


def inflated_radius(r: np.ndarray, quad_segs: int = 8, epsilon_m: float = 1.0) -> np.ndarray:
    """Radio del buffer para que los círculos tangentes sigan tocándose.

    El buffer aproxima el círculo con un polígono inscripto; se compensa el
    déficit del polígono regular y se agrega 1 m.
    """
    factor = 1.0 / math.cos(math.pi / (4.0 * quad_segs))
    return np.asarray(r, dtype=float) * factor + float(epsilon_m)


def build_circles(x: np.ndarray, y: np.ndarray, r: np.ndarray,
                  quad_segs: int = 8, epsilon_m: float = 1.0) -> np.ndarray:
    """Array de polígonos (shapely 2 vectorizado), en la proyección TM."""
    points = shapely.points(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    radii = inflated_radius(r, quad_segs=quad_segs, epsilon_m=epsilon_m)
    return shapely.buffer(points, radii, quad_segs=int(quad_segs),
                          cap_style="round", join_style="round")


def union_fire_polygons(circles: np.ndarray, labels: np.ndarray,
                        simplify_m: float = 25.0,
                        preserve_topology: bool = True,
                        repair_attempts_m: Sequence[float] = (0.0, 2.0, 5.0),
                        simplify_fallback_m: Sequence[float] = (25.0, 10.0, 1.0, 0.0),
                        on_failure: str = "raise") -> tuple[list[bytes | None], dict]:
    """Une los círculos de cada incendio y devuelve WKB (TM) + auditoría.

    Los incendios de un solo hotspot se simplifican vectorizadamente.
    Los multi-hotspot usan shapely.union_all. Se exige un único Polygon
    válido; si no, se reintenta con más inflación/menos simplificación.
    """
    labels = np.asarray(labels)
    n = len(labels)
    n_labels = int(labels.max()) + 1 if n else 0
    out: list[bytes | None] = [None] * n_labels
    errors: list[dict] = []
    n_multi = 0
    n_repaired = 0

    # Orden determinístico por etiqueta.
    order = np.argsort(labels, kind="stable")
    sorted_labels = labels[order]
    boundaries = np.flatnonzero(np.diff(sorted_labels)) + 1
    groups = np.split(order, boundaries)

    for members in groups:
        if len(members) == 0:
            continue
        label = int(labels[members[0]])
        geoms = circles[members]
        geom = None
        used_simplify = simplify_m
        for attempt_idx, extra_m in enumerate(repair_attempts_m):
            if len(members) == 1:
                geom = geoms[0]
            else:
                # Reintento: inflar un poco más si el anterior quedó partido.
                if attempt_idx == 0:
                    geom = shapely.union_all(geoms)
                else:
                    inflated = shapely.buffer(geoms, float(extra_m), quad_segs=8)
                    geom = shapely.union_all(inflated)
            if geom is None or geom.is_empty:
                continue
            for simp in (used_simplify, *simplify_fallback_m):
                candidate = shapely.simplify(geom, float(simp), preserve_topology=preserve_topology)
                if candidate.is_empty:
                    continue
                if candidate.geom_type == "Polygon" and candidate.is_valid:
                    geom = candidate
                    used_simplify = simp
                    break
                if candidate.geom_type == "MultiPolygon":
                    # Puede ser válido si el original era MultiPolygon; se
                    # intenta quedarse con la unión si es conexa.
                    merged = shapely.union_all(list(candidate.geoms))
                    if merged.geom_type == "Polygon" and merged.is_valid:
                        geom = merged
                        used_simplify = simp
                        n_multi += 1
                        break
            if geom is not None and geom.geom_type == "Polygon" and geom.is_valid:
                break

        if geom is None or geom.geom_type != "Polygon" or not geom.is_valid:
            n_repaired += 1
            rec = {
                "label": label,
                "n_hotspots": int(len(members)),
                "geom_type": None if geom is None else geom.geom_type,
                "valid": None if geom is None else bool(geom.is_valid),
            }
            errors.append(rec)
            if on_failure == "raise":
                raise PolygonError(f"incendio {label}: no se pudo construir un Polygon válido: {rec}")
            out[label] = None
            continue

        out[label] = shapely.to_wkb(geom)
        if used_simplify != simplify_m:
            n_repaired += 1

    audit = {
        "fires": int(n_labels),
        "multi_inputs_merged": int(n_multi),
        "repaired": int(n_repaired),
        "errors": errors,
    }
    return out, audit


def polygon_area_km2(wkb: bytes) -> float:
    return float(shapely.area(shapely.from_wkb(wkb))) / 1e6


def polygons_area_km2(wkbs: Iterable[bytes | None]) -> np.ndarray:
    geoms = shapely.from_wkb([w for w in wkbs])
    return shapely.area(geoms) / 1e6


def polygon_centroid_wkb(wkbs: Iterable[bytes | None]) -> tuple[np.ndarray, np.ndarray]:
    geoms = shapely.from_wkb([w for w in wkbs])
    cents = shapely.centroid(geoms)
    return shapely.get_x(cents), shapely.get_y(cents)


def transform_wkb(wkbs: Sequence[bytes], transformer: Transformer) -> np.ndarray:
    """Transforma WKB entre CRS usando shapely.transform (vectorizado)."""
    geoms = shapely.from_wkb(list(wkbs))

    def _coords(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geoms, _coords)


def to_wkt(geoms: Sequence, rounding_precision: int = 7) -> list[str]:
    return shapely.to_wkt(list(geoms), rounding_precision=rounding_precision).tolist()


def points_in_polygon(points_xy: np.ndarray, polygon) -> np.ndarray:
    """Máscara booleana; incluye el borde (intersects)."""
    x = np.asarray(points_xy[:, 0], dtype=float)
    y = np.asarray(points_xy[:, 1], dtype=float)
    return np.asarray(shapely.intersects_xy(polygon, x, y), dtype=bool)


def query_polygons(points_xy: np.ndarray, polygons: Sequence,
                   polygon_ids: Sequence[int],
                   polygon_names: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    """STRtree: devuelve pares (índice de punto, índice de polígono)."""
    if len(polygons) == 0 or len(points_xy) == 0:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    tree = shapely.STRtree(list(polygons))
    pts = shapely.points(np.asarray(points_xy[:, 0], dtype=float),
                         np.asarray(points_xy[:, 1], dtype=float))
    point_idx, poly_idx = tree.query(pts, predicate="intersects")
    return np.asarray(point_idx, dtype=np.int64), np.asarray(poly_idx, dtype=np.int64)


def majority_class(fire_ids: np.ndarray, classes: np.ndarray,
                   n_classes: int = 32) -> tuple[np.ndarray, np.ndarray]:
    """Clase mayoritaria por fire_id sobre píxeles válidos.

    Devuelve (clase, conteo) por fire_id; fire_id debe ser 1..N.
    """
    n_fires = int(fire_ids.max()) if fire_ids.size else 0
    if n_fires == 0:
        return np.empty(0, dtype=np.int16), np.empty(0, dtype=np.int64)
    valid = (fire_ids > 0) & (classes >= 0) & (classes < n_classes)
    if not valid.any():
        return np.zeros(n_fires, dtype=np.int16), np.zeros(n_fires, dtype=np.int64)
    code = fire_ids[valid].astype(np.int64) * n_classes + classes[valid].astype(np.int64)
    counts = np.bincount(code, minlength=(n_fires + 1) * n_classes)
    counts = counts.reshape(n_fires + 1, n_classes)
    # Empate: la clase más baja gana con argmax.
    majority = counts.argmax(axis=1).astype(np.int16)
    maximum = counts.max(axis=1).astype(np.int64)
    return majority[1:], maximum[1:]
