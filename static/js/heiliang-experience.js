(() => {
  'use strict';
  const root = document.documentElement;
  document.addEventListener('keydown', () => { root.dataset.inputMode = 'keyboard'; }, true);
  document.addEventListener('pointerdown', () => { root.dataset.inputMode = 'pointer'; }, true);
  document.addEventListener('pointermove', event => {
    if (event.pointerType === 'mouse') root.dataset.inputMode = 'pointer';
  }, { passive: true });

  const normalize = value => value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('es');
  document.querySelectorAll('[data-table-search]').forEach(toolbar => {
    const table = toolbar.closest('.board-column')?.querySelector('table');
    if (!table) return;
    const body = table.tBodies[0];
    const rows = [...body.rows].filter(row => !row.querySelector('[colspan]'));
    if (!rows.length) return;
    const entries = rows.map(row => ({ row, text: normalize(row.textContent) }));
    const empty = document.createElement('tr');
    empty.className = 'table-empty-search';
    const cell = empty.insertCell();
    cell.colSpan = table.tHead.rows[0].cells.length;
    cell.textContent = 'No hay coincidencias en los registros mostrados. Prueba otra búsqueda.';
    empty.hidden = true;
    body.append(empty);
    const input = toolbar.querySelector('input');
    const output = toolbar.querySelector('output');
    const apply = () => {
      const words = normalize(input.value.trim()).split(/\s+/).filter(Boolean);
      let count = 0;
      entries.forEach(({row, text}) => {
        row.hidden = !words.every(word => text.includes(word));
        if (!row.hidden) count++;
      });
      empty.hidden = count > 0;
      output.textContent = `${count} de ${rows.length}`;
      table.closest('.table-wrap').scrollTop = 0;
    };
    input.addEventListener('input', apply);
    toolbar.hidden = false;
    apply();
  });

  const diameter = document.getElementById('priority-diameter');
  if (diameter && diameter.options.length > 1) {
    const table = document.querySelector('.diameter-priority-table');
    const rows = [...table.tBodies[0].rows];
    const groups = [];
    let key = '';
    rows.forEach(row => {
      const heading = row.querySelector('.diameter-section-title');
      if (heading) key = heading.textContent.replace(/^Diámetro\s+/, '').trim();
      groups.push({row, key, heading: Boolean(heading)});
    });
    const apply = () => {
      let count = 0;
      groups.forEach(({row, key, heading}) => {
        row.hidden = Boolean(diameter.value && key !== diameter.value);
        if (!row.hidden && !heading) count++;
      });
      document.getElementById('diameter-result-count').textContent = `${count} ${count === 1 ? 'orden' : 'órdenes'}`;
      table.closest('.table-wrap').scrollTop = 0;
    };
    diameter.addEventListener('change', apply);
    diameter.closest('.diameter-toolbar').hidden = false;
    apply();
  }

  const order = document.getElementById('id_start-order');
  const context = document.getElementById('order-selection-context');
  const balancesNode = document.getElementById('order-balances');
  if (order && context && balancesNode) {
    const balances = JSON.parse(balancesNode.textContent);
    const update = () => {
      const balance = balances[order.value];
      context.hidden = balance === undefined;
      context.textContent = balance === undefined ? '' : `Saldo disponible: ${Number(balance).toLocaleString('es-MX')} piezas. Puedes asignar una cantidad menor.`;
    };
    order.addEventListener('change', update);
    update();
  }

  const password = document.querySelector('.login-card input[type="password"]');
  if (password) {
    const wrapper = document.createElement('div');
    wrapper.className = 'password-field';
    password.before(wrapper);
    wrapper.append(password);
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'password-toggle';
    toggle.textContent = 'Mostrar';
    toggle.setAttribute('aria-label', 'Mostrar contraseña');
    toggle.setAttribute('aria-controls', password.id);
    toggle.setAttribute('aria-pressed', 'false');
    toggle.addEventListener('click', () => {
      const visible = password.type === 'password';
      password.type = visible ? 'text' : 'password';
      toggle.textContent = visible ? 'Ocultar' : 'Mostrar';
      toggle.setAttribute('aria-label', visible ? 'Ocultar contraseña' : 'Mostrar contraseña');
      toggle.setAttribute('aria-pressed', String(visible));
    });
    wrapper.append(toggle);
  }

  const scrollers = [...document.querySelectorAll('.table-wrap, .preview-table-wrap')];
  const updateScrollAccess = () => scrollers.forEach(wrapper => {
    const needsScroll = wrapper.scrollWidth > wrapper.clientWidth + 1 || wrapper.scrollHeight > wrapper.clientHeight + 1;
    if (needsScroll) {
      wrapper.tabIndex = 0;
      wrapper.setAttribute('role', 'region');
      const heading = wrapper.closest('section, .board-column, .panel')?.querySelector('h2');
      wrapper.setAttribute('aria-label', (heading?.textContent || 'Registros') + ' · tabla desplazable');
    } else {
      wrapper.removeAttribute('tabindex');
      wrapper.removeAttribute('role');
      wrapper.removeAttribute('aria-label');
    }
  });
  if (window.ResizeObserver) {
    const observer = new ResizeObserver(updateScrollAccess);
    scrollers.forEach(wrapper => observer.observe(wrapper));
  }
  updateScrollAccess();

  const nav = document.getElementById('site-nav');
  const active = nav?.querySelector('[aria-current="page"]');
  if (nav && active && innerWidth > 800) {
    // Scroll only the nav; avoid scrolling the page or animating a daily action.
    nav.scrollLeft = Math.max(0, active.offsetLeft - nav.offsetLeft - (nav.clientWidth - active.clientWidth) / 2);
  }
})();
