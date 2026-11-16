"""IDs determinísticos por contenido (blake2b, 20 caracteres hex).

- HS-...  hotspot: (satellite, lat, lon, ts_utc)
- INC-... incendio: (pass_bin, miembros ordenados)
- EVT-... evento: (incendio semilla, ts del semilla)

Los IDs no dependen del orden de lectura ni del número de corrida.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Iterable

import pandas as pd

HEX_CHARS = 20


def _digest(text: str, chars: int = HEX_CHARS) -> str:
    raw = hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()
    return raw[:chars]


def _fmt_float(value: float) -> str:
    # Normaliza -0.0 y fija 6 decimales (~0.1 m en lat/lon).
    value = 0.0 if abs(float(value)) < 1e-12 else float(value)
    return f"{value:.6f}"


def _fmt_ts(value: datetime | str | pd.Timestamp) -> str:
    ts = pd.Timestamp(value)
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def hotspot_id(satellite: str, lat: float, lon: float,
               ts_utc: datetime | str | pd.Timestamp) -> str:
    text = "v1|{}|{}|{}|{}".format(satellite, _fmt_float(lat), _fmt_float(lon), _fmt_ts(ts_utc))
    return "HS-" + _digest(text)


def fire_id(pass_bin: str, member_hotspot_ids: Iterable[str]) -> str:
    members = ",".join(sorted(member_hotspot_ids))
    text = f"v1|{pass_bin}|{members}"
    return "INC-" + _digest(text)


def event_id(seed_fire_id: str, seed_ts: datetime | str | pd.Timestamp) -> str:
    text = f"v1|{seed_fire_id}|{_fmt_ts(seed_ts)}"
    return "EVT-" + _digest(text)


def stable_int(value: str, bits: int = 63) -> int:
    """Entero estable a partir de un ID, para joins compactos."""
    raw = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(raw, "big") & ((1 << bits) - 1)
