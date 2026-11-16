# Reporte de preprocesamiento FIRMS

- Etapa: `07_export`
- Smoke: `False` / caso: `None`
- run_id: `20261115T190759Z-07_export`

## Conteos por etapa

| Etapa | Duración (s) | Métricas clave | Warnings |
|---|---:|---|---|
| 00_fetch_aux | 22.874 |  | 1 |
| 01_ingest | 14.772 | ingest.rows_raw=6868985 | 0 |
| 02_clean | 203.847 | clean.rows_raw=6868985; clean.rows_dedup=6868982; clean.duplicates=3; clean.nrt_total=314925; clean.nrt_discarded=19212; clean.rows_final=6658956 | 0 |
| 03_conf_class | 89.403 | class.rows_in=6658956; class.rows_out=6658956; class.pass_bins=18283 | 0 |
| 04_fires | 1259.469 | fires.engine_gpu=False; fires.total=2021370; fires.argentina=1952801; fires.singletons=1017301; fires.singleton_fraction=0.5032730276990358; fires.area_violations=257445 | 0 |
| 05_events | 4877.296 | events.total=1230343; events.argentina=1187021; events.merged=18556; events.closed=1230343; events.singletons=941242; events.singleton_fraction=0.7650240623956084 | 0 |
| 06_confidence | 282.382 | confidence.fires=2021370; confidence.events=1230343 | 0 |
| 07_export | 207.047 | export.hotspots=6426755 | 0 |

## Validaciones

```json
{
  "counts": {
    "hotspots": 6426755,
    "incendios": 1952801,
    "eventos": 1187021
  },
  "hotspots_nulls": {
    "incendio_id": 0,
    "evento_id": 0,
    "conf_inc": 0
  },
  "confidence_range": {
    "fires_min": 7.936471904123982,
    "fires_max": 99.41279744,
    "events_min": 7.936471904123982,
    "events_max": 99.2659968
  },
  "pre_viirs_max": 72.0,
  "confidence_nulls": {
    "fires": 0,
    "events": 0
  },
  "area_violations": 243460,
  "area_violation_fraction": 0.1246722016221827,
  "fire_geom_types": {
    "3": 1952801
  },
  "event_geom_types": {
    "3": 1052198,
    "6": 134823
  },
  "fire_geom_valid": true,
  "event_geom_valid": true,
  "fire_geom_single_polygon": true,
  "event_multipolygon": 134823
}
```

## Artefactos

| Archivo | Bytes |
|---|---:|
| `/home/nacho/NASA/nasa-space-app-modis/prep/data/processed/hotspots.parquet` | 394636318 |
| `/home/nacho/NASA/nasa-space-app-modis/prep/data/processed/incendios.parquet` | 503647987 |
| `/home/nacho/NASA/nasa-space-app-modis/prep/data/processed/eventos.parquet` | 359930704 |
| `/home/nacho/NASA/nasa-space-app-modis/prep/data/qgis/fuego.gpkg` | 4126523392 |

## Cómo abrir en QGIS

1. Abrir `/home/nacho/NASA/nasa-space-app-modis/prep/data/qgis/fuego.gpkg`.
2. Colorear `eventos` por `evento_id` y usar transparencia por `confidence`.
3. Revisar `incendios` en parques nacionales y el flag `es_bosque`.
