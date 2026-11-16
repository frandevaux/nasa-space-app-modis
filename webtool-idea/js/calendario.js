/* Mente Fría — Vista Calendario */
(function () {
  const M = MF.MES_CALENDARIO;
  const LVL = ['var(--lvl-0)', 'var(--lvl-1)', 'var(--lvl-2)', 'var(--lvl-3)', 'var(--lvl-4)'];
  const DIA = ['var(--day-0)', 'var(--day-1)', 'var(--day-2)', 'var(--day-3)', 'var(--day-4)'];

  const state = { dia: 13, resumen: 'sep24', izq: true, der: true, temporadasArriba: true, arrastrando: null };
  const root = document.getElementById('app');

  function setState(patch) {
    Object.assign(state, patch);
    render();
  }

  /* Heatmap de 8 temporadas (jul→jun), semana por semana — EJEMPLO, pico en septiembre. */
  function temporadas() {
    const filas = [];
    for (let y = 0; y < 8; y++) {
      const anio = 2018 + y;
      const abierta = anio === 2024;
      const yearF = 0.6 + 0.9 * MF.rnd(3, y + 1, 99);
      const celdas = [];
      for (let w = 0; w < 52; w++) {
        const season = Math.exp(-Math.pow(w - 10, 2) / 60);
        const bump = 0.25 * Math.exp(-Math.pow(w - 49, 2) / 12);
        const v = 0.85 * (season + bump) * yearF * (0.45 + MF.rnd(3, y + 1, w + 1));
        let lvl = v >= 0.85 ? 4 : v >= 0.5 ? 3 : v >= 0.25 ? 2 : v >= 0.08 ? 1 : 0;
        const enMes = abierta && w >= 9 && w <= 12;
        if (enMes && (w === 10 || w === 11)) { lvl = 4; }
        celdas.push(`<div class="${enMes ? 'is-marked' : ''}" style="background:${LVL[lvl]}"></div>`);
      }
      const etiqueta = anio + '/' + String((anio + 1) % 100).padStart(2, '0');
      filas.push(`<div class="seasons__row"><div class="seasons__label ${abierta ? 'is-open' : ''}">${etiqueta}</div><div class="seasons__weeks">${celdas.join('')}</div></div>`);
    }
    const meses = ['Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun'].map((m) => `<span>${m}</span>`).join('');
    return `
    <div class="panel card" draggable="true" data-drag="temporadas" style="order:${state.temporadasArriba ? 1 : 2}">
      <div class="card__head">
        <div><span class="grip" title="Arrastrá para reordenar" aria-hidden="true">${MF.icon.grip}</span><h2>Ocho temporadas, semana por semana</h2></div>
        <div><span class="hint">De julio a junio</span><button type="button" class="nav-btn" data-action="swap" aria-label="${state.temporadasArriba ? 'Mover las temporadas abajo' : 'Mover las temporadas arriba'}"><span>${MF.icon.swap}</span></button></div>
      </div>
      <div class="seasons" role="img" aria-label="Actividad de quema por semana en las últimas ocho temporadas. Se concentra entre agosto y octubre. Septiembre de 2024 está resaltado.">
        <div class="seasons__row"><div class="seasons__label"></div><div class="seasons__months">${meses}</div></div>
        ${filas.join('')}
      </div>
    </div>`;
  }

  function mes() {
    const celdas = [];
    const vacia = '<div class="day" style="background:transparent"></div>';
    for (let i = 0; i < M.vaciasInicio; i++) { celdas.push(vacia); }
    for (let d = 1; d <= M.dias; d++) {
      const lvl = M.nivel[d];
      const n = M.focos[d];
      const e = M.eventos[d];
      const chip = e ? `<button type="button" class="event" data-dia="${d}" aria-pressed="${state.dia === d}" aria-label="${MF.esc(e[1])}">${MF.esc(e[0])}</button>` : '';
      celdas.push(`<div class="day" style="background:${DIA[lvl]};border-color:${lvl === 0 ? 'var(--line)' : DIA[lvl]}"><div class="day__top"><span>${d}</span><span>${n === 1 ? '1 foco' : n + ' focos'}</span></div>${chip}</div>`);
    }
    while (celdas.length % 7 !== 0) { celdas.push(vacia); }
    const dias = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'].map((x) => `<span>${x}</span>`).join('');
    return `
    <div class="panel card" draggable="true" data-drag="mes" style="order:${state.temporadasArriba ? 2 : 1}">
      <div class="card__head">
        <div>
          <span class="grip" title="Arrastrá para reordenar" aria-hidden="true">${MF.icon.grip}</span>
          <button type="button" class="nav-btn" aria-label="Mes anterior"><span>${MF.icon.left}</span></button>
          <button type="button" class="nav-btn" aria-label="Mes siguiente"><span>${MF.icon.right}</span></button>
          <h2 class="month">${MF.esc(M.titulo)}</h2>
        </div>
        <div>
          <div class="segmented" role="group" aria-label="Escala del calendario">
            <button type="button" aria-pressed="false">Semana</button><button type="button" aria-pressed="true">Mes</button><button type="button" aria-pressed="false">Temporada</button>
          </div>
          <button type="button" class="nav-btn" data-action="swap" aria-label="${state.temporadasArriba ? 'Mover el mes arriba' : 'Mover el mes abajo'}"><span>${MF.icon.swap}</span></button>
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px">
        <div class="weekdays">${dias}</div>
        <div class="days">${celdas.join('')}</div>
      </div>
      <p class="hint" style="margin:0">Prototipo · los focos y los registros de este mes son ejemplos, no datos reales.</p>
    </div>`;
  }

  function izquierda() {
    const z = MF.ZONA;
    if (!state.izq) {
      return `<button type="button" class="cal__reopen" data-action="toggle-izq" aria-label="Abrir el panel de localización"><span>${MF.icon.right}</span></button>`;
    }
    const capas = ['Focos satelitales', 'Alertas', 'Evacuaciones', 'Procedimientos', 'Controles y lecciones']
      .map((c) => `<label><input type="checkbox" checked>${c}</label>`).join('');
    return `
    <aside class="panel zone cal__left" aria-label="Localización">
      <div class="panel__head"><div class="panel__eyebrow">Localización</div><button type="button" class="icon-btn" data-action="toggle-izq" aria-label="Colapsar el panel de localización"><span>${MF.icon.up}</span></button></div>
      <div class="zone__title"><h1>${MF.esc(z.nombre)}</h1><div>${MF.esc(z.subtitulo)}</div></div>
      <div class="stats">
        <div class="stat"><span>Departamentos</span><span>${z.departamentos}</span></div>
        <div class="stat"><span>Temporada alta</span><span>${MF.esc(z.temporadaAltaCorta)}</span></div>
        <div class="stat"><span>Testimonios</span><span>${z.testimonios}</span></div>
        <div class="stat"><span>Último registro</span><span>${MF.esc(z.ultimoRegistro)}</span></div>
      </div>
      <fieldset class="layers-box"><legend>Capas del calendario</legend>${capas}</fieldset>
      <div class="scale-box">
        <div class="panel__eyebrow">Focos por día</div>
        <div class="scale-box__bar" aria-hidden="true">
          <span style="background:var(--day-0);border:1px solid var(--line)"></span><span style="background:var(--day-1)"></span><span style="background:var(--day-2)"></span><span style="background:var(--day-3)"></span><span style="background:var(--day-4)"></span>
        </div>
        <div class="scale-box__ends"><span>Menos</span><span>Más</span></div>
        <p>Serie armonizada entre MODIS y VIIRS, para que los años se puedan comparar.</p>
      </div>
    </aside>`;
  }

  function derecha() {
    if (!state.der) {
      return `<button type="button" class="cal__reopen" data-action="toggle-der" aria-label="Abrir la bitácora zonal"><span>${MF.icon.left}</span></button>`;
    }
    return `<div class="cal__right">${MF.bitacora(state.resumen)}</div>`;
  }

  function render() {
    root.innerHTML = `
    <div class="cal">
      ${MF.header('calendario')}
      <main class="cal__main">
        ${izquierda()}
        <section class="cal__center">${temporadas()}${mes()}</section>
        ${derecha()}
      </main>
    </div>`;
  }

  root.addEventListener('click', (e) => {
    const t = e.target.closest('[data-action],[data-dia],[data-entry]');
    if (!t) { return; }
    if (t.dataset.dia) { setState({ dia: Number(t.dataset.dia), resumen: 'sep24' }); return; }
    if (t.dataset.entry) { setState({ resumen: t.dataset.entry }); return; }
    const a = t.dataset.action;
    if (a === 'toggle-izq') { setState({ izq: !state.izq }); }
    if (a === 'toggle-der') { setState({ der: !state.der }); }
    if (a === 'swap') { setState({ temporadasArriba: !state.temporadasArriba }); }
  });

  /* Reordenar tarjetas arrastrando una sobre la otra. */
  root.addEventListener('dragstart', (e) => {
    const c = e.target.closest('[data-drag]');
    if (c) { state.arrastrando = c.dataset.drag; }
  });
  root.addEventListener('dragover', (e) => { if (e.target.closest('[data-drag]')) { e.preventDefault(); } });
  root.addEventListener('drop', (e) => {
    const c = e.target.closest('[data-drag]');
    if (!c) { return; }
    e.preventDefault();
    if (state.arrastrando && state.arrastrando !== c.dataset.drag) {
      setState({ temporadasArriba: !state.temporadasArriba, arrastrando: null });
    } else {
      state.arrastrando = null;
    }
  });

  render();
})();
