from __future__ import annotations

import pandas as pd

import ids


def test_hotspot_id_stable_and_unique():
    a = ids.hotspot_id("SNPP", -34.123456, -58.654321, pd.Timestamp("2025-01-01 12:00"))
    b = ids.hotspot_id("SNPP", -34.123456, -58.654321, pd.Timestamp("2025-01-01 12:00"))
    c = ids.hotspot_id("Terra", -34.123456, -58.654321, pd.Timestamp("2025-01-01 12:00"))
    assert a == b
    assert a != c
    assert a.startswith("HS-")


def test_fire_id_order_independent():
    members = ["HS-b", "HS-a", "HS-c"]
    assert ids.fire_id("2025-01-01_D", members) == ids.fire_id("2025-01-01_D", reversed(members))
    assert ids.fire_id("2025-01-01_D", members) != ids.fire_id("2025-01-02_D", members)


def test_event_id_stable():
    a = ids.event_id("INC-x", pd.Timestamp("2025-01-01 12:00"))
    b = ids.event_id("INC-x", pd.Timestamp("2025-01-01 12:00"))
    assert a == b and a.startswith("EVT-")
