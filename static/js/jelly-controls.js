/* Capsule navigation and press feedback adapted from Universo Ramos. */
(() => {
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const controls = '.button, button:not(.glide-select__trigger):not(.theme-toggle):not(.nav-toggle), .assign-order-button';
  const release = () => document.querySelectorAll('.jelly-pressed').forEach(control => control.classList.remove('jelly-pressed'));
  document.addEventListener('pointerdown', event => {
    const control = event.target.closest(controls);
    if (!motion.matches && control && !control.disabled && control.getAttribute('aria-disabled') !== 'true') control.classList.add('jelly-pressed');
  });
  ['pointerup', 'pointercancel', 'dragstart'].forEach(type => document.addEventListener(type, release));
  document.addEventListener('pointerout', event => {
    const control = event.target.closest(controls);
    if (control && !control.contains(event.relatedTarget)) control.classList.remove('jelly-pressed');
  });
  window.addEventListener('blur', release);
  window.addEventListener('pagehide', release);
  const nav = document.getElementById('site-nav');
  if (!nav) return;
  const key = 'mesa-jelly-nav-pop';
  const normalize = value => value.replace(/\/+$/, '') || '/';
  const links = [...nav.querySelectorAll('a[href]')];
  const linkPath = link => normalize(new URL(link.href, location.href).pathname);
  const path = normalize(location.pathname);
  const current = links.find(link => linkPath(link) === path) || links
    .filter(link => linkPath(link) !== '/' && path.startsWith(`${linkPath(link)}/`))
    .sort((a, b) => linkPath(b).length - linkPath(a).length)[0];
  current?.setAttribute('aria-current', 'page');
  try {
    const target = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
    if (current && target === linkPath(current) && !motion.matches) {
      current.classList.add('jelly-nav-pop');
      current.addEventListener('animationend', () => current.classList.remove('jelly-nav-pop'), { once: true });
    }
  } catch {}
  nav.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || link === current || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    try { sessionStorage.setItem(key, linkPath(link)); } catch {}
  });
})();
