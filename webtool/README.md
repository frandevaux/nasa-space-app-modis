# Mente Fría · herramienta web (prototipo funcional)

Next.js 15 (App Router) + MapLibre GL. Pasa a código el diseño de
[`../webtool-idea`](../webtool-idea) y lo conecta con datos reales de NASA
FIRMS. El código está en inglés y la interfaz, en español.

## Cómo correrlo

Desde la raíz del repo:

```bash
# 1. Datos y pipeline
make setup                 # crea prep/.venv y pred/.venv
make pipeline-setup        # crea pipeline/.venv (incluye duckdb)
cp .env.example .env       # completar MAP_KEY de FIRMS
make download              # FIRMS, POWER/ONI y límites IGN
make raw                   # data/processed/detections_raw.parquet
make data-aux              # auxiliares de prep
make prep                  # prep/data/processed/{hotspots,incendios,eventos}.parquet

# 2. Datos de la web
pipeline/.venv/bin/python webtool/scripts/build_data.py

# 3. App
cd webtool
npm install
npm run dev
```

La app queda en http://localhost:3000. `make webtool-data` hace el paso 2 y
`make webtool` levanta el servidor si ya instalaste las dependencias.

`public/data/fires/` y `public/data/hotspots/` (≈ 760 MB en total) no van a
git, así que hay que regenerarlos con el script.

Requisitos: Node.js 20+ y el pipeline de `prep/` ejecutado al menos una vez.

## Vistas

| Ruta | Qué muestra |
|---|---|
| `/` (Mapa) | Funciona como un programa de análisis de datos: hay botones cuadrados que abren tarjetas alrededor del mapa. **Ubicación** (arriba a la izquierda) se abre al tocar el mapa y muestra latitud y longitud, zona, probabilidad de fuego, hotspots e inicio y fin del incendio total (evento). **Filtros** (abajo a la izquierda) elige entre focos (incendios) y hotspots VIIRS, MODIS o ambos (`?s=`). **Bitácora** (arriba a la derecha) muestra el histórico de registros, con un botón "Ver más". Una etiqueta siempre visible indica los focos del país y de la provincia. Abajo está la línea de tiempo, con el botón "Hoy". |
| `/calendario` | Ocho temporadas semana por semana y un calendario con escala Semana, Mes o Temporada. A la izquierda, **Fecha** (la fecha elegida, la ubicación País › Provincia › Departamento y los incendios de ese día) y **Filtros** (capas). A la derecha, la **Bitácora**. |

La región (`?r=AR | pNN | dNNNNN`), el mes (`?m=YYYY-MM`) y el día (`?d=`) van
en la URL, así que las dos vistas comparten la selección y los links se pueden
compartir. El buscador del header encuentra provincias y departamentos.

## Datos (`scripts/build_data.py` → `public/data/`)

La fuente son las **salidas del pipeline de `prep/`**: hotspots agrupados en
**incendios** y **eventos**, con la `confidence` calculada por
`prep/src/06_confidence.py`, de 2000-11-01 a 2026-11-14. El script usa la
primera ubicación donde las encuentre:

1. `prep/data/processed/{hotspots,incendios,eventos}.parquet`, si el pipeline se
   corre en esta máquina.
2. `data/prep/{hotspots,incendios,eventos}.parquet`: una copia local opcional
   para no depender de `prep/data/`.
3. `data/prep/fuego*.gpkg`: un GeoPackage del pipeline (por ejemplo, una
   corrida parcial).

Si el pipeline no cubre algunos días, esos días salen de
`data/processed/detections_raw.parquet` (generado por `make raw`) con reglas
provisorias, y la web los marca como "Datos provisorios". Con la corrida
completa actual, eso no pasa.

| Archivo | Contenido |
|---|---|
| `meta.json` | rango de fechas, último dato, factor `k` MODIS → VIIRS y cobertura del pipeline |
| `regions.json` | país, 24 provincias y 529 departamentos (IGN) con su bbox |
| `geo/provinces.json`, `geo/departments.json` | límites IGN simplificados |
| `series/<región>.json` | serie diaria `[día, nº MODIS, nº VIIRS, km², nº incendios]` |
| `fires/<YYYY-MM>.json` | **incendios** que empezaron en el mes: atributos, centroide, polígono simplificado (~50 m, enteros delta de 1e-4°) y la tabla de sus **eventos** (≈ 550 MB en total; el mes más pesado, ago 2020, ocupa 11,8 MB) |
| `hotspots/<YYYY-MM>.json` | hotspots del mes en columnas: `lat, lon, s (sensor), p (confianza de su incendio), r (radio m), d (día), fire (fila de su incendio en fires/<mes>)` (≈ 215 MB) |

El diccionario de los parquets de entrada está en
[`../DATA_DICTIONARY.md`](../DATA_DICTIONARY.md).

## Mapa: incendios (vista principal) y hotspots (alternativa)

- **Incendios** (`?v=fires`, por defecto). De lejos se ve una mancha de calor
  sobre los centroides, ponderada por confianza y área. De cerca, los polígonos
  reales del pipeline (unión de los círculos de píxel), coloreados por
  confianza.
  - La confianza en un punto es `1 − Π(1 − c)` sobre los incendios cuyo polígono
    lo contiene. Fuera de los polígonos vale 0.
- **Hotspots** (`?v=hotspots`). Cada píxel se dibuja con su radio real de píxel
  y lleva la confianza de su incendio.
  - Cuentan solo los píxeles que cubren el punto. Los hotspots de un mismo
    incendio cuentan una sola vez, porque no son evidencia independiente.
- En las dos vistas, al tocar un punto se ven el **incendio** (hora local,
  satélites, hotspots, km² de píxeles y de contorno, área protegida y bosque) y
  su **evento** (inicio, fin, duración, cantidad de incendios y buffer). El
  tooltip resume el incendio que está bajo el cursor.

**Superficie (series y línea de tiempo).** Se mide la superficie de píxeles con
fuego (Σ scan·track) en escala VIIRS. Desde el 2012-01-20 se usa el área VIIRS;
antes, el área MODIS × `k`, donde `k` = Σ área VIIRS / Σ área MODIS en el
período de solapamiento (hoy `k = 0,582`).

## Pronóstico (pendiente: falta el archivo)

La web lee `public/data/prediction/index.json` si existe. Si no existe, los
meses futuros se muestran rayados con el aviso "Pronóstico pendiente". Formato
esperado (`Prediction` en `src/lib/types.ts`):

```json
{
  "model": "nombre/versión del modelo",
  "generated": "2026-11-15",
  "months": ["2026-12", "2027-01"],
  "regions": {
    "AR":     { "2026-12": { "km2": 5200, "lo": 3100, "hi": 8000, "prob": 0.7 } },
    "p14":    { "2026-12": { "km2": 120,  "lo": 40,   "hi": 260 } },
    "d14091": { "2026-12": { "km2": 8.5 } }
  },
  "grid": true
}
```

- `km2` va en la misma escala que la serie histórica (km² equivalentes VIIRS).
  `lo`, `hi` y `prob` son opcionales.
- Con `"grid": true`, además se lee `prediction/<YYYY-MM>.json` con
  `{ "month", "step", "lat": [], "lon": [], "p": [] }`: centros de celda en
  grados y probabilidad de 0 a 100. Se dibuja como capa en el mapa.

## Bitácora

`/api/entries` (GET/POST) guarda los registros en `data/entries.json`, que no va
a git. Es un prototipo sin usuarios ni autenticación. Cada registro queda
anclado a un punto y se asigna a su departamento y provincia en el navegador
(punto en polígono).

## Pendiente

- Cuentas de usuario y una base de datos real para la bitácora.
- Resúmenes con IA de los testimonios (el diseño los muestra; hoy no están
  implementados).
- Comprimir los archivos mensuales: el más pesado (incendios de ago 2020) ocupa
  11,8 MB sin gzip.
- Versión mobile.
