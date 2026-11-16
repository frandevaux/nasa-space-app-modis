# prep — preprocesamiento FIRMS

Workspace aislado para el pipeline FIRMS: hotspots MODIS/VIIRS →
incendios → eventos, con polígonos y `confidence`. No modifica `src/` ni
`data/` del resto del repo.

## Estructura

```
config/params.yaml       umbrales, pesos, rutas y períodos operativos
src/00_fetch_aux.py      AP desde la rama RaMarti + boundaries + MCD12Q1
src/01_ingest.py         CSV -> esquema unificado
src/02_clean.py          dedup + type + inferencia NRT
src/03_conf_class.py     conf_class, pass_bin, proyección y radios
src/04_fires.py          clustering, polígonos, AP/bosque
src/05_events.py         eventos FEDS (1/5 km, 5 días)
src/06_confidence.py     métrica §4.8
src/07_export.py         parquet WGS84 + GeoPackage + report.md
tests/                   suite pytest
data/                    intermedios y salidas (no versionados)
```

## Entorno

- Python 3.12 en `prep/.venv` (RAPIDS no publica para 3.14).
- Stack CPU: duckdb, pandas, pyarrow, scipy, shapely, pyproj, pyogrio,
  geopandas, rasterio, pyyaml, pytest.
- Stack GPU opcional: RAPIDS 25.04 (`cuml-cu12`, `cudf-cu12`,
  `cugraph-cu12`, `cuspatial-cu12`) + `nvidia-cuda-runtime-cu12`.
- Instalación: `make setup` (requiere `uv`).

## Uso

```bash
make aux              # trae AP de RaMarti y valida auxiliares
make smoke-archive    # 2025 completo, salidas en data/smoke/archive_2025/
make smoke-api        # slice API 2026-07/08 (SP+NRT, inferencia type)
make test             # pytest
make all              # corrida completa 2000-2026
```

La corrida completa tarda ~1-2 h en CPU, con pico <6 GB de RAM y ~6-12 GB de
salidas. El smoke 2025 tarda ~5 min y no pisa las salidas completas.

## GPU

`gpu.enabled: false` por defecto. El benchmark del 2026-11-15 sobre bins
reales dio CPU 9 ms vs GPU 220-1000 ms; kNN CPU 0.10 s vs GPU 0.33 s;
cuSpatial point-in-polygon CPU 0.72 s vs GPU 2.39 s. Se deja la capa GPU
implementada y validada (`make gpu-check`, `--gpu`), pero el preprocesamiento
va en CPU. La GPU se aprovechará en la etapa de predicción.

## Salidas

- `data/processed/hotspots.parquet`
- `data/processed/incendios.parquet`
- `data/processed/eventos.parquet`
- `data/qgis/fuego.gpkg` con capas `areas_protegidas_ign`,
  `limites_provincia`, `eventos`, `incendios`, `hotspots`
- `report.md` con conteos, QC y benchmark

## Notas

- La capa `ign_area_protegida` se extrae de `origin/RaMarti` con
  `git fetch` + `git show`; no se descarga del WFS.
- Los archivos `._*` de macOS se excluyen explícitamente.
- Los NRT no traen `type`: se infiere con una ventana de 365 días y contacto
  de píxeles.
- `area_pixeles_km2 > area_poligono_km2` en ~20 % de los incendios es
  esperado (círculos superpuestos); se reporta como métrica, no como fallo.
