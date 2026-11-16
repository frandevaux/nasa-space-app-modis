# NASA Space Apps — Predicción de hotspots MODIS/VIIRS (Córdoba)

Pipeline de preprocesamiento y predicción de hotspots de incendios a 7 días para
Córdoba, Argentina, usando datos públicos de NASA FIRMS, NASA POWER,
Open-Meteo, MCD12Q1 y límites IGN.

## Estructura

| Ruta | Descripción |
|---|---|
| `prep/` | Preprocesamiento FIRMS: hotspots → incendios → eventos, con polígonos y `confidence`. |
| `pred/` | Predicción de hotspots (CNN+LSTM, parches 32×32 a 1 km) y derivación clásica de incendios/eventos. |
| `pred/data/models/best.pt` | Modelo entrenado usado en la predicción operativa (9.8 MB). |
| `pred/predictions/latest_2026-11-13/` | Predicción operativa 2026-11-14 → 2026-11-20 (GeoJSON + Parquet). |

## Resultado

La predicción operativa está en `pred/predictions/latest_2026-11-13/`:

- `predicted_hotspots.geojson` / `.parquet`
- `predicted_fires.geojson` / `.parquet`
- `predicted_events.geojson` / `.parquet`
- `summary.json` y `README.md`

## Reproducir

### 1. Preprocesamiento

```bash
cd prep
make setup
make aux          # auxiliares (AP, boundaries, landcover)
make all          # corrida completa 2000-2026
make test
```

### 2. Predicción

```bash
cd pred
make setup
make inventory
make static
make hotspots
make patches
make train
make eval
make classic
make report
```

### 3. Predicción operativa

```bash
cd pred
./.venv/bin/python src/10_predict_latest.py --config config/params.yaml
```

## Datos no versionados

Los datos crudos e intermedios (~32 GB) no se suben porque son públicos y
regenerables:

- FIRMS (MODIS/VIIRS), NASA POWER, Open-Meteo, MCD12Q1 y límites IGN.
- `prep/data/` y `pred/data/` se generan con los `make` de cada etapa.
- `.venv/` (15.6 GB) se recrea con `make setup`.

Esto mantiene el repositorio liviano (~11 MB) y reproducible.

## Entorno

- Python 3.12 (`uv`).
- PyTorch CUDA 12.4 (RTX 4060 Laptop, 8 GB) para `pred/`; RAPIDS opcional para `prep/`.
- Ver el `requirements.txt` de cada etapa.
