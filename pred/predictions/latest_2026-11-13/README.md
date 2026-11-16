# Predicción operativa — Córdoba, 2026-11-14 a 2026-11-20

Generada con `src/10_predict_latest.py` a partir de los últimos hotspots
disponibles en Córdoba.

- **T0 / último dato**: 2026-11-13 (25 hotspots; 15 celdas-día ancla).
- **Horizonte**: 7 días, 2026-11-14 a 2026-11-20.
- **Modelo**: `data/models/best.pt`, época 5, entrenado con train 2019-01-01
  a 2025-07-24 y validación 2025-08-01 a 2026-07-24 (solo Córdoba, 1 km).
- **Clima**: POWER observado para la historia y **Open-Meteo** para los 7 días
  futuros. Si falta una variable/día se rellena con la última observación.
- **Umbral**: 0.8 de probabilidad; presupuesto máximo 200 hotspots/día (no se
  alcanzó: el día más cargado tuvo 93).
- **Resultados**: 271 hotspots, 131 incendios clásicos, 20 eventos clásicos.

Archivos:
- `predicted_hotspots.parquet` / `.geojson`: hotspots predichos (lat/lon, prob, fecha, lead).
- `predicted_fires.parquet` / `.geojson`: incendios clásicos (contacto de píxeles).
- `predicted_events.parquet` / `.geojson`: eventos clásicos (buffer/ventana de 5 días).
- `summary.json`: parámetros y conteos.
