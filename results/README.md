# Resultados de evaluación

Artefactos generados con `pred/src/07_evaluate.py` sobre los splits de
validación y test del modelo `pred/data/models/best.pt` (época 5).

## Métricas principales

| Métrica | Validación | Test |
|---|---:|---:|
| ROC-AUC | 0,8560 | 0,8374 |
| PR-AUC | 0,0122 | 0,0090 |
| Brier | 0,1015 | 0,1267 |
| Recall @ 0,5 | 0,6454 | 0,6714 |
| Patch hit rate | 0,7687 | 0,7924 |
| PR-AUC persistencia | 0,0068 | 0,0027 |
| PR-AUC climatología | 0,0041 | 0,0063 |

El detalle completo, incluidos precisión/recall por umbral, métricas top-k,
derivación clásica de incendios/eventos y baselines, está en los reportes y en
los JSON de métricas.

## Archivos

| Archivo | Descripción |
|---|---|
| `report_val.md` | Reporte legible de validación (agosto 2025 – julio 2026). |
| `report_test.md` | Reporte legible de test (agosto – noviembre 2026). |
| `metrics_val.json` | Métricas crudas de validación. |
| `metrics_test.json` | Métricas crudas de test. |
| `sweep.csv`, `sweep.json` | Resultados del barrido de hiperparámetros. |
| `training_curves.png` | Curvas de entrenamiento y validación. |
| `last_val_figure.png` | Figura de ejemplo de la última validación. |
| `predicted_hotspots_val.parquet` | Hotspots predichos en validación. |
| `predicted_hotspots_test.parquet` | Hotspots predichos en test. |
| `predicted_fires_val.parquet` | Incendios derivados en validación. |
| `predicted_fires_test.parquet` | Incendios derivados en test. |
| `predicted_events_val.parquet` | Eventos derivados en validación. |
| `predicted_events_test.parquet` | Eventos derivados en test. |

La predicción operativa más reciente no está acá: vive en
`pred/predictions/latest_2026-11-13/`.

## Reproducir

```bash
cd pred
./.venv/bin/python src/07_evaluate.py --config config/params.yaml
./.venv/bin/python src/07_evaluate.py --config config/params.yaml --split test
```

Los reportes guardan rutas absolutas del entorno donde se generaron; los
números y las tablas son independientes de esas rutas.
