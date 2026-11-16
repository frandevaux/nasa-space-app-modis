/* Icons from the design prototype (webtool-idea/js/common.js). */
const base = { 'aria-hidden': true, fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' } as const;

export const Icon = {
  search: () => (<svg {...base} width="16" height="16" viewBox="0 0 16 16" stroke="#5F6670" strokeWidth="1.6"><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" /></svg>),
  eye: () => (<svg {...base} width="20" height="20" viewBox="0 0 20 20" stroke="#17191C" strokeWidth="1.5"><path d="M1.5 10S4.5 4 10 4s8.5 6 8.5 6-3 6-8.5 6-8.5-6-8.5-6z" /><circle cx="10" cy="10" r="2.6" /></svg>),
  user: () => (<svg {...base} width="18" height="18" viewBox="0 0 16 16" stroke="#5F6670" strokeWidth="1.5"><circle cx="8" cy="5.5" r="2.8" /><path d="M2.5 14c.6-2.8 2.8-4.2 5.5-4.2s4.9 1.4 5.5 4.2" /></svg>),
  down: () => (<svg {...base} width="16" height="16" viewBox="0 0 16 16" stroke="#17191C" strokeWidth="1.8"><path d="M3 6l5 5 5-5" /></svg>),
  downSmall: () => (<svg {...base} width="12" height="12" viewBox="0 0 16 16" stroke="#5F6670" strokeWidth="1.8"><path d="M3 6l5 5 5-5" /></svg>),
  up: () => (<svg {...base} width="16" height="16" viewBox="0 0 16 16" stroke="#17191C" strokeWidth="1.8"><path d="M3 10l5-5 5 5" /></svg>),
  left: () => (<svg {...base} width="16" height="16" viewBox="0 0 16 16" stroke="#17191C" strokeWidth="1.8"><path d="M10 3L5 8l5 5" /></svg>),
  right: () => (<svg {...base} width="16" height="16" viewBox="0 0 16 16" stroke="#17191C" strokeWidth="1.8"><path d="M6 3l5 5-5 5" /></svg>),
  swap: () => (<svg {...base} width="14" height="14" viewBox="0 0 16 16" stroke="#17191C" strokeWidth="1.8"><path d="M5 2v12M2 5l3-3 3 3M11 14V2M8 11l3 3 3-3" /></svg>),
  grip: () => (<svg aria-hidden width="12" height="18" viewBox="0 0 12 18" fill="#9AA1AA"><circle cx="3" cy="3" r="1.6" /><circle cx="9" cy="3" r="1.6" /><circle cx="3" cy="9" r="1.6" /><circle cx="9" cy="9" r="1.6" /><circle cx="3" cy="15" r="1.6" /><circle cx="9" cy="15" r="1.6" /></svg>),
  plus: () => (<svg {...base} width="18" height="18" viewBox="0 0 16 16" stroke="#FFFFFF" strokeWidth="1.6"><path d="M8 2v12M2 8h12" /></svg>),
  play: () => (<svg aria-hidden width="10" height="10" viewBox="0 0 16 16" fill="#FFFFFF"><path d="M4 2.5v11l9-5.5z" /></svg>),
  pin: () => (<svg {...base} width="18" height="18" viewBox="0 0 20 20" stroke="currentColor" strokeWidth="1.6"><path d="M10 18s-5.5-5.2-5.5-9.5a5.5 5.5 0 0 1 11 0C15.5 12.8 10 18 10 18z" /><circle cx="10" cy="8.5" r="2" /></svg>),
  log: () => (<svg {...base} width="18" height="18" viewBox="0 0 20 20" stroke="currentColor" strokeWidth="1.6"><path d="M5 2.5h9.5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1H5a1.5 1.5 0 0 1-1.5-1.5v-12A1.5 1.5 0 0 1 5 2.5z" /><path d="M7 6.5h6M7 9.5h6M7 12.5h3.5" /></svg>),
  filter: () => (<svg {...base} width="18" height="18" viewBox="0 0 20 20" stroke="currentColor" strokeWidth="1.6"><path d="M3 4.5h14M5.5 10h9M8 15.5h4" /></svg>),
  calendar: () => (<svg {...base} width="18" height="18" viewBox="0 0 20 20" stroke="currentColor" strokeWidth="1.6"><rect x="3" y="4" width="14" height="13" rx="1.5" /><path d="M3 8h14M7 2.5v3M13 2.5v3" /></svg>),
  close: () => (<svg {...base} width="14" height="14" viewBox="0 0 16 16" stroke="currentColor" strokeWidth="1.8"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" /></svg>),
  pause: () => (<svg aria-hidden width="10" height="10" viewBox="0 0 16 16" fill="#FFFFFF"><path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" /></svg>),
};
