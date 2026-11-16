# Fuentes de datos y créditos

Este proyecto usa datos públicos. Los archivos crudos e intermedios **no se
redistribuyen** en el repositorio; se descargan o regeneran con los pipelines de
`prep/` y `pred/`.

## Datos satelitales y meteorológicos

| Fuente | Proveedor | Uso en el proyecto | Enlace |
|---|---|---|---|
| FIRMS — MODIS Active Fire | NASA | Hotspots históricos MODIS (2000–2026) | https://firms.modaps.eosdis.nasa.gov/ |
| FIRMS — VIIRS Active Fire | NASA | Hotspots históricos VIIRS (2012–2026) | https://firms.modaps.eosdis.nasa.gov/ |
| POWER | NASA LaRC | Meteorología histórica diaria | https://power.larc.nasa.gov/ |
| Open-Meteo | Open-Meteo | Pronóstico meteorológico a 7 días para inferencia operativa | https://open-meteo.com/ |
| MCD12Q1 v061 | NASA LP DAAC | Cobertura de suelo anual (2001–2025) | https://lpdaac.usgs.gov/products/mcd12q1v061/ |
| Límites provinciales y departamentales | IGN Argentina | Recorte y polígonos de Córdoba | https://www.ign.gob.ar/ |
| Oceanic Niño Index (ONI) | NOAA CPC | Indicador climático de gran escala | https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php |

## Condiciones de uso

- **NASA FIRMS / NASA POWER / MCD12Q1:** datos públicos de NASA. Se recomienda
  citar la fuente y respetar las políticas de atribución de NASA Earthdata.
- **Open-Meteo:** datos bajo licencia CC BY 4.0; atribuir a Open-Meteo.
- **IGN Argentina:** datos públicos; atribuir al Instituto Geográfico Nacional.
- **NOAA CPC:** datos públicos del gobierno de Estados Unidos.

Cada dataset conserva su licencia original. Este repositorio solo publica
código, modelos y resultados derivados.

## Cómo regenerar los datos

```bash
cd prep
make setup
make aux       # auxiliares: áreas protegidas, límites y cobertura de suelo
make all       # pipeline completo FIRMS 2000-2026
```

Los scripts para bajar estos datos están en
[`pipeline/`](pipeline/README.md). Las URLs y parámetros principales del
pipeline también están en `prep/config/params.yaml`.

## Agradecimientos

- NASA Space Apps Challenge.
- Equipos de NASA FIRMS, NASA POWER, NASA LP DAAC, Open-Meteo, IGN y NOAA CPC
  por mantener datos abiertos.
- Comunidad de software abierto: Python, PyTorch, GeoPandas, Rasterio, DuckDB y
  QGIS.
