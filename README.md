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

Más detalle en el [model card](MODEL_CARD.md), el
[diccionario de datos](DATA_DICTIONARY.md), los
[reportes de evaluación](results/report_val.md) y las
[fuentes de datos](DATA_SOURCES.md).

## Estructura

| Ruta | Descripción |
|---|---|
| `prep/` | Preprocesamiento FIRMS: hotspots → incendios → eventos, con polígonos y `confidence`. |
| `pred/` | Predicción de hotspots (CNN+LSTM, parches 32×32 a 1 km) y derivación clásica de incendios/eventos. |
| `pipeline/` | Descarga de datos crudos: FIRMS, POWER, ONI, FWI de Copernicus y límites IGN. |
| `webtool/` | App web funcional (Next.js 15 + MapLibre) con mapa, calendario y bitácora. |
| `webtool-idea/` | Prototipo estático de la interfaz (HTML/CSS/JS, datos de ejemplo). |
| `docs/` | Mapa interactivo (Leaflet) y dashboard exploratorio para GitHub Pages. |
| `results/` | Reportes, métricas, curvas y parquets de evaluación (validación y test). |
| `pred/data/models/best.pt` | Modelo entrenado usado en la predicción operativa (9.8 MB). |
| `pred/predictions/latest_2026-11-13/` | Predicción operativa 2026-11-14 → 2026-11-20 (GeoJSON + Parquet). |
| `DATA_DICTIONARY.md` | Esquema y significado de cada columna de los parquets. |
| `MODEL_CARD.md` | Arquitectura, datos, métricas y limitaciones del modelo. |
| `DATA_SOURCES.md` | Fuentes, licencias y créditos de los datos. |
| `Makefile` | Atajos para setup, descargas, pipelines, demo y tests. |

## Reproducir

### 0. Datos crudos

```bash
make pipeline-setup
cp .env.example .env       # completar MAP_KEY de FIRMS
make download              # límites IGN, FIRMS, POWER y ONI
make setup                 # crea prep/.venv y pred/.venv
make data-aux              # áreas protegidas, cobertura de suelo y auxiliares
make raw                   # data/processed/detections_raw.parquet
```

`make download` no incluye el FWI de Copernicus porque requiere una cuenta CDS.
Para agregarlo:

```bash
cd pipeline && ./.venv/bin/python download_copernicus.py
```

Ver [`pipeline/README.md`](pipeline/README.md) para el detalle de cada script,
las salidas y las claves necesarias.

### 1. Preprocesamiento

```bash
make prep
make test
```

Equivalente a `cd prep && make all`.

### 2. Predicción

```bash
make pred
```

Equivalente a `cd pred && make all`. Los pasos individuales están documentados
en [`pred/README.md`](pred/README.md).

### 3. Predicción operativa

```bash
cd pred
./.venv/bin/python src/10_predict_latest.py --config config/params.yaml
```

### 4. Demo local

```bash
make demo
# abrir http://localhost:8000
```

## Aplicación web

- **`webtool/`**: app funcional Next.js 15 + MapLibre (mapa, calendario y
  bitácora). Necesita Node.js 20+ y los datos generados por el pipeline
  (~760 MB en `webtool/public/data/`):

  ```bash
  make raw
  make prep
  make webtool-install
  make webtool-data
  make webtool
  # http://localhost:3000
  ```

  No corre en GitHub Pages porque usa un API route (`/api/entries`); para
  publicarla hace falta Vercel o un servidor Node. Ver
  [`webtool/README.md`](webtool/README.md).

- **`webtool-idea/`**: prototipo navegable sin build, con datos de ejemplo.
  Abrí `webtool-idea/index.html` o serví la carpeta:

  ```bash
  npx serve webtool-idea
  ```

## Datos no versionados

Los datos crudos e intermedios (~13 GB, más los entornos virtuales) no se suben
porque son públicos y regenerables:

- FIRMS (MODIS/VIIRS), NASA POWER, Open-Meteo, MCD12Q1 y límites IGN.
- `data/`, `prep/data/` y `pred/data/` se generan con `pipeline/` y los `make`
  de cada etapa.
- `webtool/public/data/` (~760 MB) se genera con `make webtool-data`.
- `.venv/` (15.6 GB) se recrea con `make setup`.

Esto mantiene el repositorio liviano (~17 MB) y reproducible.

## Entorno

- Python 3.12 (`uv`).
- PyTorch CUDA 12.4 (RTX 4060 Laptop, 8 GB) para `pred/`; RAPIDS opcional para `prep/`.
- Ver el `requirements.txt` de cada etapa y de `pipeline/`.

## Licencia

MIT. Ver [LICENSE](LICENSE) y [CITATION.cff](CITATION.cff).
