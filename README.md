# NASA Space Apps — Predicción de hotspots MODIS/VIIRS (Córdoba)

Pipeline de preprocesamiento y predicción de hotspots de incendios a 7 días para
Córdoba, Argentina, usando datos públicos de NASA FIRMS, NASA POWER,
Open-Meteo, MCD12Q1 y límites IGN.

## Demo

- **Mapa interactivo:** https://frandevaux.github.io/nasa-space-app-modis/
- **Análisis exploratorio:** https://frandevaux.github.io/nasa-space-app-modis/eda/

## Resultados

Predicción operativa del 2026-11-13 para el 2026-11-14 → 2026-11-20:
**271 hotspots, 131 incendios y 20 eventos** derivados. Ver
[`pred/predictions/latest_2026-11-13/`](pred/predictions/latest_2026-11-13/)
y [`results/`](results/).

| Métrica | Validación | Test |
|---|---:|---:|
| ROC-AUC | 0,8560 | 0,8374 |
| PR-AUC | 0,0122 | 0,0090 |
| Brier | 0,1015 | 0,1267 |
| Recall @ 0,5 | 0,6454 | 0,6714 |
| Patch hit rate | 0,7687 | 0,7924 |
| PR-AUC persistencia | 0,0068 | 0,0027 |
| PR-AUC climatología | 0,0041 | 0,0063 |

Más detalle en el [model card](MODEL_CARD.md), los
[reportes de evaluación](results/report_val.md) y las
[fuentes de datos](DATA_SOURCES.md).

## Estructura

| Ruta | Descripción |
|---|---|
| `prep/` | Preprocesamiento FIRMS: hotspots → incendios → eventos, con polígonos y `confidence`. |
| `pred/` | Predicción de hotspots (CNN+LSTM, parches 32×32 a 1 km) y derivación clásica de incendios/eventos. |
| `pred/data/models/best.pt` | Modelo entrenado usado en la predicción operativa (9.8 MB). |
| `pred/predictions/latest_2026-11-13/` | Predicción operativa 2026-11-14 → 2026-11-20 (GeoJSON + Parquet). |
| `docs/` | Mapa interactivo (Leaflet) y dashboard exploratorio para GitHub Pages. |
| `results/` | Reportes, métricas, curvas y parquets de evaluación (validación y test). |
| `MODEL_CARD.md` | Arquitectura, datos, métricas y limitaciones del modelo. |
| `DATA_SOURCES.md` | Fuentes, licencias y créditos de los datos. |

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

### 4. Demo local

```bash
python3 -m http.server 8000 --directory docs
# abrir http://localhost:8000
```

## Datos no versionados

Los datos crudos e intermedios (~32 GB) no se suben porque son públicos y
regenerables:

- FIRMS (MODIS/VIIRS), NASA POWER, Open-Meteo, MCD12Q1 y límites IGN.
- `prep/data/` y `pred/data/` se generan con los `make` de cada etapa.
- `.venv/` (15.6 GB) se recrea con `make setup`.

Esto mantiene el repositorio liviano (~15 MB) y reproducible.

## Entorno

- Python 3.12 (`uv`).
- PyTorch CUDA 12.4 (RTX 4060 Laptop, 8 GB) para `pred/`; RAPIDS opcional para `prep/`.
- Ver el `requirements.txt` de cada etapa.

## Licencia

MIT. Ver [LICENSE](LICENSE) y [CITATION.cff](CITATION.cff).
