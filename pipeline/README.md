# pipeline — descarga de datos crudos

Scripts para bajar desde cero los datos públicos que consume `prep/`. Están
pensados para ejecutarse desde este repo y escriben en `data/`, que está
ignorado por git.

## Requisitos

- Python 3.11+.
- `geopandas` (para `download_climate.py`).
- `duckdb` (para `load_raw.py` y el build de datos de la web).
- `cdsapi` (solo para `download_copernicus.py`).
- Una API key de FIRMS para el año en curso (solo `download_api.py`).

```bash
cd pipeline
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
```

## Configuración

1. Copiá `.env.example` a `.env` en la raíz del repo:

   ```bash
   cp .env.example .env
   ```

2. Completá `MAP_KEY` con tu API key de FIRMS:
   https://firms.modaps.eosdis.nasa.gov/api/area/

3. Para FWI (opcional), configurá `~/.cdsapirc` con tu token de Copernicus CDS
   y aceptá la licencia del dataset `cems-fire-historical-v1`.

Los scripts cargan `.env` automáticamente mediante `common.load_env()`.

## Orden recomendado

```bash
cd pipeline

# 1. Límites oficiales del IGN (los necesita download_climate.py)
./.venv/bin/python download_boundaries.py

# 2. Archivos anuales por país de FIRMS (MODIS y VIIRS; sin API key)
./.venv/bin/python download_country.py

# 3. Año en curso por la Area API (requiere MAP_KEY)
./.venv/bin/python download_api.py

# 4. POWER diario por departamento + índice ONI
./.venv/bin/python download_climate.py

# 5. Unir los CSV de FIRMS en un parquet único (lo usa también la web)
./.venv/bin/python load_raw.py

# 6. Opcional: índices FWI de Copernicus (requiere cdsapi)
./.venv/bin/python download_copernicus.py
```

Todos los scripts son idempotentes: saltean los archivos que ya existen y
permiten refrescar solo lo nuevo.

## Salidas

| Script | Destino |
|---|---|
| `download_boundaries.py` | `data/boundaries/ign_{pais,provincia,departamento}.geojson` |
| `download_country.py` | `data/raw/firms/country/<producto>/<producto>_<año>_Argentina.csv` |
| `download_api.py` | `data/raw/firms/api/<SOURCE>/<SOURCE>_<inicio>_<dias>d.csv` |
| `download_climate.py` | `data/raw/climate/power/power_<lat>_<lon>.csv`, `data/raw/climate/oni.ascii.txt` |
| `load_raw.py` | `data/processed/detections_raw.parquet` (unión cruda de FIRMS) |
| `download_copernicus.py` | `data/raw/climate/fwi/fwi_<año>[_intermediate].nc` |

El volumen total ronda los **1–2 GB** según los años descargados. No se
versiona: el repo solo guarda código y resultados.

## Después de descargar

```bash
cd prep
make setup
make aux       # áreas protegidas, cobertura de suelo y auxiliares
make all       # pipeline completo FIRMS 2000-2026
```

`load_raw.py` genera `data/processed/detections_raw.parquet`, que también usa
`webtool/scripts/build_data.py` para la app web.

Ver el [README principal](../README.md) y el
[diccionario de datos](../DATA_DICTIONARY.md).
