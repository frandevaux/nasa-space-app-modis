/* Mente Fría — Vista Mapa */
(function () {
  const T = MF.TIEMPO;
  const W = MF.PROYECCION.W;
  const H = MF.PROYECCION.H;
  const NOMBRES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
  const ABR = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const NIVELES = ['var(--lvl-0)', 'var(--lvl-1)', 'var(--lvl-2)', 'var(--lvl-3)', 'var(--lvl-4)'];

  const state = {
    sel: 'sep24',
    mes: T.ahora,
    focos: true,
    registros: true,
    izq: true,
    der: true,
    punto: { x: 652, y: 404 } // en px del SVG base (1440×900)
  };

  const root = document.getElementById('app');

  function setState(patch) {
    Object.assign(state, patch);
    render();
  }

  /* --- Modelo --- */
  function hotspotsVisibles(focosMes) {
    if (focosMes <= 0) { return []; }
    const n = Math.max(3, Math.min(MF.HOTSPOTS.length, Math.round(MF.HOTSPOTS.length * focosMes / 60)));
    return MF.HOTSPOTS.slice(0, n);
  }

  /* Probabilidad combinada: 1 - Π(1 - conf·peso). Peso = 1 dentro del píxel, cae gaussiano afuera. */
  function leer(x, y, lista) {
    const sigma = 12;
    let q = 1;
    let n = 0;
    lista.forEach((h) => {
      const r = h.lado / 2;
      const dx = Math.max(Math.abs(x - h.x) - r, 0);
      const dy = Math.max(Math.abs(y - h.y) - r, 0);
      const w = (dx === 0 && dy === 0) ? 1 : Math.exp(-(dx * dx + dy * dy) / (sigma * sigma));
      q *= 1 - (h.conf / 100) * w;
      if (w === 1) { n += 1; }
    });
    const pr = 1 - q;
    const banda = pr >= 0.85 ? 'muy alta' : (pr >= 0.6 ? 'alta' : (pr >= 0.35 ? 'media' : (pr >= 0.15 ? 'baja' : 'mínima')));
    const txt = n === 0 ? 'ningún hotspot cubre este punto' : (n === 1 ? '1 hotspot cubre este punto' : n + ' hotspots cubren este punto');
    return { pct: Math.round(pr * 100), n: n, txt: 'Confianza ' + banda + ' · ' + txt };
  }

  function contexto() {
    const sinDatos = state.mes > T.finPronostico;
    const fecha = MF.fechaMes(state.mes);
    const mesSel = sinDatos ? { focos: 0, lo: 0, hi: 0 } : MF.datosMes(fecha);
    return { sinDatos, fecha, mesSel, lista: hotspotsVisibles(mesSel.focos) };
  }

  /* --- Vistas --- */
  function capaCalor(lista) {
    if (!state.focos) { return ''; }
    const celdas = lista.map((h) => `<div class="hotspot" style="left:${((h.x - h.lado / 2) / W * 100).toFixed(3)}%;top:${((h.y - h.lado / 2) / H * 100).toFixed(3)}%;width:${(h.lado / W * 100).toFixed(3)}%;height:${(h.lado / H * 100).toFixed(3)}%;background:rgba(232,89,12,${(h.conf / 100).toFixed(2)})"></div>`).join('');
    const dosFocos = lista.length > 13;
    const flechas = MF.FLECHAS.filter((a) => a.foco === 1 || dosFocos).map((a) => {
      const L = a.largo;
      return `<svg class="arrow" width="${L}" height="10" viewBox="0 0 ${L} 10" style="left:${(a.x / W * 100).toFixed(3)}%;top:${(a.y / H * 100).toFixed(3)}%;transform:translate(-50%,-50%) rotate(${a.ang}deg)"><path d="M1 5H${L - 1}M${L - 5} 1.5L${L - 1} 5L${L - 5} 8.5"/></svg>`;
    }).join('');
    return `<div class="layer layer--heat" aria-hidden="true">${celdas}</div><div class="layer" aria-hidden="true">${flechas}</div>`;
  }

  function capaPines() {
    if (!state.registros) { return ''; }
    return `<div class="layer">${MF.PINES.map((p) => `<button type="button" class="pin" data-pin="${p.grupo}" aria-pressed="${p.grupo === state.sel}" aria-label="Testimonio: ${MF.esc(p.nombre)}" style="left:${p.x}%;top:${p.y}%"><span></span></button>`).join('')}</div>`;
  }

  function panelIzquierdo(ctx) {
    const z = MF.ZONA;
    if (!state.izq) {
      return `<div class="map__left"><button type="button" class="reopen" data-action="toggle-izq" aria-label="Abrir el panel de zona">${MF.esc(z.nombre)}<span>${MF.icon.down}</span></button></div>`;
    }
    const l = leer(state.punto.x, state.punto.y, ctx.lista);
    const ll = MF.aLatLon(state.punto.x, state.punto.y);
    let nota;
    if (ctx.sinDatos) {
      nota = '<div class="note" role="note"><strong>Sin pronóstico todavía</strong><p>El pronóstico llega hasta siete meses adelante. Volvé a una fecha más cercana.</p></div>';
    } else if (state.mes >= T.ahora) {
      nota = `<div class="note note--warn" role="note"><div class="note__head"><strong>Cuidado.</strong><span class="note__bang" aria-hidden="true">!</span></div><p>Esto es una predicción basada en registros satelitales pasados y el pronóstico meteorológico extendido. Puede haber fallas.</p></div>`;
    } else {
      const t = NOMBRES[ctx.fecha.getMonth()] + ' de ' + ctx.fecha.getFullYear();
      nota = `<div class="note" role="note"><strong>Registro de ${t}</strong><p>${ctx.mesSel.focos} focos detectados por MODIS y VIIRS en el mes. Lo habitual para esta época es de ${ctx.mesSel.lo} a ${ctx.mesSel.hi}.</p></div>`;
    }
    return `
    <div class="map__left">
      <section class="panel zone" aria-label="Zona">
        <div class="panel__head"><div class="panel__eyebrow">Zona</div><button type="button" class="icon-btn" data-action="toggle-izq" aria-label="Colapsar el panel de zona"><span>${MF.icon.up}</span></button></div>
        <div class="zone__title"><h1>${MF.esc(z.nombre)}</h1><div>${MF.esc(z.subtitulo)}</div></div>
        <div class="stats">
          <div class="stat"><span>Departamentos</span><span>${z.departamentos}</span></div>
          <div class="stat"><span>Temporada alta</span><span>${MF.esc(z.temporadaAlta)}</span></div>
          <div class="stat"><span>Testimonios guardados</span><span>${z.testimonios}</span></div>
          <div class="stat"><span>Último registro</span><span>${MF.esc(z.ultimoRegistro)}</span></div>
        </div>
      </section>
      <section class="panel reading" aria-label="Punto seleccionado">
        <div class="reading__row">
          <div class="reading__metric"><span>Confianza</span><span>${l.pct}%</span></div>
          <div class="reading__metric"><span>Nº de Hotspots</span><span>${l.n}</span></div>
          <div class="reading__coords"><span>Lat:</span><span>${ll.lat.toFixed(3)}°</span><span>Lon:</span><span>${ll.lon.toFixed(3)}°</span></div>
        </div>
        ${nota}
      </section>
    </div>`;
  }

  function capas() {
    return `
    <div class="layers">
      <div class="panel__eyebrow">Capas del mapa</div>
      <div class="layers__list">
        <button type="button" class="toggle" data-action="toggle-focos" aria-pressed="${state.focos}"><span class="toggle__dot" aria-hidden="true"></span>Focos satelitales</button>
        <button type="button" class="toggle" data-action="toggle-registros" aria-pressed="${state.registros}"><span class="toggle__sq" aria-hidden="true"></span>Testimonios</button>
      </div>
    </div>`;
  }

  function panelDerecho() {
    if (!state.der) {
      return `<div class="map__right"><button type="button" class="reopen" data-action="toggle-der" aria-label="Abrir la bitácora zonal">Bitácora zonal<span>${MF.icon.down}</span></button></div>`;
    }
    return `<div class="map__right map__right--open">${MF.bitacora(state.sel, { enlaceHistorico: true })}</div>`;
  }

  function lineaDeTiempo(ctx) {
    const celdas = [];
    const regla = [];
    for (let i = 0; i < T.meses; i++) {
      let bg = 'var(--lvl-0)';
      if (i < T.ahora) { bg = NIVELES[MF.nivelFocos(MF.datosMes(MF.fechaMes(i)).focos)]; }
      else if (i <= T.ahora + 1) { bg = 'var(--warn)'; }
      else if (i <= T.finPronostico) { bg = 'var(--forecast)'; }
      celdas.push(`<div style="background:${bg}"></div>`);
      const f = MF.fechaMes(i);
      const enero = f.getMonth() === 0;
      regla.push(`<span class="${enero ? 'year' : ''}">${enero ? "'" + String(f.getFullYear()).slice(2) : ABR[f.getMonth()]}</span>`);
    }
    const titulo = NOMBRES[ctx.fecha.getMonth()] + ' de ' + ctx.fecha.getFullYear();
    const sub = state.mes >= T.ahora && !ctx.sinDatos ? 'Pronóstico' : NOMBRES[ctx.fecha.getMonth()];
    const semana = state.mes === T.ahora ? 'Semana ' + T.semanaActual : '';
    const frac = (state.mes + 0.5) / T.meses;
    return `
    <section class="panel timeline" aria-label="Línea de tiempo">
      <div class="timeline__top">
        <div class="timeline__title"><strong>${titulo}</strong><span><span>${sub}</span><span>${semana}</span></span></div>
        <div class="transport" role="group" aria-label="Moverse por la línea de tiempo">
          <button type="button" data-move="-50" aria-label="Retroceder 50 meses">-50</button>
          <button type="button" data-move="-5" aria-label="Retroceder 5 meses">-5</button>
          <button type="button" class="transport__play" data-action="play" aria-label="Reproducir la línea de tiempo">${MF.icon.play}</button>
          <button type="button" data-move="5" aria-label="Avanzar 5 meses">+5</button>
          <button type="button" data-move="50" aria-label="Avanzar 50 meses">+50</button>
        </div>
        <div class="timeline__range">Línea de tiempo · nov 2023 a nov 2026 · pronóstico a 7 meses</div>
      </div>
      <div>
        <div class="track">
          <div class="cells" aria-hidden="true">${celdas.join('')}</div>
          <div class="playhead" aria-hidden="true" style="left:calc(5px + (100% - 10px) * ${frac.toFixed(4)})"></div>
          <input type="range" min="0" max="${T.meses - 1}" step="1" value="${state.mes}" aria-label="Mes de la línea de tiempo" data-range>
        </div>
        <div class="ruler" aria-hidden="true">${regla.join('')}</div>
      </div>
    </section>`;
  }

  function render() {
    const ctx = contexto();
    root.innerHTML = `
    <div class="map">
      <img class="map__base" src="assets/mapa-cordoba.svg" alt="Mapa de la provincia de Córdoba con sus 26 departamentos">
      <svg aria-hidden="true" width="0" height="0" style="position:absolute"><defs><filter id="franjas" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="9"/><feComponentTransfer><feFuncA type="discrete" tableValues="0 0 0.1 0.2 0.2 0.2 0.2 0.42 0.42 0.42 0.42 0.42 0.66 0.66 0.66 0.66 0.66 0.92 0.92 0.92"/></feComponentTransfer></filter></defs></svg>
      ${capaCalor(ctx.lista)}
      <button type="button" class="map__hit" data-hit aria-label="Mapa de confianza. Tocá un punto para ver su confianza, hotspots y coordenadas en el panel de zona."></button>
      <div class="map__point" aria-hidden="true" style="left:${(state.punto.x / W * 100).toFixed(3)}%;top:${(state.punto.y / H * 100).toFixed(3)}%"></div>
      <div class="map__tip" aria-hidden="true" hidden data-tip><strong></strong><span></span></div>
      ${capaPines()}
      ${MF.header('mapa')}
      ${panelIzquierdo(ctx)}
      ${capas()}
      ${panelDerecho()}
      ${lineaDeTiempo(ctx)}
    </div>`;
    root._lista = ctx.lista;
  }

  /* Convierte un evento del mouse a px del SVG base. */
  function aSvg(e, el) {
    const r = el.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    return { px, py, x: px / r.width * W, y: py / r.height * H };
  }

  /* --- Eventos (delegados) --- */
  root.addEventListener('click', (e) => {
    const t = e.target.closest('[data-action],[data-pin],[data-entry],[data-move],[data-hit]');
    if (!t) { return; }
    if (t.dataset.hit !== undefined) {
      const p = e.detail === 0 ? { x: W * 0.453, y: H * 0.449 } : aSvg(e, t); // e.detail 0 = teclado
      setState({ punto: { x: p.x, y: p.y } });
      return;
    }
    if (t.dataset.pin || t.dataset.entry) {
      const id = t.dataset.pin || t.dataset.entry;
      const r = MF.BITACORA.find((x) => x.id === id);
      setState({ sel: id, mes: r ? r.mes : state.mes });
      return;
    }
    if (t.dataset.move) {
      setState({ mes: Math.max(0, Math.min(T.meses - 1, state.mes + Number(t.dataset.move))) });
      return;
    }
    const a = t.dataset.action;
    if (a === 'toggle-izq') { setState({ izq: !state.izq }); }
    if (a === 'toggle-der') { setState({ der: !state.der }); }
    if (a === 'toggle-focos') { setState({ focos: !state.focos }); }
    if (a === 'toggle-registros') { setState({ registros: !state.registros }); }
    if (a === 'play') { /* TODO: animar la línea de tiempo (setInterval sobre state.mes). */ }
  });

  root.addEventListener('change', (e) => {
    if (e.target.matches('[data-range]')) { setState({ mes: Number(e.target.value) }); }
  });

  /* El tooltip se actualiza directo en el DOM para no re-renderizar en cada mousemove. */
  root.addEventListener('mousemove', (e) => {
    const hit = e.target.closest('[data-hit]');
    const tip = root.querySelector('[data-tip]');
    if (!tip) { return; }
    if (!hit) { tip.hidden = true; return; }
    const p = aSvg(e, hit);
    const l = leer(p.x, p.y, root._lista || []);
    tip.hidden = false;
    tip.style.left = Math.round(p.px) + 'px';
    tip.style.top = Math.round(p.py) + 'px';
    tip.querySelector('strong').textContent = l.pct + ' % de confianza';
    tip.querySelector('span').textContent = l.txt;
  });
  root.addEventListener('mouseleave', () => {
    const tip = root.querySelector('[data-tip]');
    if (tip) { tip.hidden = true; }
  });

  render();
})();
