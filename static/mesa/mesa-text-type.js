/* Heiliang's login heading: one pass, 400ms delay, 48ms per character. */
(() => {
  const mounted = new WeakSet();
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  function mount(element) {
    if (mounted.has(element)) return;
    mounted.add(element);
    const phrase = element.dataset.textType.split('|')[0]?.trim();
    if (!phrase) return;
    const text = element.querySelector('.login-title-characters') || element;
    const characters = Array.from(phrase);
    let timer;
    let index = 0;
    let started = false;
    const finish = () => { clearTimeout(timer); text.textContent = phrase; };
    const tick = () => {
      if (!element.isConnected) { clearTimeout(timer); return; }
      text.textContent = characters.slice(0, ++index).join('');
      if (index < characters.length) timer = setTimeout(tick, 48);
    };
    const start = () => {
      if (started || !element.getClientRects().length || element.closest('[hidden],.hidden')) return;
      started = true;
      visibility.disconnect();
      if (motion.matches) { finish(); return; }
      text.textContent = '';
      timer = setTimeout(tick, 400);
    };
    // Tickets opens its login dialog later; type only when that dialog is visible.
    const visibility = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) start();
    });
    visibility.observe(element);
    motion.addEventListener('change', event => { if (event.matches) finish(); });
    window.addEventListener('pagehide', finish, {once: true});
    start();
  }
  const scan = root => {
    if (root.matches?.('[data-text-type]')) mount(root);
    root.querySelectorAll?.('[data-text-type]').forEach(mount);
  };
  scan(document);
  new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
    if (node.nodeType === Node.ELEMENT_NODE) scan(node);
  }))).observe(document.body, {childList: true, subtree: true});
})();
