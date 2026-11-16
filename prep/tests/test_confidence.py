from __future__ import annotations

import pandas as pd
import pytest

from conftest import load_step


def _agg(index):
    return pd.DataFrame({
        "p_M": [0.44, 0.72, 0.44],
        "p_V": [0.55, 0.0, 0.0],
        "p_class_M": [0.55, 0.90, 0.55],
        "p_class_V": [0.55, 0.0, 0.0],
        "has_aqua": [0, 0, 1],
        "has_terra": [0, 1, 0],
        "has_viirs": [1, 0, 0],
    }, index=index)


def test_fire_confidence_cases(cfg):
    step = load_step("06_confidence.py")
    fires = pd.DataFrame({
        "incendio_id": ["mixed", "pre_viirs", "aqua_only"],
        "n_pasadas": [1, 1, 1],
        "area_pixeles_km2": [1.0, 1.0, 1.0],
        "t_inicio": pd.to_datetime(["2020-01-01", "2010-01-01", "2020-01-01"]),
        "n_hotspots_modis": [1, 1, 1],
        "n_hotspots_viirs": [1, 0, 0],
        "era": ["MODIS+VIIRS", "solo_MODIS", "MODIS+VIIRS"],
    })
    out = step.fire_confidence(fires, _agg(fires["incendio_id"]), cfg)
    vals = out.set_index("incendio_id")["confidence"]
    # noisy-OR: 1-(1-0.44)(1-0.55) = 0.748; f_size(1 km2)=0.9449
    assert vals["mixed"] == pytest.approx(100 * 0.748 * (0.85 + 0.15 * (1 - 2.718281828 ** -1)), rel=1e-3)
    assert vals["pre_viirs"] <= 72.0
    assert vals["aqua_only"] == pytest.approx(100 * 0.44 * (0.9449) * 0.70, rel=1e-3)
    assert vals["mixed"] > vals["aqua_only"]


def test_event_confidence_weighted():
    step = load_step("06_confidence.py")
    events = pd.DataFrame({"evento_id": ["E1"], "incendios_argentina": [2]})
    fires = pd.DataFrame({
        "incendio_id": ["A", "B"],
        "area_pixeles_km2": [1.0, 3.0],
        "confidence": [70.0, 30.0],
    })
    mapping = pd.DataFrame({"incendio_id": ["A", "B"], "evento_id": ["E1", "E1"]})
    out = step.event_confidence(events, fires, mapping)
    assert out.loc[0, "confidence"] == pytest.approx((70 * 1 + 30 * 3) / 4)
