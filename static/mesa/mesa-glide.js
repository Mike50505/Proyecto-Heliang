(() => {
  const instances = new Map();
  let sequence = 0;
  const selector = "select:not([multiple]):not([size]):not([data-glide-skip]):not([data-glide-managed])";
  function enhance(select) {
    if (instances.has(select)) return instances.get(select);
    const selectNumber = ++sequence;
    const abort = new AbortController();
    const on = (target, event, handler, options = {}) => target.addEventListener(event, handler, {...options, signal: abort.signal});
    const original = {tabIndex: select.getAttribute("tabindex"), ariaHidden: select.getAttribute("aria-hidden")};
    if (select.dataset.glideReady) return;
    select.dataset.glideReady = 'true';
    select.classList.add('glide-native-select');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    let options = [...select.options];
    const isDisabled = option => !option || option.disabled || option.hidden || option.parentElement?.disabled || option.parentElement?.hidden;
    const selectedIndex = () => select.selectedIndex;
    const field = select.closest('.field, .form-grid > div, .form-card p, label');
    const nativeLabel = select.labels?.[0];
    const labelElement = nativeLabel || field?.querySelector('label') || select.closest('.part-lookup')?.querySelector('label');
    const labelCopy = labelElement?.cloneNode(true);
    labelCopy?.querySelectorAll('select, input, button, small').forEach(node => node.remove());
    const label = (select.getAttribute('aria-label') || labelCopy?.textContent || 'Seleccionar opción').trim();
    const root = document.createElement('div');
    root.className = 'glide-select';
    root.dataset.size = 'md';
    root.dataset.disabled = select.disabled ? '' : 'false';
    const trigger = document.createElement('button');
    trigger.className = 'glide-select__trigger';
    trigger.id = `glide-select-trigger-${selectNumber}`;
    trigger.type = 'button';
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-label', label);
    // Preserve native label associations; forward native focus to the trigger.
    const listId = `glide-select-list-${selectNumber}`;
    trigger.setAttribute('aria-controls', listId);
    trigger.disabled = select.disabled;
    const selectedLabel = document.createElement('span');
    selectedLabel.className = 'glide-select__label';
    const chevron = document.createElement('span');
    chevron.className = 'glide-select__chevron';
    chevron.setAttribute('aria-hidden', 'true');
    chevron.textContent = '⌄';
    trigger.append(selectedLabel, chevron);

    const menu = document.createElement('div');
    menu.className = 'glide-select__menu';
    menu.classList.add('glide-select__menu--portal');
    menu.dataset.state = 'closed';
    menu.setAttribute('aria-hidden', 'true');
    menu.dataset.side = 'bottom';
    menu.dataset.align = 'left';
    const list = document.createElement('div');
    list.id = listId;
    list.className = 'glide-select__list';
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', label);
    const pill = document.createElement('span');
    pill.className = 'glide-select__pill';
    pill.setAttribute('aria-hidden', 'true');
    list.append(pill);
    let rows = [];
    const renderOptions = () => {
    options = [...select.options];
    list.replaceChildren(pill);
    rows = options.map((option, index) => {
      const row = document.createElement('div');
      row.className = 'glide-select__option';
      row.classList.toggle('glide-select__option--priority', option.classList.contains('priority-option'));
      row.id = `${listId}-option-${index}`;
      row.dataset.index = String(index);
      row.hidden = option.hidden || option.parentElement?.hidden;
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', 'false');
      row.setAttribute('aria-disabled', String(Boolean(isDisabled(option))));
      const name = document.createElement('span');
      name.className = 'glide-select__name';
      name.textContent = option.text;
      const check = document.createElement('span');
      check.className = 'glide-select__check';
      check.setAttribute('aria-hidden', 'true');
      check.textContent = '✓';
      row.append(name, check);
      list.append(row);
      return row;
    });
    };
    renderOptions();
    menu.append(list);
    const validation = document.createElement('small');
    validation.id = `glide-select-error-${selectNumber}`;
    validation.className = 'error-text';
    validation.hidden = true;
    root.append(trigger, validation);
    const descriptionIds = [...(field?.querySelectorAll('small') || [])].map((element, index) => {
      if (!element.id) element.id = `glide-select-help-${selectNumber}-${index}`;
      return element.id;
    });
    select.insertAdjacentElement('afterend', root);

    let open = false;
    let active = null;
    let closeTimer;
    let typeahead = '';
    let typeaheadTimer;
    const syncAccessibility = () => {
      trigger.setAttribute('aria-required', String(select.required));
      for (const name of ['aria-invalid', 'aria-describedby', 'aria-errormessage']) {
        if (select.hasAttribute(name)) trigger.setAttribute(name, select.getAttribute(name));
        else trigger.removeAttribute(name);
      }
      const descriptions = [select.getAttribute('aria-describedby'), ...descriptionIds, !validation.hidden ? validation.id : ''].filter(Boolean);
      if (descriptions.length) trigger.setAttribute('aria-describedby', descriptions.join(' '));
      if (!validation.hidden) trigger.setAttribute('aria-invalid', 'true');
    };
    const update = () => {
      if (select.validity.valid && !validation.hidden) validation.hidden = true;
      syncAccessibility();
      const index = selectedIndex();
      const currentText = index >= 0 ? options[index]?.text || 'Seleccionar…' : 'Seleccionar…';
      if (selectedLabel.textContent !== currentText) selectedLabel.textContent = currentText;
      selectedLabel.classList.toggle('glide-select__label--priority', index >= 0 && options[index]?.classList.contains('priority-option'));
      selectedLabel.toggleAttribute('data-empty', index < 0 || select.value === '');
      trigger.title = selectedLabel.textContent;
      rows.forEach((row, rowIndex) => {
        const isSelected = rowIndex === index;
        row.setAttribute('aria-selected', String(isSelected));
        row.querySelector('.glide-select__check').toggleAttribute('data-on', isSelected);
      });
      root.dataset.disabled = select.disabled ? '' : 'false';
      trigger.disabled = select.disabled;
      if (select.disabled) close(true);
    };
    const setActive = index => {
      active = index;
      list.toggleAttribute('data-live', index !== null);
      if (index === null) {
        trigger.removeAttribute('aria-activedescendant');
        pill.style.opacity = '0';
        return;
      }
      if (!rows[index]) return;
      trigger.setAttribute('aria-activedescendant', rows[index].id);
      pill.style.height = `${rows[index].offsetHeight}px`;
      pill.style.transform = `translateY(${rows[index].offsetTop}px)`;
      pill.style.opacity = '1';
      const row = rows[index];
      if (row.offsetTop < list.scrollTop) list.scrollTop = row.offsetTop;
      else if (row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight) {
        list.scrollTop = row.offsetTop + row.offsetHeight - list.clientHeight;
      }
    };
    const close = immediate => {
      if (!open) { if (immediate) { clearTimeout(closeTimer); menu.remove(); } return; }
      open = false;
      trigger.setAttribute('aria-expanded', 'false');
      menu.dataset.state = 'closed';
      menu.setAttribute('aria-hidden', 'true');
      setActive(null);
      clearTimeout(closeTimer);
      if (immediate) menu.remove();
      else closeTimer = window.setTimeout(() => menu.remove(), 130);
    };
    const choose = index => {
      const option = options[index];
      if (!option || isDisabled(option)) return;
      const changed = select.value !== option.value;
      select.selectedIndex = index;
      update();
      close(true);
      if (changed) {
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
      trigger.focus({ preventScroll: true });
    };
    const openMenu = viaKeyboard => {
      if (select.disabled || open || !rows.length) return;
      instances.forEach(instance => { if (instance.select !== select) instance.close(true); });
      update();
      clearTimeout(closeTimer);
      open = true;
      menu.dataset.state = 'closed';
      const fullscreenRoot = document.fullscreenElement;
      (fullscreenRoot?.contains(trigger) ? fullscreenRoot : trigger.closest('dialog[open]') || document.body).append(menu);
      trigger.setAttribute('aria-expanded', 'true');
      positionMenu();
      const index = selectedIndex();
      setActive(index >= 0 && !isDisabled(options[index]) ? index : viaKeyboard ? options.findIndex(option => !isDisabled(option)) : null);
      requestAnimationFrame(() => {
        if (!open) return;
        menu.dataset.state = 'open';
        menu.removeAttribute('aria-hidden');
      });
    };
    const positionMenu = () => {
      const rect = trigger.getBoundingClientRect();
      const width = Math.min(Math.max(240, rect.width), window.innerWidth - 32);
      menu.style.width = `${width}px`;
      menu.style.minWidth = '0';
      const below = window.innerHeight - rect.bottom - 14;
      const above = rect.top - 14;
      const side = below < Math.min(menu.scrollHeight, 300) && above > below ? 'top' : 'bottom';
      list.style.maxHeight = `${Math.max(36, Math.min(300, side === 'top' ? above : below))}px`;
      menu.dataset.side = side;
      menu.style.left = `${Math.max(16, Math.min(rect.left, window.innerWidth - width - 16))}px`;
      menu.style.top = `${side === 'top' ? Math.max(8, rect.top - menu.offsetHeight - 6) : rect.bottom + 6}px`;
      if (active !== null) setActive(active);
    };
    const onKeyDown = event => {
      const key = event.key;
      if (!open) {
        if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(key)) {
          event.preventDefault();
          openMenu(true);
        }
        return;
      }
      if (key === 'Escape' || key === 'Tab') {
        if (key === 'Escape') { event.preventDefault(); event.stopPropagation(); }
        close(true);
      } else if (key === 'ArrowDown' || key === 'ArrowUp') {
        event.preventDefault();
        move((active ?? Math.max(0, selectedIndex())) + (key === 'ArrowDown' ? 1 : -1));
      } else if (key === 'Home' || key === 'End') {
        event.preventDefault();
        move(key === 'Home' ? 0 : rows.length - 1);
      } else if (key === 'Enter' || key === ' ') {
        event.preventDefault();
        if (active !== null) choose(active);
      } else if (key.length === 1 && !event.metaKey && !event.ctrlKey && !event.altKey) {
        typeahead += key.toLocaleLowerCase();
        clearTimeout(typeaheadTimer);
        typeaheadTimer = window.setTimeout(() => { typeahead = ''; }, 600);
        const start = active ?? Math.max(0, selectedIndex());
        for (let offset = 1; offset <= options.length; offset += 1) {
          const index = (start + offset) % options.length;
          if (!isDisabled(options[index]) && options[index].text.toLocaleLowerCase().startsWith(typeahead)) {
            event.preventDefault();
            setActive(index);
            break;
          }
        }
      }
    };
    const move = index => {
      const direction = index >= (active ?? selectedIndex()) ? 1 : -1;
      let next = Math.max(0, Math.min(rows.length - 1, index));
      while (next >= 0 && next < rows.length && isDisabled(options[next])) next += direction;
      if (next >= 0 && next < rows.length) setActive(next);
    };
    on(trigger, 'click', () => open ? close(false) : openMenu(false));
    on(trigger, 'keydown', onKeyDown);
    on(list, 'pointerover', event => {
      const row = event.target.closest('.glide-select__option');
      if (row && !isDisabled(options[Number(row.dataset.index)])) setActive(Number(row.dataset.index));
    });
    on(list, 'click', event => {
      const row = event.target.closest('.glide-select__option');
      if (row) choose(Number(row.dataset.index));
    });
    on(document, 'pointerdown', event => {
      if (open && !root.contains(event.target) && !menu.contains(event.target)) close(false);
    }, {capture: true});
    on(window, 'resize', () => { if (open) positionMenu(); });
    on(document, 'fullscreenchange', () => close(true));
    on(window, 'scroll', event => {
      if (open && !menu.contains(event.target)) {
        const rect = trigger.getBoundingClientRect();
        if (rect.bottom <= 0 || rect.top >= window.innerHeight) close(true);
        else positionMenu();
      }
    }, {capture: true});
    on(select, 'invalid', event => {
      event.preventDefault();
      validation.textContent = select.validationMessage;
      validation.hidden = false;
      syncAccessibility();
      trigger.focus({ preventScroll: false });
      openMenu(true);
    });
    const observer = new MutationObserver(records => {
      if (records.some(record => record.type !== 'attributes' || record.target !== select)) {
        close(true); renderOptions();
      }
      update();
    });
    observer.observe(select, {attributes: true, childList: true, subtree: true, characterData: true});
    on(select, 'change', update);
    if (select.form) on(select.form, 'reset', () => window.setTimeout(update, 0));
    on(select, 'focus', () => trigger.focus({preventScroll: true}));
    const instance = {select, update, close, destroy() {
      close(true); clearTimeout(typeaheadTimer); abort.abort(); observer.disconnect();
      root.remove(); select.classList.remove('glide-native-select'); delete select.dataset.glideReady;
      for (const [name, value] of [['tabindex', original.tabIndex], ['aria-hidden', original.ariaHidden]]) {
        if (value === null) select.removeAttribute(name); else select.setAttribute(name, value);
      }
      instances.delete(select);
    }};
    instances.set(select, instance);
    update();
    return instance;
  }
  const scan = root => {
    if (root.matches?.(selector)) enhance(root);
    root.querySelectorAll?.(selector).forEach(enhance);
  };
  scan(document);
  new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(node => {
      if (node.nodeType === Node.ELEMENT_NODE) scan(node);
    }));
    instances.forEach(instance => { if (!instance.select.isConnected) instance.destroy(); });
    // Legacy apps set select.value while opening dialogs without firing change.
    if (records.some(record => record.target.nodeType === Node.ELEMENT_NODE && !record.target.closest('.glide-select,.glide-select__menu'))) {
      instances.forEach(instance => instance.update());
    }
  }).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['hidden','class']});
  window.MesaGlide = {enhance};
  window.dispatchEvent(new Event('mesa-glide-ready'));
})();
