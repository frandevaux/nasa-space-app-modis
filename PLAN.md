# PLAN — Preprocesamiento y armonización de hotspots MODIS + VIIRS

> **Alcance**: solo preprocesamiento. El resultado son hotspots, incendios y eventos agrupados, con polígonos de límite y `confidence`, listos para la etapa de predicción (que no forma parte de este plan).
> Las referencias entre corchetes ([S1], [S2]…) apuntan a la sección **Fuentes** al final.

---

## 1. Objetivo

Pasar de los hotspots crudos de FIRMS (MODIS 2000–2026 y VIIRS 2012–2026) a tres entidades jerárquicas.
- **Incendios y eventos** llevan una métrica nueva `confidence` (%), calculada con **ambos satélites**, y las **coordenadas de su límite** (polígono).
- **Los hotspots mantienen su formato original de FIRMS** (T23): no se les calcula ninguna confianza nueva.

```
EVENTO (tiempo)         inicio, fin, confidence, incendios[], polígono (unión de sus incendios)
  └─ INCENDIO (espacio) hotspots[], confidence, polígono (unión de círculos)   ← cluster dentro de una pasada de 12 h
       └─ HOTSPOT       columnas originales de FIRMS + incendio_id, evento_id   ← sin confianza nueva
```

Las salidas se pueden verificar en QGIS.

## 2. Decisiones del equipo

| # | Decisión |
|---|----------|
| T1 | Solo vegetación: se conserva `type == 0` y se descarta todo `type != 0` (volcanes, fuentes estáticas o fábricas, offshore). |
| T2 | La confianza original de cada sensor **no se modifica**. Se agrega una columna nueva `confidence` basada en ambos satélites. |
| T3 | **Miembros mixtos**: un incendio puede contener hotspots MODIS y VIIRS. |
| T4 | **Incendio = cluster espacial dentro de una pasada / ventana de 12 h**, igual que NASA FEDS [S5]. |
| T5 | **Evento = incendios unidos por tiempo y cercanía espacial**, al estilo FEDS [S5]. |
| T6 | Los hotspots NRT no traen `type`: se **infiere** a partir del histórico (T22). |
| T7 | La distancia respeta la resolución original de cada sensor (MODIS ≈ 1 km, VIIRS ≈ 375 m), generalizada con el tamaño real del píxel (T11). MODIS se penaliza en `confidence` por ser menos preciso. |
| T8 | **VIIRS es la referencia a futuro**: MODIS se lleva a las clases de VIIRS (`l` / `n` / `h`), no al revés. |
| T9 | MODIS → `l` / `n` / `h` con los **umbrales oficiales de NASA, sin calibración empírica**: `0 ≤ C < 30 → l`, `30 ≤ C < 80 → n`, `80 ≤ C ≤ 100 → h` (Tabla 11 de [S3]). |
| T10 | **Distancia euclídea proyectada**, en metros, con una TM única de `lon_0 = −63` (§4.6). |
| T11 | **Umbral adaptativo por contacto de píxeles**: `d_ij ≤ r_i + r_j`, con `r = ½√(scan² + track²)` (§4.6). |
| T12 | No hace falta el script que generó `detections_raw.parquet`. |
| T13 | **Eventos**: buffer de 1 km (opción b) en general y buffer por cobertura (opción c) dentro de áreas protegidas, con `N = 5` días (§4.7). |
| T14 | Métrica `confidence` de §4.8 aprobada (estructura y valores iniciales). |
| T15 | **Objetivo de la etapa**: entregar datos agrupados y procesados para predecir. El clima (FWI, POWER, ONI) y la variable a predecir quedan para la etapa siguiente. |
| T16 | **Polígono del INCENDIO = unión de círculos** de radio `r_i` (el mismo de T11). **Polígono del EVENTO = unión de los polígonos de sus incendios** (§4.9). |
| T17 | **Áreas protegidas = capa IGN `ign:area_protegida`** (WFS, 506 polígonos, fuente SIB/IGN) [S16]. Los datasets de datos.gob.ar solo tienen estadísticas por provincia, sin geometría [S20]. |
| T18 | **Bosque = NASA MCD12Q1 v061** (cobertura de suelo IGBP, 500 m, anual) [S17]. |
| T19 | **Asignación**: un incendio está "en área protegida" si **al menos un hotspot** cae adentro. "Es bosque" si la **clase mayoritaria de MCD12Q1 bajo su polígono** es bosque, igual que FEDS [S5]. |
| T20 | **Inferencia de `type`**: un hotspot NRT se descarta si toca algún hotspot histórico con `type ≠ 0` de los **365 días anteriores** (§4.3). |
| T21 | **Defaults aprobados**: entrada desde CSV crudos; se agrupa con todos los puntos y se conservan los incendios con al menos un hotspot en Argentina; se conservan los incendios de un solo hotspot y los de confianza baja (los penaliza `confidence`); se incluye NOAA-21; la confidence del evento sale de sus incendios; salida en GeoPackage + parquet con WKT. |
| T22 | **WDPA queda fuera del alcance** por licencia. Se documenta como trabajo futuro (§8). |
| T23 | **El HOTSPOT mantiene el formato original de FIRMS.** No se le calcula confianza nueva: `confidence` existe solo en incendios y eventos. La clase común `l` / `n` / `h` y el puntaje `p_i` (§4.4 y §4.8) son **valores intermedios** del cálculo del incendio y no se guardan en la tabla de hotspots. |

## 3. Qué hay en los datos (relevado el 2026-11-15)

| Fuente | Período | Filas | Confianza | `type` |
|---|---|---|---|---|
| `data/raw/firms/country/modis` (Terra + Aqua) | 2000-11-01 → 2025-12-31 | 1.712.416 | numérica 0–100 | sí (0: 1.680.407 · 1: 4 · 2: 31.936 · 3: 69) |
| `country/viirs-snpp` | 2012-01-20 → 2025-12-31 | 2.889.092 | `l` / `n` / `h` | sí (0: 2.800.306 · 2: 80.724 · 3: 8.062) |
| `country/viirs-jpss1` (NOAA-20) | 2018-04-01 → 2025-12-31 | 1.728.797 | `l` / `n` / `h` | sí (0: 1.673.619 · 2: 49.114 · 3: 6.064) |
| `api/*_SP` (MODIS, SNPP, NOAA20) | 2026-01 → 2026-07/08 | — | idem | **sí** |
| `api/*_NRT` (MODIS, SNPP, NOAA20, **NOAA21**) | 2026-08/09 → 2026-11-14 (NOAA21 desde 2026-01) | — | idem | **NO** |

Hallazgos que condicionan el diseño:

- **Tamaño real de píxel** (columnas `scan` y `track`, en km). La coordenada es el **centro del píxel** y el píxel crece hacia el borde de la pasada [S1][S2].
  - MODIS: `scan` de 1,00 a **4,80** (media 1,66) y `track` hasta 2,00 (media 1,23). El 36,6 % de los píxeles tiene `scan` > 1,5 km.
  - VIIRS: `scan` de 0,32 a 0,80 (media 0,46) y `track` hasta 0,78 (media 0,49).
- **Hora de adquisición (UTC-3)**: MODIS pasa entre las 9 y las 17 h y entre las 21 y las 4 h; VIIRS, entre las 13 y las 17 h y entre las 0 y las 4 h. **No hay registros entre las 05 y las 08 h ni entre las 19 y las 20 h.**
- **`acq_time` en la API no tiene ceros a la izquierda** (`22`, `220`, `521`): hay que rellenarlo a 4 dígitos (HHMM, en UTC [S2]).
- **NOAA-21** solo existe en la API (NRT 2026).
- **S-NPP VIIRS**: FIRMS anunció el fin del flujo operativo para el 2026-11-02 [S12]. El último archivo NRT descargado es del 2026-10-30.
- **Terra MODIS** entró en standby el 2026-03-26 [S11]. En los datos, Terra cae de 1.102 detecciones en marzo de 2026 a 162 en junio y vuelve a 2.774 en septiembre (ver §6).
- **Extensión**: la API trae puntos hasta lat −21,7 / lon −53,6, posiblemente fuera de Argentina.
- **Fin de MODIS**: NASA prevé cortar la toma de datos científicos de Terra en feb-2027 y de Aqua en sep-2027 [S10].
- Las coordenadas de FIRMS están en WGS84 [S1].

## 4. Pipeline

Stack: Python 3 con duckdb, pandas, pyarrow, scipy, pyproj, geopandas, shapely y rasterio (para MCD12Q1). Hoy el sistema no tiene esas librerías: hay que armar un venv con `requirements.txt`.

```
config/params.yaml          ← todos los umbrales, pesos y períodos operativos (nada hardcodeado)
src/prep/
  00_download_aux.py        ← áreas protegidas IGN (WFS) + recorte MCD12Q1 (AppEEARS / LP DAAC)
  01_ingest.py              ← lectura de CSV crudos y unificación de esquema
  02_clean.py               ← dedup, filtro type + inferencia NRT
  03_conf_class.py          ← MODIS → l/n/h (intermedio, solo para el cálculo del incendio)
  04_fires.py               ← clustering hotspots → incendios + polígonos + AP/bosque
  05_events.py              ← incendios → eventos + polígonos
  06_confidence.py          ← métrica confidence (incendio / evento)
  07_export.py              ← parquet + GeoPackage
  report.md                 ← conteos por etapa (se genera)
```

### 4.0 Datos auxiliares
- **Áreas protegidas**: `GetFeature` de `ign:area_protegida` en `https://wms.ign.gob.ar/geoserver/ows`, en formato GeoJSON → `data/boundaries/ign_area_protegida.geojson` [S16].
  - Campos: `gid, fna, gna, nam, fdc, sag, area, geom`.
  - Verificar que lleguen los 506 objetos.
- **Cobertura de suelo**: MCD12Q1 v061, capa `LC_Type1` (IGBP), recortada a Argentina → `data/raw/landcover/` [S17].
  - Requiere una cuenta Earthdata (gratuita). Vía AppEEARS, con un pedido de área sobre el bounding box de Argentina, o vía LP DAAC.
  - ✅ **Descargado** (2026-11-15) en `data/raw/landcover/Geotiff/`: 25 años (2001–2025) × 2 capas (`LC_Type1` y `QC`), 146 MB.
    - EPSG:4326, píxel de 0,0041667° (~463 m), Byte, NoData = 255.
    - Extensión: lon −77,70 a −53,50, lat −56,68 a −20,82.
  - **Clases de bosque**: IGBP **1–5** (Evergreen Needleleaf, Evergreen Broadleaf, Deciduous Needleleaf, Deciduous Broadleaf y Mixed Forests). ✅ Verificado con la tabla de `MCD12Q1-061-LC-Type1-Statistics.csv` de la descarga.
  - Año: el del incendio; si no existe, el último disponible. NASA advierte cautela con las capas de 2021 en adelante [S17], así que se agrega el flag `lc_anio_usado`.

### 4.1 Ingesta (hotspots en formato original, T23)
Se lee desde los **CSV crudos** de `data/raw/firms/country/` y `data/raw/firms/api/`.

**Columnas originales de FIRMS, con sus nombres y valores sin modificar:**
`latitude, longitude, brightness, bright_t31, bright_ti4, bright_ti5, scan, track, acq_date, acq_time, satellite, instrument, confidence, version, frp, daynight, type`
- `brightness` y `bright_t31` solo vienen en MODIS; `bright_ti4` y `bright_ti5`, solo en VIIRS. En las filas del otro sensor esas columnas quedan nulas.
- `confidence` es la **original de FIRMS**: 0–100 en MODIS, `l` / `n` / `h` en VIIRS.
- `satellite` en VIIRS viene como `N` (SNPP), `N20` y `N21`.

**Columnas agregadas** (solo para enlazar y trazar, no son confianza):
- `hotspot_id`, `incendio_id`, `evento_id`
- `product` (`archive` / `SP` / `NRT`)
- `ts_utc`: `acq_date` + `acq_time`, ya rellenado a 4 dígitos
- `type_inferred` (bool), `terra_post_standby` (bool)

Para el cálculo se usan internamente columnas derivadas (sensor, hora local, `pass_bin`, radio `r`, coordenadas proyectadas). No se guardan en la tabla de hotspots.

### 4.2 Limpieza
- Deduplicar con la clave `(satellite, lat, lon, ts_utc)`. Cuando una detección aparece en standard/SP y en NRT, se prioriza standard/SP.
- **No se recorta antes de agrupar.** Se clusteriza con todos los puntos y se conservan los incendios con al menos un hotspot dentro de `data/boundaries/ign_pais.geojson` (T21). Así no se parten los incendios de frontera.
- Se conserva la confianza baja (T21).

### 4.3 Filtro de vegetación (T1) e inferencia de `type` en NRT (T20)
1. Archivo y SP: conservar `type == 0`.
2. NRT: un hotspot NRT `i` se **descarta** si existe un hotspot histórico `j` con `type ≠ 0` (de archivo o SP, de cualquier sensor) tal que:
   - `ts_j ∈ [ts_i − 365 días, ts_i)`, y
   - `d_ij ≤ r_i + r_j` (la misma fórmula de contacto de §4.6).
3. Si no toca ninguno, queda `type = 0` con `type_inferred = True`.
4. Reportar cuántos NRT se descartan y cuántos quedan inferidos.

Por qué 365 días: NASA define el `type 2` (fuente estática) como un punto detectado **16 días o más en un mismo año calendario**, o en zona urbana [S3]. Una ventana de un año toma las fuentes que siguen activas y descarta las que cerraron hace años.

Cuando NASA publique el producto estándar (SP/ML) de esas fechas, que sí trae `type` [S1], lo inferido se reemplaza.

### 4.4 Clase de confianza común (T8, T9) — valor intermedio
- Se usa **solo dentro del cálculo de `confidence` del incendio** (§4.8). **No se guarda en los hotspots** (T23).
- VIIRS conserva su clase nativa (`l` / `n` / `h`).
- MODIS: clase `l` si C < 30, `n` si 30 ≤ C < 80 y `h` si C ≥ 80 (Tabla 11 de [S3]).
- La columna original `confidence` de cada hotspot no se toca (T2).
- Limitación documentada: NASA define las clases de cada sensor con criterios propios (en VIIRS, `h` corresponde a píxeles saturados [S2]). La equivalencia se acepta por decisión del equipo.

### 4.5 Ventana de 12 h (T4)
- `pass_bin = fecha + {D, N}` sobre la hora local UTC-3, con cortes a las **07:00 y 19:00**. Según el histograma de §3, no hay registros en esas franjas.
- La ventana nocturna cruza la medianoche y lleva la fecha de su inicio (19:00).
- Antes de fijar los cortes, recalcular el histograma por satélite: Terra y Aqua tienen deriva orbital desde ~2022 [S10].

### 4.6 Clustering hotspots → INCENDIOS
**Proyección (T10)**: Transversa de Mercator única sobre WGS84:
`+proj=tmerc +lat_0=-90 +lon_0=-63 +k=1 +x_0=500000 +y_0=0 +datum=WGS84 +units=m` (meridiano central de la faja 4 de POSGAR [S13]).
- Se usa una sola proyección, y no las 7 fajas POSGAR 2007 (EPSG:5343–5349), para que un incendio que cruza el límite entre fajas no quede en dos sistemas distintos.
- TM es conforme, así que conserva bien las distancias locales.
- Error de escala en los extremos (lon −73,6 y −53,6): alrededor del 1 %, unos 4 m sobre 375 m. Las áreas tienen un error de alrededor del 2 %.

**Criterio (T11): los hotspots se unen si sus píxeles se tocan, incluso por una esquina.**

```
r_i = ½ · √(scan_i² + track_i²)        (semidiagonal del píxel i; km → ×1000 m)
i ~ j  ⇔  d_ij ≤ r_i + r_j              (d_ij = distancia euclídea proyectada entre centros)
```

Justificación:
1. La coordenada FIRMS es el **centro del píxel**: el fuego está en algún lugar dentro del píxel [S1].
2. El píxel mide `scan × track` y crece hacia el borde de la pasada [S2]. Un valor fijo (1 km o 375 m) partiría incendios: con 1 km fijo, dos píxeles MODIS vecinos del borde quedarían separados.
3. "Mismo incendio" = **área quemándose continua**. FIRMS señala que varios píxeles en línea suelen ser un frente de fuego [S1].
   - Es el criterio "touched" de GlobFire, Hantson y Archibald & Roy (Tabla 1 de [S5]).
   - Se incluye el contacto **por la esquina** porque los frentes avanzan en diagonal respecto de la grilla.
4. No tenemos la orientación de la pasada, así que cada píxel se aproxima por su **círculo circunscripto** (radio = semidiagonal). El criterio no depende de la orientación.
5. Para un par de sensores distintos, cada hotspot aporta su propio radio: no hace falta un umbral especial MODIS–VIIRS.

| Par (nadir) | Umbral |
|---|---|
| MODIS 1×1 + MODIS 1×1 | **1,41 km** |
| VIIRS 0,375 + VIIRS 0,375 | **0,53 km** |
| MODIS 1×1 + VIIRS 0,375 | **0,97 km** |
| MODIS borde 4,8×2,0 + MODIS 4,8×2,0 | **5,2 km** |

Costo conocido: el círculo es algo más grande que el rectángulo. A lo largo de un eje puede unir píxeles separados por un hueco de hasta unos 0,41 km (entre dos MODIS de 1 km). Se acepta, porque es menor que la incertidumbre de dónde está el fuego dentro del píxel.

**Algoritmo**: dentro de cada `pass_bin`, `cKDTree.query_pairs(2·r_max)` → filtrar `d_ij ≤ r_i + r_j` → `scipy.sparse.csgraph.connected_components`.
- Equivale a DBSCAN con `min_samples = 1` (single-linkage), pero con umbral por par, que DBSCAN no admite [S14]. FEDS usa un ball tree para el mismo paso [S5].
- Los hotspots aislados forman incendios de un solo hotspot y se conservan (T21).

**Atributos del incendio**:
- `incendio_id`, `pass_bin`, `t_inicio`, `t_fin`
- `n_hotspots_modis`, `n_hotspots_viirs`, `sensores_presentes`, `satelites_presentes`, `n_pasadas` (combinaciones distintas de satélite y hora)
- `area_pixeles_km2` (Σ scan·track, nominal), `area_poligono_km2`, `frp_sum`, centroide, **polígono** (§4.9)
- `en_area_protegida`, `ap_gid`, `ap_nombre` (si toca varias áreas: listas), `es_bosque`, `lc_clase`, `lc_anio_usado`
- `en_argentina`, `era` (§5), `confidence`

### 4.7 INCENDIOS → EVENTOS (T5, T13)
Enlace progresivo en orden temporal, `pass_bin` por `pass_bin`, según el algoritmo FEDS [S5]:

```
buffer(evento) = 5 km   si el evento está en un área protegida y es bosque   (opción c, FEDS)
                 1 km   en cualquier otro caso                                (opción b / c, FEDS)

incendio nuevo I se suma al evento activo E  ⇔
    existe un hotspot i ∈ I y un hotspot j ∈ E (detectado en los últimos N = 5 días)
    tal que  d_ij ≤ r_i + r_j + buffer(E)
```

- Igual que en FEDS, el buffer depende del **objeto existente** (el evento) [S5]:
  - El evento está "en área protegida" si alguno de sus incendios lo está.
  - "Es bosque" si la clase mayoritaria de MCD12Q1 bajo su polígono es bosque.
- Si el incendio toca dos eventos activos o más, esos eventos se **fusionan** y se conserva el `evento_id` más antiguo [S5].
- Si no toca ninguno, se crea un evento nuevo.
- Un evento se **cierra** cuando pasan 5 días sin incendios nuevos.
- Se conservan los eventos con al menos un incendio en Argentina.

Por qué estos valores:
- Los buffers de 1 y 5 km y los 5 días vienen **juntos** de FEDS, que los calibró sobre el mismo tipo de dato (VIIRS 375 m, `type 0`) [S5].
- Sin buffer, el evento se partiría en varios cuando el frente avanza entre pasadas (en pastizal la propagación es rápida [S15]) o cuando hay una pasada con nubes o humo [S1].
- Los estudios que usan 4 días trabajan solo con MODIS [S6][S8]; FIRED usa 11 días, pero optimizados sobre área quemada en EE. UU. [S7].

Riesgo a monitorear: en temporada alta, el encadenamiento de fusiones puede formar "mega-eventos" (por ejemplo, en el Delta o en el Chaco). Hay que revisar los eventos más grandes en QGIS.

**Atributos del evento**: `evento_id`, `inicio`, `fin`, `duracion`, `incendios[]`, `n_incendios`, `n_pass_bins_activos`, `area_pixeles_km2`, `area_poligono_km2`, `en_area_protegida`, `es_bosque`, `buffer_km`, **polígono**, `confidence`.

### 4.8 Métrica `confidence` (T2, T14)
Todos los números van en `params.yaml`. Son puntos de partida que se validan con la prueba de sensibilidad de §7.

**Qué la determina, en orden de importancia:**
1. **Corroboración independiente**: que otro satélite u otra pasada vea el mismo fuego. Los falsos positivos dependen de la pasada [S2]. Varios píxeles de una misma pasada **no** son evidencia independiente, así que se cuentan **pasadas**, no hotspots.
2. **Clase NASA** de los hotspots (T9).
3. **Ausencia de VIIRS cuando VIIRS miró**. VIIRS responde mejor a fuegos chicos [S1]. Se distingue *evidencia de ausencia* (VIIRS operativo y no detectó) de *ausencia de evidencia* (antes de 2012 VIIRS no existía).
4. **Comparabilidad entre épocas** (crítico para el modelo). La cantidad de satélites cambia con los años:
   - 2000–2002: solo Terra
   - 2002–2011: Terra y Aqua
   - desde 2012: se suma S-NPP
   - desde 2018: NOAA-20
   - desde 2023: NOAA-21
   - 2027: salen Terra y Aqua

   Por eso la corroboración se limita a **una observación por familia de sensor**.
5. **Tamaño** (área de píxeles), con peso leve. Un píxel MODIS ≈ 7 píxeles VIIRS, así que se usa área y no conteo [S1].

**Fórmula del INCENDIO:**

```
p(h)=0.90  p(n)=0.55  p(l)=0.15        ← punto medio de los rangos NASA de la Tabla 11 [S3] (elección nuestra)
w_VIIRS=1.00  w_MODIS=0.80             ← T7: MODIS penalizado por menor precisión

p_i  = p(class_i) · w_sensor_i                        ← intermedio por hotspot, no se guarda (T23)
p_M  = max p_i sobre hotspots MODIS   (0 si no hay)
p_V  = max p_i sobre hotspots VIIRS   (0 si no hay)

P    = 1 − (1 − p_M)·(1 − p_V)                         ← ambos sensores ↑ (noisy-OR, máx. 2 términos)
P   ← 1 − (1 − P)·(1 − ρ)^(k − 1)    ρ = 0.20          ← más pasadas que lo detectan ↑ (k = nº de pasadas distintas)
f_size = 0.85 + 0.15·(1 − e^(−A / 1 km²))              ← cantidad ponderada por área de píxeles A
f_miss = 1.00  si p_V > 0, o si la ventana es anterior al 2012-01-20 (no había VIIRS)
         0.70  si solo MODIS, VIIRS operativo y hay hotspot Aqua   (Aqua y S-NPP pasan juntos, ~13:30)
         0.85  si solo MODIS, VIIRS operativo y solo Terra        (Terra pasa ~3 h antes)

confidence_incendio = 100 · P · f_size · f_miss
```

| Regla del equipo | Dónde está |
|---|---|
| Tomada en el período sin VIIRS | `P = p_M`, con techo de 72 %. No se aplica `f_miss` porque no hay evidencia en contra. |
| Detectada con ambos sensores | noisy-OR. Ejemplo: MODIS `n` (0,44) + VIIRS `n` (0,55) → 75 %. |
| Mismo día, hotspots cercanos | `k` pasadas, con rendimiento decreciente y tope de 100 %. |
| MODIS detectó y VIIRS no | `f_miss` |
| Cantidad ponderada | `f_size`, por área |

"VIIRS operativo" sale de una tabla de períodos operativos por satélite en `params.yaml` (fechas de [S10][S11][S12]).

**EVENTO**: `confidence_evento` = promedio de `confidence_incendio` de sus incendios, **ponderado por `area_pixeles_km2`**.
- No se usa noisy-OR: un evento largo llegaría siempre a cerca de 100 %.
- La persistencia (`duracion`, `n_pass_bins_activos`) queda como columna aparte para el modelo.

### 4.9 Polígonos (límites de los clusters) y salidas (T16, T21)
**Polígono del INCENDIO** = unión de los círculos de radio `r_i` de sus hotspots. Se calcula en la TM y se exporta en lon/lat WGS84 (EPSG:4326).
- Es coherente con T11: dos hotspots del mismo incendio tienen círculos que se tocan, así que **cada incendio es un único polígono conexo**. Funciona con 1 hotspot (círculo) o con 2 (forma de "8").
- Detalle de implementación: `buffer` aproxima el círculo con un polígono inscripto, que es un poco más chico. Por eso se usa `r' = r / cos(π / (4·quad_segs)) + 1 m` con `quad_segs = 8`, para que los círculos tangentes sigan tocándose. Después: `unary_union` → `simplify(25 m, preserve_topology=True)`.
- `area_poligono_km2` (envolvente de círculos) sobreestima el área quemándose. Por eso también se reporta `area_pixeles_km2` (Σ scan·track).

**Polígono del EVENTO** = `unary_union` de los polígonos de sus incendios. Puede ser **MultiPolygon**, porque los incendios se enlazan con buffer de 1 o 5 km y no siempre se tocan.

**Archivos de salida** (coordenadas en lon/lat WGS84):

| Archivo | Contenido |
|---|---|
| `data/processed/hotspots.parquet` | hotspots finales en **formato original de FIRMS** + `incendio_id`, `evento_id` y las columnas de trazabilidad de §4.1 (sin confianza nueva, T23) |
| `data/processed/incendios.parquet` | atributos de §4.6 + `geometry_wkt` (límite del cluster) |
| `data/processed/eventos.parquet` | atributos de §4.7 + `geometry_wkt` |
| `data/qgis/fuego.gpkg` | capas `hotspots`, `incendios`, `eventos`, `areas_protegidas_ign`, `limites_provincia` |

Estilo en QGIS: color por `evento_id` y transparencia por `confidence`.

## 5. Transición MODIS → VIIRS

`era` por fecha:
- `solo_MODIS`: hasta el 2012-01-19
- `MODIS+VIIRS`: desde el 2012-01-20
- `solo_VIIRS`: a futuro (fin de Terra y Aqua [S10])

La `confidence` funciona **sin MODIS**: un incendio solo-VIIRS de clase `h` da 90 %, mientras que uno solo-MODIS anterior a 2012 tiene un techo de 72 %. El período solo-MODIS queda naturalmente por debajo, sin premiar una corroboración que solo existe entre 2012 y 2026. MODIS se categoriza con los umbrales oficiales de NASA (T9).

## 6. Puntos abiertos (no bloquean)

| ID | Tema | Cómo se resuelve |
|---|---|---|
| D11 | Terra después del standby del 2026-03-26 [S11] | Se marca `terra_post_standby` y se comparan los conteos con Aqua. Si no son consistentes, esos hotspots se excluyen de `confidence`. |
| D14 | Variable a predecir y unidad espacio-temporal | Etapa siguiente (T15). |

## 7. Verificación
1. **Conteos por etapa** (entrada → dedup → `type` → inferencia NRT → hotspots → incendios → eventos → Argentina) en `report.md`.
2. **Tests de la fórmula de contacto**:
   - dos píxeles que se tocan por la esquina se unen;
   - con un hueco mayor que la semidiagonal no se unen;
   - los pares mixtos dan los umbrales de la tabla de §4.6;
   - hotspots de ventanas distintas no se unen.
3. **Polígonos**:
   - cada incendio es un único `Polygon` válido (`is_valid`, nunca MultiPolygon); el test falla si aparece uno;
   - `area_pixeles_km2 ≤ area_poligono_km2` en todos los incendios.
4. **Eventos**: un caso sintético con dos incendios a 0,9 km en días consecutivos se une; a 1,5 km fuera de área protegida no se une; separados por 6 días no se unen.
5. **Inferencia de `type`**: visualizar en QGIS los NRT descartados. Deberían quedar cerca de fuentes conocidas (zonas petroleras, urbanas).
6. **Áreas protegidas y bosque**: revisar en QGIS incendios dentro de parques nacionales y su `es_bosque`.
7. **Sanidad de `confidence`**:
   - el rango cae en [0, 100];
   - la distribución por `era` no se separa solo por la cantidad de satélites (comparar las medianas de 2005 y 2020);
   - los incendios mixtos tienen mayor confidence que los solo-MODIS.
8. **Sensibilidad**: variar `w_MODIS`, `ρ` y `f_miss` en ±0,1, y el buffer de eventos a 0 y 2 km. Comparar la cantidad de eventos, la proporción de eventos de un solo incendio y los más grandes.
9. **Visual en QGIS** sobre grandes incendios conocidos de Argentina, con fechas y fuentes a confirmar antes de usarlos.

## 8. Trabajo futuro (para la defensa del proyecto)

**Integrar WDPA (World Database on Protected Areas, UNEP-WCMC e IUCN).**
- **Qué es**: la base mundial de áreas protegidas. Es la capa que usa el mapa de NASA FIRMS para alertas en áreas protegidas [S19]. Se actualiza todos los meses e incluye categorías UICN y designaciones que podrían no estar en la capa del IGN (por ejemplo, reservas privadas).
- **Por qué no se incluyó**: no es un dato de NASA. Sus términos [S18]:
  - prohíben redistribuir los datos (no se podrían subir al repositorio ni ofrecer para descargar);
  - definen como uso comercial el de una empresa o el que busca generar ingresos;
  - y dejan a UNEP-WCMC decidir cada caso.

  Para evitar riesgos de licencia, el equipo decidió dejarla fuera de este alcance.
- **Cómo se integraría con autorización**:
  - unión con la capa del IGN y columna `ap_fuente` (IGN / WDPA / ambas);
  - en las salidas solo flags e identificadores (`WDPAID`), nunca sus polígonos;
  - el archivo fuera de git;
  - la cita obligatoria "UNEP-WCMC and IUCN (año), Protected Planet: The World Database on Protected Areas (WDPA), [mes/año], www.protectedplanet.net".
- **Qué aporta**: cobertura más completa de áreas protegidas, y por lo tanto un buffer de eventos (5 km en bosque protegido) aplicado donde corresponde, alineado con la fuente que usa NASA FIRMS.

**Otras mejoras:**
- Reemplazar la inferencia de `type` por el producto estándar de NASA cuando esté publicado [S1].
- Afinar los pesos de `confidence` con registros de campo (por ejemplo, del Servicio Nacional de Manejo del Fuego).
- Usar la orientación real de la pasada para modelar el píxel como rectángulo en lugar de círculo.

## Fuentes

- **[S1]** NASA Earthdata, *FIRMS FAQ*: tamaño y centro de píxel, NRT sin `type`, horarios de pasada, causas de no detección, WGS84. https://www.earthdata.nasa.gov/data/tools/firms/faq
- **[S2]** NASA Earthdata, *FIRMS Active Fire Data Attributes (MODIS/VIIRS)*. https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs
- **[S3]** Giglio, L. et al., *MODIS Collection 6/6.1 Active Fire Product User's Guide v1.0* (NASA, mayo 2021): Tabla 11 (clases de confianza) y §5.5 (`type`). https://earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf
- **[S4]** NASA, *VIIRS C2 375 m Active Fire User Guide 1.2* (referencia, no revisada en detalle). https://www.earthdata.nasa.gov/s3fs-public/2025-06/VIIRS_C2_AF-375m_User_Guide_1.2.pdf
- **[S5]** Chen, Y. et al. (2022), *California wildfire spread derived using VIIRS satellite observations and an object-based tracking system*, Scientific Data 9:249, doi:10.1038/s41597-022-01343-0. Base de **FEDS** (NASA Earth Information System): filtro `type 0`, ball tree, buffer de 5 km en bosque y 1 km en el resto, 5 días de inactividad, cobertura mayoritaria, Tabla 1. https://earth-information-system.github.io/fireatlas/docs/data_overview.html
- **[S6]** Lizundia-Loiola, J. et al. (2020), Remote Sensing of Environment 236:111493: 1.875 m y 4 días (según la Tabla 1 de [S5]).
- **[S7]** Balch, J. K. et al. (2020), *FIRED*, Remote Sensing 12(21):3498: 2.315 m y 11 días.
- **[S8]** Loboda, T. & Csiszar, I. (2007): 2,5 km y 4 días (según la Tabla 1 de [S5]).
- **[S9]** Brigadistas y bomberos: no se encontró ninguna fuente operativa que fije una distancia entre hotspots. Las definiciones de NWCG son cualitativas: *Incident Complex* (equivale a nuestro EVENTO) y *Merged fire*.
  - https://inciweb.wildfire.gov/terminology
  - https://gacc.nifc.gov/gbcc/admin/IBCdocs/MIS7%20NWCG%20Memo16-024a%20Data%20Standards%20for%20Incident%20Complexes%20and%20Merged%20Wildfires.pdf
  - El manual de CONAE tampoco define distancias: https://catalogos5.conae.gov.ar/catalogofocos/Docs/035_CONAE_AQUA_TERRA_NOAA20_MODIS_VIIRS_FC_VISOR_ManualUsuarios_e02.pdf
- **[S10]** NASA LAADS, *MODIS to VIIRS Transition*: https://ladsweb.modaps.eosdis.nasa.gov/learn/modis-to-viirs-transition/ · NASA Earthdata, *Transition from MODIS to VIIRS*: https://www.earthdata.nasa.gov/data/alerts-outages/transition-from-modis-viirs
- **[S11]** NASA Earthdata, *Terra MODIS placed in standby mode*. https://www.earthdata.nasa.gov/data/alerts-outages/terra-modis-placed-standby-mode
- **[S12]** NASA Earthdata, *Transitioning from Suomi NPP VIIRS/OMPS: what FIRMS users need to know*. https://www.earthdata.nasa.gov/news/blog/transitioning-from-suomi-npp-viirs-omps-what-firms-users-need-know
- **[S13]** EPSG, POSGAR 2007 / Argentina fajas 1–7 (EPSG:5343–5349). https://epsg.io/5343
- **[S14]** scikit-learn, `DBSCAN`. https://scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html
- **[S15]** Andela, N. et al. (2019), *The Global Fire Atlas of individual fire size, duration, speed and direction*, Earth System Science Data 11:529–552: propagación rápida en ecosistemas de poco combustible. https://essd.copernicus.org/articles/11/529/2019/
- **[S16]** IGN Argentina, WFS capa `ign:area_protegida` (506 objetos, fuente SIB/IGN). https://wms.ign.gob.ar/geoserver/ows?service=wfs&version=2.0.0&request=DescribeFeatureType&typeNames=ign:area_protegida
- **[S17]** NASA LP DAAC, *MCD12Q1 v061 — MODIS/Terra+Aqua Land Cover Type Yearly L3 Global 500 m*: https://www.earthdata.nasa.gov/data/catalog/lpcloud-mcd12q1-061 · NASA MODIS Land Team, Land Cover: https://modis-land.gsfc.nasa.gov/landcover.html
- **[S18]** Protected Planet (UNEP-WCMC), términos legales de WDPA. https://www.protectedplanet.net/en/legal
- **[S19]** AGU Fall Meeting 2013, resumen IN11B-1524, *Providing accurate near real-time fire alerts for Protected Areas through NASA FIRMS* (FIRMS usa WDPA; autores a verificar en la página). https://ui.adsabs.harvard.edu/abs/2013AGUFMIN11B1524I
- **[S20]** datos.gob.ar, *Áreas protegidas nacionales* y *Áreas protegidas privadas* (Subsecretaría de Ambiente, CC BY 4.0): solo CSV estadísticos por jurisdicción, sin geometría. https://datos.gob.ar/dataset/areas-protegidas-nacionales · https://datos.gob.ar/dataset/areas-protegidas-privadas
