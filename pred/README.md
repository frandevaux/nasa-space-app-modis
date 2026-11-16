# pred — predicción de hotspots (Córdoba, 1 km)

Etapa de predicción del proyecto. **Trabaja solo con hotspots**: no usa
incendios ni eventos como entidad ni como features. Predice hotspots futuros
en los 7 días posteriores a un hotspot ancla y, después, deriva incendios y
eventos con la lógica clásica de `prep/` (`04_fires.py` y `05_events.py`).

## Entorno

- Python 3.12 en `.venv` (uv).
- PyTorch CUDA 12.4 para la RTX 4060 Laptop (8 GB).
- Datos de entrada de `../prep/data/processed`, `../data/raw/climate/power`,
  `../data/boundaries` y `../data/raw/landcover/Geotiff`.

```bash
make setup          # crea .venv e instala deps + torch cu124
make gpu-check      # verifica CUDA
```

## Flujo

```bash
make inventory      # valida insumos y filtros Córdoba
make static         # rasters Córdoba 1 km (máscara, deptos, landcover, AP, climatología)
make hotspots       # muestras de hotspots + forecast 7d por localidad
make patches        # índice, hotspots largos, clima, stats
make train          # CNN+LSTM, train 2019-jul 2025 / val ago 2025-jul 2026
make tensorboard    # métricas y visualizaciones en vivo
make eval           # métricas hotspot + derivación clásica + baselines (val)
make classic        # hotspots predichos -> incendios/eventos clásicos
make report         # report_val.md
make smoke          # corrida chica end-to-end
make test           # pytest

# Evaluación de test (ago-nov 2026)
./.venv/bin/python src/07_evaluate.py --config config/params.yaml --split test

# Predicción operativa con los últimos hotspots + Open-Meteo
./.venv/bin/python src/10_predict_latest.py --config config/params.yaml
```

## Datos

- **Entrada**: `prep/data/processed/hotspots.parquet` (6.4 M puntos de FIRMS).
- **Períodos**:
  - Train: 2019-01-01 → 2025-07-24 (32.661 muestras; 91.074 hotspots deduplicados por celda-día).
  - Validación: 2025-08-01 → 2026-07-24 (2.913 muestras).
  - Test: 2026-08-01 → 2026-11-07 (1.145 muestras).
- **Salida del modelo**: probabilidad de hotspot por celda de 1 km y día
  futuro (7 días).
- **Post-procesamiento clásico**: los hotspots predichos se agrupan en
  incendios (contacto de píxeles, `04_fires.py`) y en eventos (buffer 1/5 km,
  ventana 5 días, `05_events.py`). La comparación con los incendios/eventos
  reales es posterior y no forma parte del entrenamiento.

## Notas

- El clima de entrenamiento es POWER observado (proxy de pronóstico); las
  métricas de validación son optimistas. En inferencia operativa se usa
  Open-Meteo para los 7 días futuros y POWER para la historia; si falta una
  variable/día, se rellena con la última observación (`10_predict_latest.py`).
- El parche es de 32×32 celdas de 1 km (±16 km) alrededor del hotspot ancla.
- Una muestra por hotspot; `dataset.dedup_cell_day: true` deduplica a una por
  celda-día para reducir parches casi idénticos.
- No se modifican `prep/` ni sus datos.
