# Mente Fría · herramienta web (prototipo funcional)

Next.js 15 (App Router) + MapLibre GL. Pasa a código el diseño de `../webtool-idea` y lo conecta con datos reales de NASA FIRMS. El código está en inglés y la interfaz, en español.

## Cómo correrlo

Desde la raíz del repo, primero se generan los datos (tarda unos 70 s y usa el venv del pipeline) y después se levanta la web en http://localhost:3000:

```bash
pipeline/.venv/bin/python webtool/scripts/build_data.py
cd webtool
npm install
npm run dev
```

`public/data/fires/` y `public/data/hotspots/` (≈ 760 MB en total) no van a git, así que hay que regenerarlos con el script.

## Vistas

| Ruta | Qué muestra |
|---|---|
| `/` (Mapa) | Funciona como un programa de análisis de datos: hay botones cuadrados que abren tarjetas alrededor del mapa. **Ubicación** (arriba a la izquierda) se abre al tocar el mapa y muestra latitud y longitud, zona, probabilidad de fuego, hotspots e inicio y fin del incendio total (evento). **Visualización** (abajo a la izquierda) elige entre ver incendios y ver hotspots VIIRS, MODIS o ambos (`?s=`), y muestra u oculta la leyenda. **Bitácora** (arriba a la derecha) muestra el histórico de registros, con un botón "Ver más". Una etiqueta siempre visible indica los incendios del país y de la provincia. Abajo está la línea de tiempo, con el botón "Hoy". |
| `/calendario` | Ocho temporadas semana por semana y un calendario con escala Semana, Mes o Temporada. A la izquierda, **Ubicación**: el lugar y el incendio que se tocó en el mapa o, si no se tocó ninguno, Argentina › Provincia › Departamento y la lista de incendios del mes (inicio, fin, latitud y longitud), con la opción de volver al mapa a elegir un punto. Después, **Fecha** (la fecha elegida, la ubicación País › Provincia › Departamento y los incendios de ese día) y **Filtros** (capas). A la derecha, la **Bitácora**: los registros nuevos quedan vinculados al incendio seleccionado. |

La región (`?r=AR | pNN | dNNNNN`), el mes (`?m=YYYY-MM`), el día (`?d=`), el punto tocado (`?pt=lat,lon`) y el incendio (evento del pipeline) de ese punto (`?ev=YYYY-MM:id`) van en la URL, así que las dos vistas comparten la selección y los links se pueden compartir. El buscador del header encuentra provincias y departamentos.

## Datos (`scripts/build_data.py` → `public/data/`)

La fuente son las **salidas del pipeline** de la rama `prep-firms` (PLAN §4): hotspots agrupados en **incendios** y **eventos**, con la `confidence` del PLAN §4.8, de 2000-11-01 a 2026-11-14. El script usa la primera ubicación donde las encuentre:

1. `prep/data/processed/{hotspots,incendios,eventos}.parquet`, si el pipeline se corre en esta máquina.
2. `data/prep/{hotspots,incendios,eventos}.parquet`: la copia que se usa hoy. Se extrae de la rama sin cambiar de rama:
   ```bash
   for n in hotspots incendios eventos; do git show tailscale/prep-firms:prep/data/processed/$n.parquet > data/prep/$n.parquet; done
   ```
3. `data/prep/fuego*.gpkg`: un GeoPackage del pipeline (por ejemplo, una corrida parcial).

Si el pipeline no cubre algunos días, esos días salen de `data/processed/detections_raw.parquet` con reglas provisorias y la web los marca como "Datos provisorios". Con la corrida completa actual, eso no pasa.

| Archivo | Contenido |
|---|---|
| `meta.json` | rango de fechas, último dato, factor `k` MODIS → VIIRS y cobertura del pipeline |
| `regions.json` | país, 24 provincias y 529 departamentos (IGN) con su bbox |
| `geo/provinces.json`, `geo/departments.json` | límites IGN simplificados |
| `series/<región>.json` | serie diaria `[día, nº MODIS, nº VIIRS, km², nº incendios]` |
| `fires/<YYYY-MM>.json` | **incendios** que empezaron en el mes: atributos, centroide, polígono simplificado (~50 m, enteros delta de 1e-4°) y la tabla de sus **eventos** (≈ 550 MB en total; el mes más pesado, ago 2020, ocupa 11,8 MB) |
| `hotspots/<YYYY-MM>.json` | hotspots del mes en columnas: `lat, lon, s (sensor), p (confianza de su incendio), r (radio m), d (día), fire (fila de su incendio en fires/<mes>)` (≈ 215 MB) |

## Mapa: incendios (vista principal) y hotspots (alternativa)

- **Incendios** (`?v=fires`, por defecto). De lejos se ve una mancha de calor sobre los centroides, ponderada por confianza y área. De cerca, los polígonos reales del pipeline (unión de los círculos de píxel, PLAN T16), coloreados por confianza.
  - La confianza en un punto es `1 − Π(1 − c)` sobre los incendios cuyo polígono lo contiene. Fuera de los polígonos vale 0.
- **Hotspots** (`?v=hotspots`). Cada píxel se dibuja con su radio real (PLAN T11) y lleva la confianza de su incendio.
  - Cuentan solo los píxeles que cubren el punto. Los hotspots de un mismo incendio cuentan una sola vez, porque no son evidencia independiente (PLAN §4.8).
- En las dos vistas, al tocar un punto se ven el **incendio** (hora local, satélites, hotspots, km² de píxeles y de contorno, área protegida y bosque) y su **evento** (inicio, fin, duración, cantidad de incendios y buffer). El tooltip resume el incendio que está bajo el cursor.

**Superficie (series y línea de tiempo).** Se mide la superficie de píxeles con fuego (Σ scan·track) en escala VIIRS. Desde el 2012-01-20 se usa el área VIIRS; antes, el área MODIS × `k`, donde `k` = Σ área VIIRS / Σ área MODIS en el período de solapamiento (hoy `k = 0,582`).

## Pronóstico (amarillo)

Sale de la predicción operativa de la rama `pred-hotspots` (`pred/PLAN.md`, `src/10_predict_latest.py`). Hoy cubre Córdoba del 14 al 20 nov 2026 con 131 incendios y 20 eventos. El modelo exporta 271 filas de hotspots, pero 55 repiten la misma celda el mismo día (ventanas superpuestas); la web cuenta cada celda una sola vez, así que quedan 216. Se extrae sin cambiar de rama y se convierte en segundos:

```bash
mkdir -p data/pred
for f in summary.json predicted_hotspots.parquet predicted_fires.parquet predicted_events.parquet; do git show tailscale/pred-hotspots:pred/predictions/latest_2026-11-13/$f > data/pred/$f; done
pipeline/.venv/bin/python webtool/scripts/build_prediction.py
```

El script genera `public/data/prediction/index.json` (≈ 74 KB). Contiene los hotspots predichos (día, incendio y ola), los incendios estimados con su contorno, los eventos y los incendios estimados por día para el país, cada provincia y cada departamento. Si la rama está en la máquina, usa la carpeta `pred/predictions/latest_*` más nueva.

- Son días de pronóstico los posteriores al último dato real. Cuando hay datos reales y pronóstico para el mismo día (hoy, el 14 nov), se muestra el dato real.
- **Línea de tiempo** (escala Días): los días de pronóstico van en amarillo. Las escalas Semanas y Meses terminan en el último dato real.
- **Mapa**: en un día de pronóstico se ven solo los datos estimados, en amarillo. En la vista Incendios aparecen los **contornos de los incendios estimados**; en la vista Hotspots, cada celda estimada.
- **Contornos**: el modelo solo exporta el centro de cada incendio, así que `build_prediction.py` los reconstruye con la misma regla de `pred/src/08_classic_fires_events.py`. Agrupa las celdas de 1 km que se tocan el mismo día (radio de 707 m, la semidiagonal) y forma el contorno con la unión de esos círculos, igual que en los incendios históricos. Recalcula también el id con el mismo hash, así que el vínculo hotspot → incendio → ola es exacto; si la regla cambia, el script lo avisa. Aparece una alerta de que son estimaciones. La tarjeta Ubicación muestra los hotspots estimados, la superficie estimada y el inicio y fin de la ola (o del incendio) estimada.
- **Sin porcentajes en el pronóstico.** El modelo solo exporta las celdas con puntaje ≥ 0,8, así que su "probabilidad" siempre está entre 80 % y 100 %. La confianza histórica en Córdoba tiene mediana de ≈ 48 % y solo el 12 % de los incendios supera 80 %. Mostrar los dos valores juntos haría parecer el pronóstico más seguro que lo observado. Por eso el color del pronóstico usa el **tamaño de cada incendio estimado** (hotspots: 1 · 2–3 · 4–9 · 10+), una medida comparable con el histórico (mediana 1, p90 ≈ 6).
- **Calendario**: los días de pronóstico van en amarillo, con la etiqueta "Estimado" y los incendios estimados. La tarjeta Fecha muestra el aviso "Cuidado".
- Fuera de la zona que cubre el modelo, se indica "sin pronóstico".

## Incendios y olas de incendios

Un **incendio** es un incendio del pipeline. Un evento que abarca varios días se llama **ola de incendios**; uno de un solo día sigue siendo un incendio. Este criterio se aplica en la tarjeta Ubicación, la lista del calendario, el formulario y la bitácora. En el mapa (vista Incendios), al tocar un incendio que forma parte de una ola, todos los incendios de esa ola quedan marcados con línea punteada. La interfaz ya no usa "foco": los conteos son de incendios, y las detecciones sueltas se llaman hotspots.

## Bitácora

`/api/entries` (GET/POST) guarda los registros en `data/entries.json`, que no va a git. Es un prototipo sin usuarios ni autenticación. Cada registro queda anclado a un punto y se asigna a su departamento y provincia en el navegador (punto en polígono).

## Pendiente

- Cuentas de usuario y una base de datos real para la bitácora.
- Resúmenes con IA de los testimonios (el diseño los muestra; hoy no están implementados).
- Predicciones para el resto del país (hoy solo Córdoba) y olas estimadas en la lista del calendario.
- Comprimir los archivos mensuales: el más pesado (incendios de ago 2020) ocupa 11,8 MB sin gzip.
- Versión mobile.
