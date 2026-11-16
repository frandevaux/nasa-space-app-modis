/* Mente Fría — piezas compartidas: íconos, header y bitácora. */
window.MF = window.MF || {};

MF.esc = function (s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
};

MF.icon = {
  search: '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#5F6670" stroke-width="1.6" stroke-linecap="round"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>',
  eye: '<svg aria-hidden="true" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="#17191C" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1.5 10S4.5 4 10 4s8.5 6 8.5 6-3 6-8.5 6-8.5-6-8.5-6z"/><circle cx="10" cy="10" r="2.6"/></svg>',
  user: '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#5F6670" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="5.5" r="2.8"/><path d="M2.5 14c.6-2.8 2.8-4.2 5.5-4.2s4.9 1.4 5.5 4.2"/></svg>',
  down: '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#17191C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6l5 5 5-5"/></svg>',
  downSmall: '<svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#5F6670" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6l5 5 5-5"/></svg>',
  up: '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#17191C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 10l5-5 5 5"/></svg>',
  left: '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#17191C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3L5 8l5 5"/></svg>',
  right: '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#17191C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3l5 5-5 5"/></svg>',
  swap: '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#17191C" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 2v12M2 5l3-3 3 3M11 14V2M8 11l3 3 3-3"/></svg>',
  grip: '<svg aria-hidden="true" width="12" height="18" viewBox="0 0 12 18" fill="#9AA1AA"><circle cx="3" cy="3" r="1.6"/><circle cx="9" cy="3" r="1.6"/><circle cx="3" cy="9" r="1.6"/><circle cx="9" cy="9" r="1.6"/><circle cx="3" cy="15" r="1.6"/><circle cx="9" cy="15" r="1.6"/></svg>',
  spark: '<svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="#5F6670" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 1.5l1.6 4.9 4.9 1.6-4.9 1.6L8 14.5 6.4 9.6 1.5 8l4.9-1.6z"/></svg>',
  plus: '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"><path d="M8 2v12M2 8h12"/></svg>',
  play: '<svg aria-hidden="true" width="10" height="10" viewBox="0 0 16 16" fill="#FFFFFF"><path d="M4 2.5v11l9-5.5z"/></svg>'
};

/* vista: 'mapa' | 'calendario' */
MF.header = function (vista) {
  const z = MF.ZONA;
  const anios = [2026, 2025, 2024, 2023, 2022, 2021, 2020].map((a) => `<option>${a}</option>`).join('');
  return `
  <header class="header">
    <div class="logo">Mente Fría<sup>®</sup></div>
    <div role="search" class="search ${vista === 'calendario' ? 'search--outlined' : ''}">
      <button type="button" class="search__btn" aria-label="Buscar locación. Actual: ${MF.esc(z.busqueda)}">${MF.icon.search}${MF.esc(z.busqueda)}</button>
      <span class="search__sep" aria-hidden="true"></span>
      <select aria-label="Año">${anios}</select>
    </div>
    <nav class="views" aria-label="Visualización">
      <span class="views__label">${MF.icon.eye}Visualización</span>
      <a href="index.html" ${vista === 'mapa' ? 'aria-current="page"' : ''}>Mapa</a>
      <a href="calendario.html" ${vista === 'calendario' ? 'aria-current="page"' : ''}>Calendario</a>
    </nav>
    <button type="button" class="user" aria-label="Cuenta de usuario"><span class="user__avatar">${MF.icon.user}</span>[USUARIO]${MF.icon.downSmall}</button>
  </header>`;
};

/* Bitácora. sel = id seleccionado. Los clics se escuchan con data-entry="<id>". */
MF.bitacora = function (sel, opciones) {
  const enlaceHistorico = opciones && opciones.enlaceHistorico;
  const items = MF.BITACORA.map((r) => `
    <button type="button" class="entry" data-entry="${r.id}" aria-pressed="${r.id === sel}">
      <span class="entry__meta"><span>${MF.esc(r.periodo)}</span><span>${MF.esc(r.cuantos)}</span></span>
      <span class="entry__title">${MF.esc(r.titulo)}</span>
      <span>${MF.esc(r.texto)}</span>
      ${r.leccion ? `<span class="entry__lesson">${MF.esc(r.leccion)}</span>` : ''}
      <span class="entry__ai">${MF.icon.spark}Resumen generado por IA</span>
    </button>`).join('');
  const historico = enlaceHistorico
    ? '<a class="btn btn--secondary" href="calendario.html">Ver el histórico de testimonios</a>'
    : '<button type="button" class="btn btn--secondary">Ver el histórico de testimonios</button>';
  return `
  <section class="panel log" aria-label="Bitácora zonal">
    <div class="panel__head">
      <h2>Bitácora zonal</h2>
      <button type="button" class="icon-btn" data-action="toggle-der" aria-label="Colapsar la bitácora zonal"><span>${MF.icon.up}</span></button>
    </div>
    <div class="log__list">${items}</div>
    <div class="log__actions">
      ${historico}
      <button type="button" class="btn btn--primary">Cargar un registro${MF.icon.plus}</button>
    </div>
  </section>`;
};
