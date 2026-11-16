# Model Card — Predicción de hotspots (Córdoba)

## Descripción

Modelo de aprendizaje profundo que estima la probabilidad de que ocurra un
**hotspot de incendio** en cada celda de **1 km** durante los **7 días**
posteriores a un hotspot ancla, en la provincia de Córdoba, Argentina.

- **Entrada:** 14 días de historia de hotspots y clima, más el pronóstico
  meteorológico de los 7 días futuros.
- **Salida:** probabilidad por celda y día futuro (`t0+1 … t0+7`), en un parche
  de 32×32 celdas (32×32 km) centrado en el hotspot ancla.
- **Post-procesamiento:** los hotspots predichos se agrupan en incendios y
  eventos con la lógica clásica de `prep/` (contacto de píxeles, buffer y
  ventana temporal).

## Uso previsto

- Exploración y apoyo a la toma de decisiones sobre riesgo de incendios.
- Demostración técnica para NASA Space Apps.
- Reproducción de experimentos y comparación con baselines.

**No** está pensado como sistema de alerta oficial ni para reemplazar
pronósticos de organismos de emergencia. Las predicciones son experimentales.

## Arquitectura

| Componente | Detalle |
|---|---|
| Parche | 32×32 celdas de 1 km (32×32 km) |
| Historia | 14 días |
| Horizonte | 7 días |
| Canales de historia | 20 |
| Canales de clima futuro | 7 |
| Canales estáticos | 12 |
| Encoder | CNN compartida por frame |
| Memoria temporal | LSTM, `hidden=64`, 1 capa, dropout 0.3 |
| Encoder de clima futuro | CNN + `Linear(64)` por día |
| Parámetros | ≈1–1,5 M |
| Pérdida | BCE ponderada (`pos_weight=75`) + pérdida de parche |
| Optimizador | AdamW, lr 2e-4, weight decay 1e-3, batch 48 |
| Checkpoint final | `pred/data/models/best.pt` (época 5) |

La grilla es de 1 km en EPSG:6933, recortada al polígono de Córdoba. Las celdas
fuera de la provincia se enmascaran y no cuentan en la pérdida ni en la
evaluación.

## Datos de entrenamiento

| Split | Período | Muestras |
|---|---|---|
| Train | 2019-01-01 → 2025-07-24 | 32.661 |
| Validación | 2025-08-01 → 2026-07-24 | 2.913 |
| Test | 2026-08-01 → 2026-11-07 | 1.145 |

Fuentes: NASA FIRMS (MODIS y VIIRS), NASA POWER, Open-Meteo, MCD12Q1 v061,
límites IGN y ONI. Ver [DATA_SOURCES.md](DATA_SOURCES.md).

## Evaluación

Métricas de hotspot (celda-día) sobre validación y test:

| Métrica | Validación | Test |
|---|---:|---:|
| ROC-AUC | 0.8560 | 0.8374 |
| PR-AUC | 0.0122 | 0.0090 |
| Brier | 0.1015 | 0.1267 |
| Recall @ 0,5 | 0.6454 | 0.6714 |
| Patch hit rate | 0.7687 | 0.7924 |
| PR-AUC persistencia | 0.0068 | 0.0027 |
| PR-AUC climatología | 0.0041 | 0.0063 |

El PR-AUC es bajo en términos absolutos porque las celdas positivas son una
fracción muy pequeña del total (≈0,19 % en validación), pero supera a los
baselines de persistencia y climatología. El ROC-AUC y el patch hit rate
indican que el modelo ordena razonablemente el riesgo y encuentra la mayoría de
los parches con al menos un hotspot futuro.

Reportes completos: [`results/report_val.md`](results/report_val.md),
[`results/report_test.md`](results/report_test.md). Métricas crudas:
[`results/metrics_val.json`](results/metrics_val.json),
[`results/metrics_test.json`](results/metrics_test.json).

## Predicción operativa

La corrida incluida en `pred/predictions/latest_2026-11-13/` usa:

- **Ancla:** 2026-11-13 (15 hotspots ancla).
- **Horizonte:** 2026-11-14 → 2026-11-20.
- **Umbral:** 0,80; máximo 200 hotspots por día.
- **Resultado:** 271 hotspots, 131 incendios y 20 eventos derivados.
- **Clima futuro:** Open-Meteo; historia: NASA POWER.

## Limitaciones

- **Desbalance extremo:** ≈0,19 % de celdas-día positivas; el PR-AUC absoluto es
  bajo y la calibración debe revisarse antes de uso operativo.
- **Clima de validación optimista:** en entrenamiento y validación se usa POWER
  observado como proxy del pronóstico; en operación se usa Open-Meteo.
- **Resolución meteorológica gruesa:** una celda POWER mide ~50–70 km, más que
  el parche de 32 km; el clima es casi uniforme dentro del parche.
- **Cobertura geográfica:** solo Córdoba; no se evaluó en otras provincias.
- **Entidades derivadas:** incendios y eventos no se aprenden directamente;
  surgen de agrupar hotspots predichos con reglas clásicas.
- **Falsos positivos:** el umbral bajo prioriza recall; puede generar alertas
  innecesarias.
- **Datos de entrada:** la predicción operativa requiere la historia reciente
  de hotspots y clima; no es un modelo autónomo sin actualización de datos.

## Artefactos

- Modelo: `pred/data/models/best.pt`.
- Métricas e historial: `pred/data/models/last_metrics.json`,
  `history.csv`, `last_val_figure.png`.
- Predicción operativa: `pred/predictions/latest_2026-11-13/`.
- Resultados de evaluación: `results/`.

## Licencia y cita

Código bajo licencia MIT. Ver [LICENSE](LICENSE) y [CITATION.cff](CITATION.cff).
