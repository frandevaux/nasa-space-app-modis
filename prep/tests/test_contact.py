from __future__ import annotations

import numpy as np
import pytest
import shapely

from geo import build_circles, radius_m, union_fire_polygons


def test_radius_thresholds():
    r_modis = radius_m([1.0], [1.0])[0]
    r_viirs = radius_m([0.375], [0.375])[0]
    r_edge = radius_m([4.8], [2.0])[0]
    assert r_modis == pytest.approx(707.10678, rel=1e-6)
    assert 2 * r_modis == pytest.approx(1414.21356, rel=1e-6)
    assert 2 * r_viirs == pytest.approx(530.33008, rel=1e-6)
    assert r_modis + r_viirs == pytest.approx(972.27186, rel=1e-6)
    assert 2 * r_edge == pytest.approx(5200.0, rel=1e-9)


def test_tangent_circles_union_to_one_polygon():
    r = 707.10678
    circles = build_circles(np.array([0.0, 2 * r]), np.array([0.0, 0.0]),
                            np.array([r, r]))
    union = shapely.union_all(circles)
    assert union.geom_type == "Polygon"


def test_gap_keeps_two_polygons():
    r = 707.10678
    circles = build_circles(np.array([0.0, 2 * r + 100.0]), np.array([0.0, 0.0]),
                            np.array([r, r]))
    union = shapely.union_all(circles)
    assert union.geom_type == "MultiPolygon"


def test_union_fire_polygons_one_fire():
    r = 707.10678
    x = np.array([0.0, 2 * r])
    y = np.array([0.0, 0.0])
    radii = np.array([r, r])
    circles = build_circles(x, y, radii)
    wkbs, audit = union_fire_polygons(circles, np.array([0, 0]))
    assert len(wkbs) == 1 and wkbs[0] is not None
    geom = shapely.from_wkb(wkbs[0])
    assert geom.geom_type == "Polygon"
    assert geom.is_valid
    assert audit["fires"] == 1


def test_union_fire_polygons_detects_gap():
    r = 707.10678
    circles = build_circles(np.array([0.0, 2 * r + 100.0]), np.array([0.0, 0.0]),
                            np.array([r, r]))
    with pytest.raises(Exception):
        union_fire_polygons(circles, np.array([0, 0]), on_failure="raise")
