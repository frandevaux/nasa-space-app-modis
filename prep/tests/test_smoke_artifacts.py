from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import shapely

PREP = Path(__file__).resolve().parents[1]
SMOKE = PREP / "data" / "smoke" / "archive_2025"

pytestmark = pytest.mark.skipif(not SMOKE.exists(), reason="smoke 2025 no generado")


def test_smoke_counts_and_integrity():
    fires = pd.read_parquet(SMOKE / "interim" / "06_incendios_final.parquet")
    events = pd.read_parquet(SMOKE / "interim" / "06_eventos_final.parquet")
    hs = pd.read_parquet(SMOKE / "interim" / "06_hotspots_final.parquet")
    mapping = pd.read_parquet(SMOKE / "interim" / "05_fire_event_map.parquet")
    assert len(fires) > 0 and len(events) > 0 and len(hs) > 0
    assert fires["confidence"].between(0, 100).all()
    assert events["confidence"].between(0, 100).all()
    assert hs["incendio_id"].notna().all()
    assert hs["evento_id"].notna().all()
    assert mapping["incendio_id"].is_unique
    assert set(mapping["incendio_id"]) == set(fires["incendio_id"])
    fg = shapely.from_wkb(fires["geometry_wkb"].tolist())
    eg = shapely.from_wkb(events["geometry_wkb"].tolist())
    assert shapely.is_valid(fg).all() and shapely.is_valid(eg).all()
    assert (shapely.get_type_id(fg) == 3).all()
    assert set(shapely.get_type_id(eg).tolist()) <= {3, 6}
    pre = fires[fires["era"] == "solo_MODIS"]
    if len(pre):
        assert pre["confidence"].max() <= 72.0 + 1e-6
