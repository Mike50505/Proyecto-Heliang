(() => {
  'use strict';
  const root = document.documentElement;
  const pickerToggle = document.getElementById('color-picker-toggle');
  const panel = document.getElementById('color-picker-panel');
  const select = document.getElementById('color-mode');
  const description = document.getElementById('color-mode-description');
  const modes = {
    classic: {theme:'light', copy:'Azul MESA sobre superficies claras.'},
    pearl: {theme:'light', copy:'Grises suaves y azules discretos, con menos blanco brillante.'},
    ivory: {theme:'light', copy:'Fondos cálidos y acentos azul grisáceo, sin blanco puro.'},
    sage: {theme:'light', copy:'Verdes tenues con acentos azul petróleo y superficies suaves.'},
    slate: {theme:'dark', copy:'Azul grisáceo oscuro, con texto suave y sin fondo negro puro.'},
    night: {theme:'dark', copy:'El modo oscuro original de MESA, sobre fondo negro.'},
  };
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key,value) { try { localStorage.setItem(key,value); } catch {} },
  };
  const systemTheme = matchMedia('(prefers-color-scheme: dark)');
  let syncing = false;
  const valid = key => Object.hasOwn(modes, key);

  function applyPalette(key, persist = true) {
    if (!valid(key)) return;
    const mode = modes[key];
    root.dataset.palette = key;
    root.dataset.theme = mode.theme;
    if (persist) {
      store.set('heiliang-color-mode', key);
      store.set('mesa-theme', mode.theme);
    }
    if (description) description.textContent = mode.copy;
    if (select && select.value !== key) {
      syncing = true;
      select.value = key;
      select.dispatchEvent(new Event('change', {bubbles:true}));
      syncing = false;
    }
  }

  function readPalette() {
    const saved = store.get('heiliang-color-mode');
    if (valid(saved)) return saved;
    const previous = store.get('mesa-theme');
    return previous === 'dark' || (!previous && systemTheme.matches) ? 'night' : 'classic';
  }

  select?.addEventListener('change', () => { if (!syncing) applyPalette(select.value); });

  function placePanel() {
    if (!panel || !pickerToggle || panel.hidden) return;
    const bounds = pickerToggle.getBoundingClientRect();
    const width = panel.getBoundingClientRect().width;
    panel.style.left = `${Math.max(16, Math.min(bounds.right - width, innerWidth - width - 16))}px`;
    panel.style.right = 'auto';
    panel.style.top = `${bounds.bottom + 12}px`;
    panel.style.maxHeight = `${Math.max(120, innerHeight - bounds.bottom - 28)}px`;
  }
  function closePanel(returnFocus = false) {
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    pickerToggle.setAttribute('aria-expanded', 'false');
    if (returnFocus) pickerToggle.focus({preventScroll:true});
  }
  pickerToggle?.addEventListener('click', () => {
    if (!panel.hidden) { closePanel(); return; }
    panel.hidden = false;
    pickerToggle.setAttribute('aria-expanded', 'true');
    placePanel();
    (panel.querySelector('.glide-select__trigger') || select).focus({preventScroll:true});
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !panel || panel.hidden) return;
    // First Escape belongs to the open Glide list; second closes the panel.
    if (panel.querySelector('.glide-select__trigger[aria-expanded="true"]')) return;
    event.preventDefault();
    closePanel(true);
  }, true);
  document.addEventListener('click', event => {
    if (!panel || panel.hidden || panel.contains(event.target) || pickerToggle.contains(event.target) || event.target.closest('.glide-select__menu')) return;
    closePanel();
  });
  document.addEventListener('focusin', event => {
    if (!panel || panel.hidden || panel.contains(event.target) || pickerToggle.contains(event.target) || event.target.closest('.glide-select__menu')) return;
    closePanel();
  });
  window.addEventListener('resize', placePanel, {passive:true});
  window.visualViewport?.addEventListener('resize', placePanel, {passive:true});
  window.addEventListener('storage', event => {
    if (['heiliang-color-mode','mesa-theme',null].includes(event.key)) applyPalette(readPalette(), false);
  });
  systemTheme.addEventListener('change', () => {
    if (!store.get('heiliang-color-mode') && !store.get('mesa-theme')) applyPalette(systemTheme.matches ? 'night' : 'classic', false);
  });
  applyPalette(valid(root.dataset.palette) ? root.dataset.palette : readPalette(), false);
  if (pickerToggle) pickerToggle.title = 'Elegir colores';
})();
