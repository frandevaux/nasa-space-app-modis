# Reporte de evaluación — hotspots Córdoba (val)

- Checkpoint: `pred/data/models/best.pt` (época 5)
- Hotspots predichos: 54572; incendios clásicos: 12619; eventos: 1015

## Métricas de hotspot

- PR-AUC: 0.0122
- ROC-AUC: 0.8560
- Brier: 0.1015
- Recall@0.5: 0.6454
- Patch hit rate: 0.7687

## Baselines

- Persistencia PR-AUC: 0.0068
- Climatología PR-AUC: 0.0041

## Derivación clásica

- Incendios: {'precision': 0.06038513352880577, 'recall': 0.159114637711422, 'f1': 0.08754595588235294, 'n_pred': 12619, 'n_real': 4789, 'n_match': 762, 'missed_rate': 0.840885362288578}
- Eventos: {'precision': 0.44236453201970444, 'recall': 0.13431049955130123, 'f1': 0.20605782469022488, 'n_pred': 1015, 'n_real': 3343, 'n_match': 449, 'missed_rate': 0.8656895004486987}
- Enlace: {'n_pred_eventos': 1015, 'n_matched': 475, 'n_continuacion': 4, 'n_nuevo': 471, 'n_sin_evento_real': 540}