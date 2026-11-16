# Mente Fría: prototipo navegable (NASA Space Apps Mendoza 2026, equipo FIREWALL)

Es la exportación en código del prototipo de diseño. Incluye dos vistas, **Mapa** (`index.html`) y **Calendario** (`calendario.html`). Está hecho en HTML, CSS y JavaScript sin frameworks ni build, así que se puede leer de punta a punta y pasar al stack que elija el equipo (React, Svelte, lo que sea).

> **Importante:** todos los datos son de **ejemplo**: focos, hotspots, testimonios, pronóstico y la temporada alta. Están juntos en `js/data.js` para que sea fácil reemplazarlos por fuentes reales.

## Cómo correrlo

Se abre `index.html` directo en el navegador, o se levanta un servidor estático:

```bash
npx serve .          # o: python3 -m http.server
```

Lo único que pide de internet son las fuentes de Google Fonts (Inter e Inter Tight).

## Estructura

```
index.html          Vista Mapa
calendario.html     Vista Calendario
css/styles.css      Estilos compartidos y tokens de diseño (variables CSS en :root)
js/data.js          Datos de ejemplo, configuración de zona, proyección del mapa y línea de tiempo
js/common.js        Íconos, header y bitácora (se usan en las dos vistas)
js/mapa.js          Estado, render y eventos de la vista Mapa
js/calendario.js    Estado, render y eventos de la vista Calendario
assets/mapa-cordoba.svg   Mapa base de 1440×900 con los 26 departamentos de Córdoba
```

Cada vista sigue el mismo patrón: un objeto `state`, una función `render()` que arma el HTML con template strings, y eventos delegados en `#app` con atributos `data-*`. El tooltip del mapa es la excepción: se actualiza directo en el DOM en cada `mousemove` para no re-renderizar toda la vista. Pasarlo a componentes debería ser casi 1:1.

## Tokens de diseño

Están en `:root` de `css/styles.css`:

| Token | Valor | Uso |
|---|---|---|
| `--ink` | `#17191C` | Texto, botones primarios, chips de eventos |
| `--muted` | `#5F6670` | Texto secundario |
| `--line` | `#E3E6EA` | Bordes |
| `--surface-2` | `#F4F5F6` | Fondos de tarjetas internas |
| `--accent` | `#C2410C` | Naranja de focos |
| `--warn` | `#FFF587` | Aviso de "Cuidado" y pronóstico cercano |
| `--forecast` | `#F6F0A6` | Pronóstico lejano en la línea de tiempo |
| `--lvl-0…4` | grises a naranja | Escala de actividad (línea de tiempo y heatmap) |
| `--day-0…4` | blanco a naranja | Tinte de días en el calendario |

Las fuentes son **Inter** para el texto e **Inter Tight** para títulos y números grandes, las dos de Google Fonts.

## Mapa: cómo conectar datos reales

**Proyección.** El SVG base usa una proyección equirectangular con corrección por coseno, centrada en Córdoba (`MF.PROYECCION` en `data.js`):

```js
x = X0 + (lon - cx) * k * s
y = Y0 - (lat - cy) * s
```

`MF.aPixel(lat, lon)` ubica un hotspot real sobre el mapa. `MF.aLatLon(x, y)` hace la cuenta inversa y es lo que alimenta las coordenadas del panel cuando se toca el mapa. Si cambia el SVG, también cambian estas constantes.

**Hotspots.** Hoy `MF.HOTSPOTS` está en px del SVG. Para usar NASA FIRMS (MODIS/VIIRS) habría que convertir cada detección:

```js
const { x, y } = MF.aPixel(det.latitude, det.longitude);
{ x, y, lado: /* tamaño del píxel del sensor en px */, conf: det.confidence, sensor: det.instrument }
```

Ojo: a esta escala (provincia completa) 1 km mide más o menos 1 px. El prototipo **agranda** los hotspots para que se vean. Con datos reales conviene definir un tamaño mínimo de dibujo o agrupar las detecciones.

**Confianza de un punto.** La calcula `leer()` en `mapa.js`: `1 − Π(1 − conf·peso)`. El peso vale 1 dentro del píxel del hotspot y baja con una gaussiana (σ = 12 px) hacia afuera. "Nº de Hotspots" cuenta cuántos píxeles cubren el punto.

**Mancha de confianza.** Los hotspots se dibujan como `div`s semitransparentes y pasan por el filtro SVG `#franjas`, que los desenfoca y cuantiza la opacidad en 4 bandas (baja, media, alta y muy alta).

**Línea de tiempo.** Tiene 70 meses desde nov 2023 (`MF.TIEMPO`). "Ahora" es el índice 36 (nov 2026), los meses 36 a 42 son pronóstico (en amarillo) y después no hay datos. El panel izquierdo cambia según el mes elegido: muestra el registro histórico, el aviso **"Cuidado."** si es pronóstico, o "Sin pronóstico todavía".

## Calendario

Muestra septiembre de 2024 de ejemplo (`MF.MES_CALENDARIO`) y un heatmap de 8 temporadas de julio a junio. Las dos tarjetas se pueden reordenar, con drag and drop o con el botón ⇅.

## Qué falta implementar (está dibujado pero no funciona)

- **Play** de la línea de tiempo (hay un `TODO` en `mapa.js`).
- **Buscador** de locación y **selector de año**.
- **Cuenta de usuario**.
- **Calendario:** flechas de mes, selector Semana/Mes/Temporada y checkboxes de capas.
- **"Cargar un registro"** y **"Ver el histórico de testimonios"** en el calendario.
- **Versión mobile:** el layout está pensado para 1440×900 de escritorio.

## Fuente del mapa base

Los límites departamentales salen del repositorio público `mgaitan/departamentos_argentina` en GitHub. El SVG se generó a partir de ese GeoJSON. Antes de publicar, conviene confirmar la licencia del repositorio y citar la fuente oficial (IGN).
