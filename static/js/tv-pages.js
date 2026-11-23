(() => {
  const panels = new Map();

  function renderPage(panel, index) {
    panel.index = (index + panel.count) % panel.count;
    const start = panel.index * panel.size;
    panel.items.forEach((item, position) => {
      item.hidden = position < start || position >= start + panel.size;
    });
    panel.controls.classList.toggle('tv-pages-single', panel.count < 2);
    panel.controls.querySelector('output').textContent = `${panel.index + 1} / ${panel.count}`;
  }

  function fitPages(reset = false) {
    const root = document.fullscreenElement;
    document.querySelectorAll('[data-tv-pages]').forEach(container => {
      const key = container.dataset.tvPages;
      const viewport = container.querySelector('[data-tv-viewport]');
      const controls = container.querySelector('.tv-pages-controls');
      const items = Array.from(viewport.querySelectorAll(container.dataset.tvItems));
      items.forEach(item => { item.hidden = false; });
      if (!root?.contains(container) || !items.length || !viewport.clientHeight) {
        controls.classList.add('tv-pages-single');
        panels.delete(key);
        return;
      }

      // Measure in the same grid used by the visible page. Cards keep a stable
      // size even when only the last page is visible.
      const bounds = viewport.getBoundingClientRect();
      const overflowAt = items.findIndex(item => {
        const rect = item.getBoundingClientRect();
        return rect.bottom > bounds.bottom + 1 || rect.right > bounds.right + 1;
      });
      const size = overflowAt < 0 ? items.length : Math.max(1, overflowAt);
      const previous = reset ? 0 : panels.get(key)?.index || 0;
      const panel = {items, controls, size, count: Math.ceil(items.length / size)};
      panels.set(key, panel);
      renderPage(panel, Math.min(previous, panel.count - 1));
    });
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('[data-tv-step]');
    if (!button) return;
    const panel = panels.get(button.closest('[data-tv-pages]').dataset.tvPages);
    if (panel) renderPage(panel, panel.index + Number(button.dataset.tvStep));
  });
  document.addEventListener('fullscreenchange', () => fitPages());
  document.addEventListener('tv:render', event => fitPages(event.detail?.reset));
  window.addEventListener('resize', () => fitPages());
  setInterval(() => {
    if (!document.fullscreenElement || document.hidden) return;
    for (const panel of panels.values()) {
      if (panel.count > 1 && !panel.controls.contains(document.activeElement)) renderPage(panel, panel.index + 1);
    }
  }, 20000);
})();
