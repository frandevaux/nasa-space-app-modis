## Predicción de nuevos hotspots

**Objetivo.** El calendario armonizado describe la actividad de fuego que ya ocurrió; la etapa de predicción busca anticipar dónde pueden aparecer nuevos hotspots en los siete días siguientes a una detección. El modelo no predice fires ni firewaves de forma directa: predice hotspots y, después, los agrupa con la misma lógica de las secciones 3 y 4. De esta manera se mantiene una única definición de fire y firewave en todo el proyecto y no se crea una entidad nueva.

**Alcance y datos.** La prueba piloto se realizó en Córdoba, sobre una grilla de celdas de 1 km en una proyección de áreas iguales (EPSG:6933). Cada muestra se ancla en un hotspot observado y construye un parche de 32 × 32 celdas (32 × 32 km) con 14 días de historia y un horizonte de 7 días. Para no repetir parches casi idénticos, se usa una muestra por celda-día con al menos un hotspot; la celda-día es solo el punto de lectura, no una entidad nueva: el modelo sigue trabajando con hotspots.

Los períodos se separaron temporalmente para que la validación y el test no compartan información con el entrenamiento:

| Período | Fechas | Hotspots | Muestras (celda-día) |
|---|---|---:|---:|
| Entrenamiento | 2019-01-01 → 2025-07-24 | 91.074 | 32.661 |
| Validación | 2025-08-01 → 2026-07-24 | 6.133 | 2.913 |
| Test | 2026-08-01 → 2026-11-07 | 2.223 | 1.145 |

Se eligió 2019-2025 porque concentra el régimen reciente de sensores y de combustible. En el conjunto resultante, el 0,45 % de las celdas-día son positivas y el 72,3 % de las anclas tiene al menos un hotspot futuro dentro del parche. La validación y el test se mantuvieron separados del entrenamiento, con una purga de siete días en los bordes para que ninguna etiqueta cruce el límite.

**Representación.** Cada muestra combina 20 canales dinámicos de historia, 7 canales de clima futuro, 12 canales estáticos y un vector de 17 atributos del hotspot ancla. Los canales de historia resumen el campo de hotspots —conteo, presencia, densidad gaussiana, FRP, confianza, sensor y día/noche— junto con la meteorología observada. Los canales futuros contienen el pronóstico de siete días. Los estáticos incluyen la máscara de Córdoba, el departamento, la cobertura de suelo del año anterior, áreas protegidas, climatología de fuego, distancia al centro del parche, distancia al hotspot conocido más cercano y días desde el último hotspot. La cobertura de suelo se toma del año anterior para no incorporar cicatrices del mismo año del evento [P4]. La meteorología proviene de NASA POWER y de derivados como VPD, días sin lluvia y precipitación acumulada a 7 y 30 días [P2]. El vector del ancla incluye FRP, confianza, sensor, satélite, tamaño de píxel, día/noche, hora, estación y ONI del trimestre anterior.

**Modelo y entrenamiento.** La red tiene tres partes. Una CNN compartida codifica cada día de historia; una LSTM resume la secuencia de 14 días; y un decoder convolucional, condicionado por el vector del ancla y por el clima futuro de cada día, produce siete mapas de 32 × 32 con la probabilidad de hotspot [P7]. El modelo tiene alrededor de 2,5 millones de parámetros y se entrenó en una GPU RTX 4060 de 8 GB.

Como los hotspots son muy raros frente al total de celdas, la pérdida combina una BCE ponderada con `pos_weight = 75` y una penalización por parche:

```
L = BCE_pos + λ · L_patch
L_patch = −log(max p(celda) sobre las celdas con hotspot real)
```

El segundo término obliga a que cada parche-día con hotspots futuros tenga al menos una celda con probabilidad alta; es la forma de penalizar con fuerza los falsos negativos sin crear una entidad de fire. Se aplicaron rotaciones, espejados y traslaciones de hasta cuatro celdas, y se usó AdamW con learning rate 2 × 10⁻⁴, weight decay 10⁻³ y early stopping sobre la validación [P8].

**Evaluación de hotspots.** La evaluación principal es libre de umbral: PR-AUC, ROC-AUC y Brier, acompañados de recall, precisión y F1 a distintos cortes. También se mide el *patch hit rate*: la fracción de parches-día con hotspot futuro en los que al menos una celda positiva supera 0,5. Se comparó contra dos baselines: persistencia (repetir los hotspots del día del ancla) y climatología (frecuencia histórica por celda y mes, calculada solo con entrenamiento).

| Métrica | Validación | Test | Persistencia (val) | Climatología (val) |
|---|---:|---:|---:|---:|
| PR-AUC | **0,0122** | **0,0090** | 0,0068 | 0,0041 |
| ROC-AUC | 0,856 | 0,837 | 0,570 | 0,607 |
| Brier | 0,102 | 0,127 | 0,009 | 0,002 |
| Recall@0,2 | 0,896 | 0,900 | 0,147 | 0,000 |
| Recall@0,5 | 0,645 | 0,671 | 0,147 | 0,000 |
| Recall@0,7 | 0,432 | 0,439 | 0,147 | 0,000 |
| Patch hit | 0,769 | 0,792 | — | — |

El modelo supera a persistencia y climatología en PR-AUC y ROC-AUC, y mantiene un recall alto cuando se baja el umbral, que es el comportamiento buscado para alerta temprana. El Brier es mayor que el de los baselines porque el modelo entrega probabilidades más extremas; por eso la calibración se reporta por separado [P9][P10].

**De hotspots predichos a fires y firewaves.** Los hotspots con probabilidad superior a un umbral se deduplican por celda-día y se pasan por la lógica clásica de las secciones 3 y 4: clustering por contacto de píxeles en ventanas de 12 horas para formar fires, y enlace con buffer de 1 km —5 km en área protegida con bosque—, ventana de 5 días e inactividad de 5 días para formar firewaves [P6]. No se predicen fires directamente: se derivan de los hotspots con el mismo criterio que el resto del pipeline.

La comparación con los fires y firewaves reales usa una tolerancia estricta: centroides a 1 km para fires, 2 km para firewaves, y fechas dentro de ±1 día. Con el punto de operación 0,8 / 200 hotspots por día se obtuvieron:

| | Validación | Test |
|---|---:|---:|
| Fires predichos | 12.619 | 3.245 |
| Firewaves predichos | 1.015 | 221 |
| Fires: precision / recall / F1 | 0,060 / 0,159 / 0,088 | 0,067 / 0,125 / 0,087 |
| Firewaves: precision / recall / F1 | 0,442 / 0,134 / 0,206 | 0,471 / 0,083 / 0,140 |

El barrido de umbral y presupuesto muestra el compromiso entre recall y precisión. El mayor F1 de firewaves se obtuvo con 0,8 / 1000 (0,219), el mejor equilibrio precisión-recall con 0,9 / 500 (precisión 0,444, recall 0,139, F1 0,212) y la mayor precisión con 0,9 / 50 (precisión 0,594, recall 0,099). La coincidencia estricta de centroides y fechas explica en parte el recall bajo a nivel de firewave; el recall de hotspots es mucho mayor.

**Predicción operativa.** La última predicción se generó con los datos disponibles hasta el 13 de noviembre de 2026: 15 celdas-día ancla, 271 hotspots, 131 fires y 20 firewaves para el período 2026-11-14 a 2026-11-20. La historia meteorológica se tomó de POWER y los siete días futuros de Open-Meteo [P3]; si falta una variable o un día, se rellena con la última observación y se registra. El resultado queda en `pred/predictions/latest_2026-11-13/`, con GeoJSON y Parquet para mapa y análisis.

**Limitaciones.** El clima de entrenamiento es observado, no pronosticado: usar POWER como proxy del pronóstico hace que las métricas de validación sean optimistas frente a una operación real. La validación y el test incluyen cambios de sensores —NOAA-21 y la puesta en standby de Terra— que no están representados por igual en el entrenamiento. El test de 2026 es corto, la coincidencia de fires y firewaves es estricta y el modelo es experimental: complementa el calendario armonizado, no lo reemplaza.

### Fuentes de la sección

- **[P1]** NASA Earthdata, *FIRMS Frequently Asked Questions* y *FIRMS Active Fire Data Attributes (MODIS/VIIRS)*. https://www.earthdata.nasa.gov/data/tools/firms/faq · https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs
- **[P2]** NASA POWER Project, *Prediction Of Worldwide Energy Resources*; Gelaro, R. et al. (2017), *MERRA-2*. *Journal of Climate* 30(14), 5419–5454. https://power.larc.nasa.gov/ · https://doi.org/10.1175/JCLI-D-16-0758.1
- **[P3]** Zippenfenig, P. (2023), *Open-Meteo.com Weather API*. Zenodo. https://doi.org/10.5281/zenodo.7970649
- **[P4]** Sulla-Menashe, D. et al. (2019), *Hierarchical mapping of annual global land cover 2001 to present: The MODIS Collection 6 Land Cover product*. *Remote Sensing of Environment* 222, 183–194. https://doi.org/10.1016/j.rse.2018.12.013
- **[P5]** Instituto Geográfico Nacional (IGN) de Argentina, servicio WFS, capa `ign:area_protegida`. https://wms.ign.gob.ar/geoserver/ows?service=wfs&version=2.0.0&request=DescribeFeatureType&typeNames=ign:area_protegida
- **[P6]** Chen, Y. et al. (2022), *California wildfire spread derived using VIIRS satellite observations and an object-based tracking system*. *Scientific Data* 9:249. https://doi.org/10.1038/s41597-022-01343-0
- **[P7]** LeCun, Y. et al. (1998), *Gradient-based learning applied to document recognition*. *Proceedings of the IEEE* 86(11), 2278–2324. https://doi.org/10.1109/5.726791 · Hochreiter, S. & Schmidhuber, J. (1997), *Long Short-Term Memory*. *Neural Computation* 9(8), 1735–1780. https://doi.org/10.1162/neco.1997.9.8.1735
- **[P8]** Lin, T.-Y. et al. (2017), *Focal Loss for Dense Object Detection*. *ICCV 2017*. https://doi.org/10.1109/ICCV.2017.324
- **[P9]** Saito, T. & Rehmsmeier, M. (2015), *The Precision-Recall Plot Is More Informative than the ROC Plot When Evaluating Binary Classifiers on Imbalanced Datasets*. *PLoS ONE* 10(3), e0118432. https://doi.org/10.1371/journal.pone.0118432
- **[P10]** Guo, C. et al. (2017), *On Calibration of Modern Neural Networks*. *ICML 2017*. arXiv:1706.04599
- **[P11]** Hersbach, H. et al. (2020), *The ERA5 global reanalysis*. *Quarterly Journal of the Royal Meteorological Society* 146(730), 1999–2049. https://doi.org/10.1002/qj.3803

*Las referencias de esta sección se numeran aparte (`P`) para no mezclarlas con las del informe principal.*
