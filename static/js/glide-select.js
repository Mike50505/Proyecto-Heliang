(() => {
  const nativeSelects = [...document.querySelectorAll('main select:not([multiple]):not([size]):not([data-glide-skip])')];
  const selectStyles = document.createElement('style');
  selectStyles.textContent = '.glide-native-select{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}';
  document.head.append(selectStyles);

  nativeSelects.forEach((select, selectNumber) => {
    if (select.dataset.glideReady) return;
    select.dataset.glideReady = 'true';
    select.classList.add('glide-native-select');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    const options = [...select.options];
    const isDisabled = option => option.disabled || option.parentElement?.disabled;
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
    if (nativeLabel) nativeLabel.htmlFor = trigger.id;
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
    const rows = options.map((option, index) => {
      const row = document.createElement('div');
      row.className = 'glide-select__option';
      row.classList.toggle('glide-select__option--priority', option.classList.contains('priority-option'));
      row.id = `${listId}-option-${index}`;
      row.dataset.index = String(index);
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
      if (select.validity.valid) validation.hidden = true;
      syncAccessibility();
      const index = selectedIndex();
      selectedLabel.textContent = index >= 0 ? options[index].text : 'Seleccionar…';
      selectedLabel.classList.toggle('glide-select__label--priority', index >= 0 && options[index].classList.contains('priority-option'));
      selectedLabel.toggleAttribute('data-empty', index < 0 || select.value === '');
      trigger.title = selectedLabel.textContent;
      rows.forEach((row, rowIndex) => {
        const isSelected = rowIndex === index;
        row.setAttribute('aria-selected', String(isSelected));
        row.querySelector('.glide-select__check').toggleAttribute('data-on', isSelected);
      });
      root.dataset.disabled = select.disabled ? '' : 'false';
      trigger.disabled = select.disabled;
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
      if (!open) return;
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
      clearTimeout(closeTimer);
      open = true;
      menu.dataset.state = 'closed';
      const fullscreenRoot = document.fullscreenElement;
      (fullscreenRoot?.contains(trigger) ? fullscreenRoot : document.body).append(menu);
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
        if (key === 'Escape') event.preventDefault();
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
    trigger.addEventListener('click', () => open ? close(false) : openMenu(false));
    trigger.addEventListener('keydown', onKeyDown);
    list.addEventListener('pointerover', event => {
      const row = event.target.closest('.glide-select__option');
      if (row && !isDisabled(options[Number(row.dataset.index)])) setActive(Number(row.dataset.index));
    });
    list.addEventListener('click', event => {
      const row = event.target.closest('.glide-select__option');
      if (row) choose(Number(row.dataset.index));
    });
    document.addEventListener('pointerdown', event => {
      if (open && !root.contains(event.target) && !menu.contains(event.target)) close(false);
    }, true);
    window.addEventListener('resize', () => { if (open) positionMenu(); });
    document.addEventListener('fullscreenchange', () => close(true));
    window.addEventListener('scroll', event => {
      if (open && !menu.contains(event.target)) {
        const rect = trigger.getBoundingClientRect();
        if (rect.bottom <= 0 || rect.top >= window.innerHeight) close(true);
        else positionMenu();
      }
    }, true);
    select.addEventListener('invalid', event => {
      event.preventDefault();
      validation.textContent = select.validationMessage;
      validation.hidden = false;
      syncAccessibility();
      trigger.focus({ preventScroll: false });
      openMenu(true);
    });
    new MutationObserver(update).observe(select, { attributes: true, attributeFilter: ['disabled', 'required', 'aria-invalid', 'aria-describedby', 'aria-errormessage'] });
    select.addEventListener('change', update);
    select.form?.addEventListener('reset', () => window.setTimeout(update, 0));
    update();
  });
})();
