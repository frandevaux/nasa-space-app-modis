# Diccionario de datos

Convenciones generales:

- **Coordenadas geográficas:** WGS84 (`EPSG:4326`), grados decimales.
- **Coordenadas proyectadas:** `EPSG:6933`, metros.
- **Tiempos:** UTC salvo `ts_local`.
- **Probabilidades:** `0–1`. **Confianza:** `0–100`.
- **Áreas:** km². **FRP:** MW. **Brillo:** K.
- Los valores faltantes se representan como `NaN`/`null`.
- Los IDs (`hotspot_id`, `incendio_id`, `evento_id`) son estables y
  determinísticos.

## 1. Hotspots — `prep/data/processed/hotspots.parquet`

6.426.755 filas. Es la entidad base: cada fila es un hotspot de FIRMS ya
normalizado, clasificado y agrupado.

| Columna | Tipo | Descripción |
|---|---|---|
| `source_group` | string | Grupo de origen: `country_*` (archivo anual) o `api_*` (Area API). |
| `source` | string | Fuente FIRMS (`MODIS_SP`, `VIIRS_SNPP_NRT`, etc.). |
| `sensor` | string | Sensor (MODIS, VIIRS). |
| `product` | string | Producto FIRMS. |
| `priority` | int64 | Prioridad al deduplicar registros de distintas fuentes. |
| `source_file` | string | Archivo CSV de origen. |
| `source_row` | int64 | Fila dentro del CSV de origen. |
| `latitude` | double | Latitud WGS84. |
| `longitude` | double | Longitud WGS84. |
| `ts_utc` | timestamp[us] | Fecha y hora de adquisición en UTC. |
| `ts_local` | timestamp[us] | Fecha y hora local (America/Argentina). |
| `satellite` | string | Satélite. |
| `instrument` | string | Instrumento. |
| `daynight` | string | `D` (día) o `N` (noche). |
| `scan_km` | double | Tamaño de píxel en la dirección de escaneo. |
| `track_km` | double | Tamaño de píxel en la dirección de órbita. |
| `bright_main` | double | Temperatura de brillo principal (K). |
| `bright_aux` | double | Temperatura de brillo auxiliar (K). |
| `frp` | double | Fire Radiative Power (MW). |
| `conf_raw` | string | Confianza original de FIRMS. |
| `version` | string | Versión del producto. |
| `type` | int64 | Tipo FIRMS: `0` vegetación; otros valores se descartan. |
| `acq_date` | string | Fecha original de adquisición (`YYYY-MM-DD`). |
| `acq_time` | string | Hora original de adquisición (`HHMM`). |
| `type_inferred` | bool | `true` si `type` se infirió (datos NRT). |
| `x` | double | Coordenada X proyectada (EPSG:6933). |
| `y` | double | Coordenada Y proyectada (EPSG:6933). |
| `r_m` | double | Radio efectivo del píxel en metros. |
| `hotspot_id` | string | ID estable del hotspot. |
| `hotspot_pk` | int64 | Clave entera del hotspot. |
| `conf_class` | string | Clase de confianza: `l` (low), `n` (nominal), `h` (high). |
| `conf_numeric` | double | Confianza normalizada a partir de `conf_class`/`conf_raw`. |
| `pass_bin` | string | Pasada de 12 h (`YYYY-MM-DD_D` o `YYYY-MM-DD_N`). |
| `bin_start_utc` | timestamp[ns] | Inicio de la ventana de 12 h. |
| `bin_end_utc` | timestamp[ns] | Fin de la ventana de 12 h. |
| `era` | string | `solo_MODIS` o `MODIS+VIIRS` según disponibilidad temporal. |
| `terra_post_standby` | bool | `true` si Terra estaba en modo standby. |
| `incendio_id` | string | Incendio al que pertenece el hotspot. |
| `evento_id` | string | Evento al que pertenece el hotspot. |
| `confidence_incendio` | double | Confianza del incendio asociado. |
| `confidence_evento` | double | Confianza del evento asociado. |

## 2. Incendios — `prep/data/processed/incendios.parquet`

1.952.801 filas. Cluster espacial de hotspots dentro de una pasada de 12 h.

| Columna | Tipo | Descripción |
|---|---|---|
| `incendio_id` | string | ID del incendio. |
| `pass_bin` | string | Pasada de 12 h. |
| `t_inicio` | timestamp[us] | Inicio del incendio. |
| `t_fin` | timestamp[us] | Fin del incendio. |
| `n_hotspots` | int64 | Hotspots totales. |
| `n_hotspots_modis` | int64 | Hotspots MODIS. |
| `n_hotspots_viirs` | int64 | Hotspots VIIRS. |
| `sensores_presentes` | string | Sensores presentes. |
| `satelites_presentes` | string | Satélites presentes. |
| `n_pasadas` | int64 | Pasadas involucradas. |
| `n_satelites` | int64 | Satélites involucrados. |
| `area_pixeles_km2` | double | Área estimada por píxeles (km²). |
| `area_poligono_km2` | double | Área del polígono (km²). |
| `frp_sum` | double | Suma de FRP de los hotspots (MW). |
| `centroid_x` | double | Centroide X (EPSG:6933). |
| `centroid_y` | double | Centroide Y (EPSG:6933). |
| `en_argentina` | bool | `true` si el incendio está en Argentina. |
| `en_area_protegida` | bool | `true` si intersecta un área protegida. |
| `ap_gids` | string | IDs de áreas protegidas intersectadas. |
| `ap_nombres` | string | Nombres de áreas protegidas intersectadas. |
| `era` | string | Era del sensor. |
| `lc_clase` | int16 | Clase de cobertura MCD12Q1. |
| `lc_anio_usado` | int16 | Año de cobertura usado. |
| `lc_anio_exacto` | bool | `true` si existía el año exacto de cobertura. |
| `lc_metodo` | string | Método de asignación de cobertura. |
| `es_bosque` | bool | `true` si la clase es bosque. |
| `p_M`, `p_V` | double | Probabilidades/componentes MODIS y VIIRS de la confianza. |
| `p_class_M`, `p_class_V` | double | Componentes por clase de confianza. |
| `has_aqua`, `has_terra`, `has_viirs` | int8 | Flags de satélites presentes. |
| `P_base` | double | Confianza base antes de ajustes. |
| `k_pasadas` | double | Factor por cantidad de pasadas. |
| `f_size` | double | Factor por tamaño. |
| `f_miss` | double | Factor por detecciones faltantes. |
| `confidence` | double | Confianza final (0–100). |
| `pre_viirs` | bool | `true` si el incendio es anterior a VIIRS. |
| `evento_id` | string | Evento asociado. |
| `geometry_wkt` | string | Polígono del incendio en WKT (EPSG:4326). |
| `centroid_lon` | double | Longitud del centroide (WGS84). |
| `centroid_lat` | double | Latitud del centroide (WGS84). |

La lógica de estas columnas está en `prep/src/04_fires.py` y
`prep/src/06_confidence.py`.

## 3. Eventos — `prep/data/processed/eventos.parquet`

1.187.021 filas. Unión temporal y espacial de incendios (buffer y ventana de
5 días).

| Columna | Tipo | Descripción |
|---|---|---|
| `evento_id` | string | ID del evento. |
| `inicio` | timestamp[ns] | Inicio del evento. |
| `fin` | timestamp[ns] | Fin del evento. |
| `duracion_dias` | double | Duración en días. |
| `n_incendios` | int64 | Incendios del evento. |
| `n_incendios_total` | int64 | Incendios totales antes de filtros. |
| `incendios_argentina` | int64 | Incendios en Argentina. |
| `n_pass_bins_activos` | int64 | Pasadas activas. |
| `area_pixeles_km2` | double | Área por píxeles (km²). |
| `area_poligono_km2` | double | Área del polígono (km²). |
| `en_area_protegida` | bool | `true` si intersecta un área protegida. |
| `es_bosque` | bool | `true` si la cobertura es bosque. |
| `buffer_km` | double | Buffer usado para unir incendios. |
| `lc_clase` | int64 | Clase de cobertura MCD12Q1. |
| `lc_metodo` | string | Método de asignación de cobertura. |
| `incendios` | string | IDs de incendios separados por coma. |
| `confidence` | double | Confianza final (0–100). |
| `confidence_min` | double | Confianza mínima de sus incendios. |
| `confidence_max` | double | Confianza máxima de sus incendios. |
| `geometry_wkt` | string | Polígono del evento en WKT (EPSG:4326). |
| `centroid_lon` | double | Longitud del centroide (WGS84). |
| `centroid_lat` | double | Latitud del centroide (WGS84). |

La lógica está en `prep/src/05_events.py`.

## 4. Predicción operativa — `pred/predictions/latest_2026-11-13/`

| Archivo | Filas | Columnas |
|---|---:|---|
| `predicted_hotspots.parquet` | 271 | `date` (string `YYYY-MM-DD`), `lat`, `lon`, `prob` (0–1), `lead` (1–7), `row`, `col` (celda de la grilla). |
| `predicted_fires.parquet` | 131 | `incendio_id`, `pass_bin`, `t_inicio`, `t_fin`, `n_hotspots`, `area_pixeles_km2`, `confidence`, `centroid_lon`, `centroid_lat`, `day`. |
| `predicted_events.parquet` | 20 | `evento_id`, `inicio`, `fin`, `n_incendios`, `area_pixeles_km2`, `confidence`, `centroid_lon`, `centroid_lat`, `incendios`. |

Los `.geojson` equivalentes tienen geometrías `Point` y las mismas
propiedades. `summary.json` resume la corrida (fecha ancla, días, conteos,
umbral y proveedor de clima).

## 5. Resultados de evaluación — `results/`

Mismos esquemas que la predicción operativa, con dos diferencias:

- `predicted_hotspots_{val,test}.parquet` agregan `hotspot_ancla` (ID del
  hotspot ancla) y `anchor_idx` (índice del ancla).
- Las columnas `date` son strings `YYYY-MM-DD`.

| Archivo | Filas |
|---|---:|
| `predicted_hotspots_val.parquet` | 54.572 |
| `predicted_fires_val.parquet` | 12.619 |
| `predicted_events_val.parquet` | 1.015 |
| `predicted_hotspots_test.parquet` | 17.945 |
| `predicted_fires_test.parquet` | 3.245 |
| `predicted_events_test.parquet` | 221 |

## 6. Intermedios útiles

### `data/processed/detections_raw.parquet`

6.868.982 filas. Unión cruda de los CSV de FIRMS, sin agrupar:

`latitude`, `longitude`, `bright_main`, `bright_aux`, `scan`, `track`,
`acq_date`, `acq_time`, `satellite`, `instrument`, `confidence`, `version`,
`frp`, `daynight`, `type`, `product`, `origin`, `is_nrt`.

### `pred/data/hotspots/hotspot_forecast_7d.parquet`

257.033 filas. Pronóstico meteorológico de los 7 días posteriores a cada
hotspot ancla:

`anchor_idx`, `hotspot_pk`, `hotspot_id`, `t0`, `lead`, `date`, `T2M`,
`T2M_MAX`, `RH2M`, `PRECTOTCORR`, `WS10M_MAX`, `GWETTOP`, `vpd`,
`days_since_rain`, `precip_7d`, `precip_30d`.

## 7. Cómo inspeccionar

```python
import pandas as pd

df = pd.read_parquet("pred/predictions/latest_2026-11-13/predicted_hotspots.parquet")
print(df.head())
print(df.dtypes)
```

Para los GeoJSON:

```python
import json

with open("pred/predictions/latest_2026-11-13/predicted_hotspots.geojson") as f:
    data = json.load(f)
print(len(data["features"]))
print(data["features"][0]["properties"])
```
