# Reporte de evaluación — hotspots Córdoba (test)

- Checkpoint: `pred/data/models/best.pt` (época 5)
- Hotspots predichos: 17945; incendios clásicos: 3245; eventos: 221

## Métricas de hotspot

- PR-AUC: 0.0090
- ROC-AUC: 0.8374
- Brier: 0.1267
- Recall@0.5: 0.6714
- Patch hit rate: 0.7924

## Baselines

- Persistencia PR-AUC: 0.0027
- Climatología PR-AUC: 0.0063

## Derivación clásica

- Incendios: {'precision': 0.06656394453004623, 'recall': 0.1249277038750723, 'f1': 0.08685162846803378, 'n_pred': 3245, 'n_real': 1729, 'n_match': 216, 'missed_rate': 0.8750722961249278}
- Eventos: {'precision': 0.47058823529411764, 'recall': 0.08247422680412371, 'f1': 0.14035087719298245, 'n_pred': 221, 'n_real': 1261, 'n_match': 104, 'missed_rate': 0.9175257731958762}
- Enlace: {'n_pred_eventos': 221, 'n_matched': 115, 'n_continuacion': 0, 'n_nuevo': 115, 'n_sin_evento_real': 106}