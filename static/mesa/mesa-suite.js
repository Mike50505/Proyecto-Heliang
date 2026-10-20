/* Interaction utilities for non-React applications. Never changes form values. */
(() => {
  const key = 'mesa-theme';
  const preference = matchMedia('(prefers-color-scheme: dark)');
  const apply = theme => {
    const palette = document.documentElement.dataset.palette;
    const themes = {classic:'light',pearl:'light',ivory:'light',sage:'light',slate:'dark',night:'dark'};
    if (Object.hasOwn(themes, palette)) theme = themes[palette];
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll('[data-mesa-theme]').forEach(button => {
      const dark = theme === 'dark';
      button.textContent = dark ? '☀ Modo claro' : '☾ Modo oscuro';
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? 'Activar modo claro' : 'Activar modo oscuro');
    });
  };
  let stored;
  try { stored = localStorage.getItem(key); } catch {}
  apply(stored === 'dark' || stored === 'light' ? stored : document.documentElement.dataset.theme || (preference.matches ? 'dark' : 'light'));
  document.querySelectorAll('[data-mesa-theme]').forEach(button => button.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(key, next); } catch {}
    apply(next);
  }));
  window.addEventListener('storage', event => {
    if (event.key === key) apply(event.newValue === 'dark' ? 'dark' : 'light');
  });
  document.querySelectorAll('[data-mesa-menu]').forEach(button => {
    const nav = document.getElementById(button.getAttribute('aria-controls'));
    if (!nav) return;
    const setOpen = open => { nav.classList.toggle('is-open', open); button.setAttribute('aria-expanded', String(open)); button.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú'); };
    button.addEventListener('click', () => setOpen(!nav.classList.contains('is-open')));
    nav.addEventListener('click', event => { if (event.target.closest('a,button')) setOpen(false); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && nav.classList.contains('is-open')) { setOpen(false); button.focus(); } });
  });
  document.querySelectorAll('.mesa-nav').forEach(nav => {
    const links = [...nav.querySelectorAll('a[href]')].filter(link => !link.hasAttribute('data-view') && !link.hasAttribute('data-panel') && !link.hasAttribute('data-action'));
    const normalized = value => value.replace(/\/+$/, '') || '/';
    const current = normalized(location.pathname);
    const entries = links.map(link => ({ link, url: new URL(link.href, location.href) })).filter(entry => entry.url.origin === location.origin);
    const match = entries.filter(entry => {
      const target = normalized(entry.url.pathname);
      return current === target || (target !== '/' && current.startsWith(target + '/'));
    }).sort((a,b) => b.url.pathname.length - a.url.pathname.length)[0];
    const fallback = !current.includes('/login') && entries.find(entry => normalized(entry.url.pathname) === '/');
    (match || fallback)?.link.setAttribute('aria-current', 'page');
  });
  /* These two apps retain their existing navigation event handlers. */
  const legacyMenu = document.getElementById('menu') || document.getElementById('menuButton');
  const legacyHeader = document.querySelector('#sidebar.mesa-header');
  if (legacyMenu && legacyHeader) {
    const sync = () => {
      const open = legacyHeader.classList.contains('open');
      legacyMenu.setAttribute('aria-expanded', String(open));
      legacyMenu.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
    };
    new MutationObserver(sync).observe(legacyHeader, { attributes: true, attributeFilter: ['class'] });
    legacyHeader.querySelector('.mesa-nav')?.addEventListener('click', event => {
      if (event.target.closest('a,button')) legacyHeader.classList.remove('open');
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && legacyHeader.classList.contains('open')) { legacyHeader.classList.remove('open'); legacyMenu.focus(); }
    });
    sync();
  }
})();
