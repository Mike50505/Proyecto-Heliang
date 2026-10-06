(() => {
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.getElementById('site-nav');
  if (!toggle || !nav) return;

  const close = () => {
    toggle.setAttribute('aria-expanded', 'false');
    toggle.setAttribute('aria-label', 'Abrir menú');
    nav.classList.remove('is-open');
  };
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
    nav.classList.toggle('is-open', open);
  });
  nav.addEventListener('click', event => {
    if (event.target.closest('a')) close();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') close();
  });
  document.addEventListener('click', event => {
    if (!nav.contains(event.target) && !toggle.contains(event.target)) close();
  });

  const current = location.pathname.replace(/\/$/, '');
  for (const link of nav.querySelectorAll('a')) {
    if (new URL(link.href).pathname.replace(/\/$/, '') === current) {
      link.setAttribute('aria-current', 'page');
    }
  }
})();
