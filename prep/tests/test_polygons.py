from __future__ import annotations

import numpy as np
import pytest
import shapely

from geo import build_circles, majority_class, union_fire_polygons


def test_single_hotspot_polygon():
    circles = build_circles(np.array([0.0]), np.array([0.0]), np.array([707.0]))
    wkbs, audit = union_fire_polygons(circles, np.array([0]))
    assert wkbs[0] is not None
    geom = shapely.from_wkb(wkbs[0])
    assert geom.geom_type == "Polygon" and geom.is_valid


def test_overlapping_circles_area_is_less_than_sum():
    r = 707.0
    circles = build_circles(np.array([0.0, 200.0]), np.array([0.0, 0.0]),
                            np.array([r, r]))
    union_area = shapely.area(shapely.union_all(circles))
    sum_area = 2 * shapely.area(circles[0])
    assert union_area < sum_area


def test_majority_class_and_tie():
    fire_ids = np.array([1, 1, 1, 2, 2], dtype=np.int64)
    classes = np.array([1, 5, 5, 2, 3], dtype=np.int16)
    majority, counts = majority_class(fire_ids, classes, n_classes=32)
    assert majority.tolist() == [5, 2]
    assert counts.tolist() == [2, 1]
