/*
 * Mente Fría — datos del prototipo.
 * TODO lo que está en este archivo es de EJEMPLO (mock). Reemplazar por las fuentes reales:
 *  - hotspots: NASA FIRMS (MODIS / VIIRS) — lat, lon, confidence, tamaño de píxel, fecha.
 *  - focos por mes / día: agregado de FIRMS por zona.
 *  - testimonios y bitácora: base propia de registros cargados por usuarios.
 *  - pronóstico: modelo propio (registros pasados + pronóstico meteorológico extendido).
 */
window.MF = window.MF || {};

MF.ZONA = {
  nombre: 'Córdoba',
  subtitulo: 'Provincia completa · Argentina',
  busqueda: 'Córdoba, Argentina',
  departamentos: 26,
  temporadaAlta: 'Agosto a octubre',      // verificar con fuente oficial antes de mostrar
  temporadaAltaCorta: 'Ago. a oct.',
  testimonios: 14,
  ultimoRegistro: '23 sep 2024'
};

/*
 * Proyección del mapa base (assets/mapa-cordoba.svg, 1440×900).
 * Equirectangular con corrección de coseno a la latitud media de Córdoba.
 *   x = X0 + (lon - cx) * k * s
 *   y = Y0 - (lat - cy) * s
 * Sirve para ubicar hotspots reales (lat/lon de FIRMS) sobre el SVG y para leer lat/lon del clic.
 */
MF.PROYECCION = { s: 120.006, k: 0.84573, cx: -63.77144, cy: -32.25028, X0: 738, Y0: 440, W: 1440, H: 900 };

MF.aPixel = function (lat, lon) {
  const p = MF.PROYECCION;
  return { x: p.X0 + (lon - p.cx) * p.k * p.s, y: p.Y0 - (lat - p.cy) * p.s };
};
MF.aLatLon = function (x, y) {
  const p = MF.PROYECCION;
  return { lon: p.cx + (x - p.X0) / (p.k * p.s), lat: p.cy - (y - p.Y0) / p.s };
};

/* Línea de tiempo: 70 meses desde nov 2023. "Ahora" = índice 36 (nov 2026); pronóstico hasta el 42. */
MF.TIEMPO = { inicio: new Date(2023, 10, 1), meses: 70, ahora: 36, finPronostico: 42, semanaActual: 3 };

/* Promedio histórico de focos por mes (ene..dic) — EJEMPLO. */
MF.FOCOS_MEDIO = [5, 4, 3, 4, 8, 14, 28, 50, 60, 38, 15, 7];

/* Hotspots de ejemplo en coordenadas del SVG (px). conf = confianza 0–100. */
MF.HOTSPOTS = (function () {
  const base = [[200, 250, 40, 55], [236, 230, 40, 90], [262, 262, 28, 55], [228, 276, 20, 90], [282, 238, 20, 90], [250, 214, 14, 90], [214, 300, 14, 25], [296, 274, 14, 55], [186, 222, 28, 25], [270, 296, 20, 55], [244, 250, 60, 25], [316, 214, 20, 55], [326, 236, 14, 25], [372, 150, 40, 90], [404, 170, 28, 90], [430, 140, 40, 55], [392, 128, 20, 90], [420, 196, 20, 55], [356, 186, 14, 90], [452, 176, 14, 25], [446, 112, 28, 25], [380, 206, 14, 55], [410, 150, 60, 55], [340, 210, 28, 55]];
  const centros = [{ bx: 250, by: 262, x: 652, y: 404 }, { bx: 410, by: 160, x: 668, y: 292 }];
  const esc = 0.6;
  return base.map((b, i) => {
    const c = centros[i < 13 ? 0 : 1];
    return {
      x: c.x + (b[0] - c.bx) * esc,
      y: c.y + (b[1] - c.by) * esc,
      lado: b[2] * esc,
      conf: b[3],
      sensor: b[2] >= 40 ? 'MODIS' : 'VIIRS',
      foco: i < 13 ? 'Foco Calamuchita' : 'Foco Punilla'
    };
  });
})();

/* Flechas de propagación de ejemplo: [x, y, ángulo°, largo, foco(1|2)] en px del SVG. */
MF.FLECHAS = (function () {
  const fl = [[215, 285, -20, 12, 1], [250, 275, -28, 14, 1], [285, 262, -32, 18, 1], [228, 240, -25, 12, 1], [265, 232, -35, 16, 1], [372, 182, -32, 22, 2], [395, 170, -30, 24, 2], [420, 160, -28, 22, 2], [440, 145, -25, 18, 2], [452, 130, -20, 14, 2], [395, 135, -30, 12, 2], [425, 190, -10, 10, 2]];
  const centros = { 1: { bx: 250, by: 262, x: 652, y: 404 }, 2: { bx: 410, by: 160, x: 668, y: 292 } };
  return fl.map((a) => {
    const c = centros[a[4]];
    return { x: c.x + (a[0] - c.bx) * 0.6, y: c.y + (a[1] - c.by) * 0.6, ang: a[2], largo: a[3], foco: a[4] };
  });
})();

/* Testimonios (pines) — x/y en % del mapa. */
MF.PINES = [
  { id: 'ev', grupo: 'sep24', x: 46.4, y: 31.6, nombre: 'Evacuación preventiva, 13 sep 2024' },
  { id: 'cf', grupo: 'sep24', x: 47.9, y: 34.4, nombre: 'Cortafuego en camino vecinal, 14 sep 2024' },
  { id: 'qp', grupo: 'jun24', x: 44.0, y: 47.6, nombre: 'Quema prescripta, 22 jun 2024' },
  { id: 'ct', grupo: 'ago25', x: 41.4, y: 39.6, nombre: 'Foco contenido, 18 ago 2025' }
];

/* Bitácora zonal — resúmenes por IA (ejemplo). mes = índice en la línea de tiempo. */
MF.BITACORA = [
  {
    id: 'ago25', mes: 21, periodo: 'Agosto de 2025', cuantos: '3 testimonios',
    titulo: 'Foco contenido en la primera hora',
    texto: 'Una cuadrilla adelantada por un alerta de calor llegó antes de que el satélite registrara el foco. Menos de una hectárea afectada.',
    leccion: 'Para la próxima: mantener la guardia adelantada en días de alerta.'
  },
  {
    id: 'sep24', mes: 10, periodo: 'Septiembre de 2024', cuantos: '5 testimonios',
    titulo: 'Incendio de tres días con evacuación preventiva',
    texto: 'Un foco en pastizal serrano creció con viento norte. Se evacuó un paraje antes de la rotación del viento y el frente se frenó con un cortafuego apoyado en un camino vecinal. Sin heridos.',
    leccion: ''
  },
  {
    id: 'jun24', mes: 7, periodo: 'Junio de 2024', cuantos: '2 testimonios',
    titulo: 'Quema prescripta junto a una ruta',
    texto: 'Antes de la temporada se quemó de forma controlada una franja de pasto seco, con brigada presente y aviso previo a los vecinos. En la temporada siguiente no hubo focos en ese tramo.',
    leccion: ''
  }
];

/* Calendario: septiembre 2024 (empieza domingo → 6 celdas vacías con semana Lun–Dom). */
MF.MES_CALENDARIO = {
  titulo: 'Septiembre de 2024',
  vaciasInicio: 6,
  dias: 30,
  focos: [null, 2, 3, 0, 1, 3, 3, 5, 6, 6, 14, 13, 26, 42, 37, 6, 4, 3, 1, 5, 3, 2, 2, 1, 2, 4, 1, 2, 1, 0, 1],
  nivel: [null, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 3, 4, 4, 1, 1, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
  eventos: {
    9: ['Alerta', 'Alerta por viento norte, 9 de septiembre'],
    13: ['Evacuación', 'Evacuación preventiva, 13 de septiembre'],
    14: ['Cortafuego', 'Cortafuego en camino vecinal, 14 de septiembre'],
    17: ['Controlado', 'Fuego controlado, 17 de septiembre'],
    23: ['Revisión', 'Revisión posterior, 23 de septiembre']
  }
};

/* Generador pseudoaleatorio determinístico (solo para los datos de ejemplo). */
MF.rnd = function (a, b, c) {
  const x = Math.sin(a * 127.1 + b * 311.7 + c * 74.7) * 43758.5453;
  return x - Math.floor(x);
};

MF.fechaMes = function (i) {
  const d = new Date(MF.TIEMPO.inicio);
  d.setMonth(d.getMonth() + i);
  return d;
};

/* Focos del mes (EJEMPLO). Reemplazar por el conteo real de FIRMS. */
MF.datosMes = function (fecha) {
  const m = fecha.getMonth();
  const y = fecha.getFullYear();
  const mid = MF.FOCOS_MEDIO[m];
  let factor = 0.5 + 1.3 * MF.rnd(y, m + 1, 7);
  if (y === 2024 && m === 8) { factor = 2.1; }
  return { focos: Math.round(mid * factor), lo: Math.max(1, Math.round(mid * 0.7)), hi: Math.round(mid * 1.3) };
};

MF.nivelFocos = function (focos) {
  if (focos >= 50) { return 4; }
  if (focos >= 30) { return 3; }
  if (focos >= 15) { return 2; }
  if (focos >= 6) { return 1; }
  return 0;
};
