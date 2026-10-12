/* Equal side columns keep navigation at the page's center, even as accounts change. */
(() => {
  const mounted = new WeakSet();
  const scan = () => document.querySelectorAll('.mesa-header,.site-header').forEach(header => {
    if (mounted.has(header)) return;
    mounted.add(header);
    const layout = header.querySelector('.mesa-header-inner,.site-header-inner') || header;
    const brand = layout.querySelector('.mesa-brand,.brand');
    const account = layout.querySelector('.mesa-account,.header-actions');
    if (!brand || !account) return;
    const measure = () => {
      if (window.innerWidth <= 800 || !header.getClientRects().length) return;
      const side = Math.ceil(Math.max(brand.getBoundingClientRect().width,account.getBoundingClientRect().width));
      if (layout.style.getPropertyValue('--mesa-header-side') !== side + 'px') layout.style.setProperty('--mesa-header-side', side + 'px');
    };
    const observer = new ResizeObserver(measure);
    observer.observe(brand); observer.observe(account);
    measure();
    const removal = new MutationObserver(() => {
      if (!header.isConnected) { observer.disconnect(); removal.disconnect(); }
    });
    removal.observe(document.body, {childList: true,subtree: true});
  });
  scan();
  new MutationObserver(scan).observe(document.body,{childList: true,subtree: true});
})();
