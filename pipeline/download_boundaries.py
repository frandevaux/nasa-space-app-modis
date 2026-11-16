"""Descarga los límites oficiales del IGN (país, provincias, departamentos) como GeoJSON.

Uso:  python3 pipeline/download_boundaries.py
Destino: data/boundaries/ign_<capa>.geojson  (no versionado; ~400 MB)
"""
from __future__ import annotations

import json
import urllib.parse

from common import ROOT, fetch

WFS = "https://wms.ign.gob.ar/geoserver/ows"
LAYERS = ["pais", "provincia", "departamento"]


def main() -> None:
    out = ROOT / "data" / "boundaries"
    for layer in LAYERS:
        q = urllib.parse.urlencode({
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": f"ign:{layer}", "outputFormat": "application/json", "srsName": "EPSG:4326",
        })
        dest = out / f"ign_{layer}.geojson"
        n = fetch(f"{WFS}?{q}", dest, timeout=600)
        feats = json.loads(dest.read_text())["features"]
        print(f"ok  {dest.name}  {n/1e6:.1f} MB  {len(feats)} features", flush=True)


if __name__ == "__main__":
    main()
