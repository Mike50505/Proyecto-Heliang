(() => {
  const screen = document.getElementById('capacity-screen');
  if (!screen) return;
  const toggle = screen.querySelector('[data-cap-fullscreen]');
  const form = screen.querySelector('[data-cap-filter]');
  const status = screen.querySelector('[data-cap-status]');
  const chartType = screen.querySelector('[data-cap-chart-type]');
  const chartPreferenceKey = 'mesa-capacity-chart-type';
  const isFullscreen = () => document.fullscreenElement === screen;
  let pendingRequest;

  function drawWeeklyChart(canvas) {
    const context = canvas.getContext('2d');
    if (!context) return;
    const {clientWidth: width, clientHeight: height} = canvas.parentElement;
    canvas.hidden = width < 120 || height < 50;
    if (canvas.hidden) return;

    const parse = value => value == null || value === '' ? null : Number(value);
    const rows = [...canvas.nextElementSibling.children].map(({dataset}) => ({
      label: dataset.label,
      date: dataset.date,
      actual: parse(dataset.actual),
      target: parse(dataset.target),
      shiftA: parse(dataset.shiftA),
      shiftB: parse(dataset.shiftB),
      other: parse(dataset.other),
    }));
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    context.scale(scale, scale);

    const style = getComputedStyle(screen);
    const bars = chartType.value === 'bars';
    const font = Math.max(10, Math.min(24, width * .025, height * .13));
    const left = font * 3.8;
    const right = width - font * 1.6;
    const top = font * .65;
    const bottom = height - font * 1.7;
    const peak = Math.max(3, ...rows.map(row => Math.max(row.actual ?? 0, row.target ?? 0)));
    const step = 10 ** Math.floor(Math.log10(peak / 3));
    const max = 3 * step * Math.ceil(peak / (3 * step));
    const groupWidth = (right - left) / rows.length;
    const x = index => left + (bars ? groupWidth * (index + .5) : (right - left) * index / (rows.length - 1));
    const y = value => bottom - (bottom - top) * value / max;
    const format = new Intl.NumberFormat('es-MX', {notation:'compact', maximumFractionDigits:1});
    const exactFormat = new Intl.NumberFormat('es-MX', {maximumFractionDigits:3});
    const parent = canvas.parentElement;
    let tooltip = parent.querySelector('[data-cap-tooltip]');
    if (!tooltip) {
      tooltip = document.createElement('div');
      tooltip.dataset.capTooltip = '';
      tooltip.className = 'cap-chart-tooltip';
      tooltip.setAttribute('role', 'tooltip');
      tooltip.hidden = true;
      parent.append(tooltip);
    }
    const targetLabel = canvas.closest('[data-cap-series]')?.querySelector('.cap-series-target')?.textContent.trim() || 'Meta';
    canvas.capTooltipState = {rows, x, left, right, bars, targetLabel, exactFormat, tooltip, parent};
    if (!canvas.dataset.capTooltipReady) {
      canvas.dataset.capTooltipReady = 'true';
      canvas.addEventListener('pointermove', event => {
        const state = canvas.capTooltipState;
        const bounds = canvas.getBoundingClientRect();
        const pointerX = event.clientX - bounds.left;
        if (!state || pointerX < state.left || pointerX > state.right) {
          if (state) state.tooltip.hidden = true;
          return;
        }
        const index = state.rows.reduce((nearest, row, i) =>
          Math.abs(state.x(i) - pointerX) < Math.abs(state.x(nearest) - pointerX) ? i : nearest, 0);
        const row = state.rows[index];
        const amount = value => value === null ? '—' : state.exactFormat.format(value);
        const lines = [row.date, `Producido: ${amount(row.actual)}`];
        if (row.actual !== null) {
          lines.push(`Turno A: ${amount(row.shiftA)}`, `Turno B: ${amount(row.shiftB)}`);
          if (row.other > 0) lines.push(`Otros / sin turno: ${amount(row.other)}`);
        }
        lines.push(`${state.targetLabel}: ${amount(row.target)}`);
        state.tooltip.textContent = lines.join('\n');
        state.tooltip.hidden = false;
        const x = state.x(index);
        const y = event.clientY - bounds.top;
        state.tooltip.style.left = `${Math.max(4, Math.min(state.parent.clientWidth - state.tooltip.offsetWidth - 4, x + 12))}px`;
        state.tooltip.style.top = `${Math.max(4, Math.min(state.parent.clientHeight - state.tooltip.offsetHeight - 4, y + 12))}px`;
      });
      canvas.addEventListener('pointerleave', () => {
        if (canvas.capTooltipState) canvas.capTooltipState.tooltip.hidden = true;
      });
    }

    context.font = `${font}px ${style.fontFamily}`;
    context.textAlign = 'right';
    context.textBaseline = 'middle';
    context.fillStyle = style.getPropertyValue('--tv-muted').trim();
    context.strokeStyle = style.getPropertyValue('--tv-line').trim();
    for (let tick = 0; tick <= 3; tick++) {
      const value = max * tick / 3;
      context.beginPath();
      context.moveTo(left, y(value));
      context.lineTo(right, y(value));
      context.stroke();
      context.fillText(format.format(value), left - font * .35, y(value), left - font * .4);
    }

    context.textAlign = 'center';
    rows.forEach(({label}, index) => context.fillText(label, x(index), bottom + font, (right - left) / 7));

    const shiftSeries = [['shiftA', '--tv-shift-a'], ['shiftB', '--tv-shift-b'], ['other', '--tv-muted']];
    if (bars) {
      const barWidth = Math.min(groupWidth * .32, font * 2.4);
      const gap = Math.min(3, groupWidth * .08);
      rows.forEach((row, index) => {
        let produced = 0;
        for (const [key, color] of shiftSeries) {
          if (!row[key]) continue;
          context.fillStyle = style.getPropertyValue(color).trim();
          context.fillRect(x(index) - barWidth - gap / 2, y(produced + row[key]), barWidth, y(produced) - y(produced + row[key]));
          produced += row[key];
        }
        if (row.target !== null) {
          context.fillStyle = style.getPropertyValue('--tv-amber').trim();
          context.fillRect(x(index) + gap / 2, y(row.target), barWidth, bottom - y(row.target));
        }
      });
      return;
    }

    const series = [
      ['actual', '--tv-green', []], ['shiftA', '--tv-shift-a', []], ['shiftB', '--tv-shift-b', [.19, .32]],
      ['other', '--tv-muted', [.15, .48]], ['target', '--tv-amber', [.55, .36]],
    ];
    for (const [key, color, dash] of series) {
      if (key === 'other' && !rows.some(row => row.other > 0)) continue;
      const points = rows.flatMap((row, index) => row[key] === null ? [] : [[x(index), y(row[key])]]);
      if (!points.length) continue;
      context.strokeStyle = context.fillStyle = style.getPropertyValue(color).trim();
      context.beginPath();
      context.moveTo(...points[0]);
      points.slice(1).forEach(point => context.lineTo(...point));
      context.lineWidth = Math.max(1.5, font * (key === 'actual' ? .24 : .14));
      context.lineJoin = 'round';
      context.setLineDash(dash.map(length => length * font));
      context.stroke();
      if (key === 'actual' || points.length === 1) {
        points.forEach(point => {
          context.beginPath();
          context.arc(...point, Math.max(2, font * .2), 0, 2 * Math.PI);
          context.fill();
        });
      }
    }
  }

  function drawCharts() {
    screen.dataset.chartType = chartType.value;
    screen.querySelectorAll('[data-cap-line]').forEach(drawWeeklyChart);
    const pie = screen.querySelector('[data-cap-pie-plot]');
    if (!pie) return;
    const legend = [...pie.parentElement.querySelectorAll('[data-cap-pie-value]')];
    const values = legend.map(item => Number(item.dataset.capPieValue));
    const total = values.reduce((sum, value) => sum + value, 0);
    if (!total) return;
    let end = 0;
    const slices = values.map((value, index) => {
      const start = end;
      end += value / total * 100;
      const color = `hsl(${(index * 137.5 + 155) % 360} 66% 52%)`;
      legend[index].style.setProperty('--slice-color', color);
      return `${color} ${start}% ${index === values.length - 1 ? 100 : end}%`;
    });
    pie.style.background = slices.length === 1
      ? legend[0].style.getPropertyValue('--slice-color')
      : `conic-gradient(${slices.join(',')})`;
  }

  try {
    if (localStorage.getItem(chartPreferenceKey) === 'bars') chartType.value = 'bars';
  } catch {
    // Browsers can disable storage. Switching views still works for this page.
  }
  chartType.closest('label').hidden = false;
  chartType.addEventListener('change', () => {
    try {
      localStorage.setItem(chartPreferenceKey, chartType.value);
    } catch {
      // Keep the active choice in memory when storage is unavailable.
    }
    drawCharts();
  });

  new ResizeObserver(drawCharts).observe(screen.querySelector('[data-cap-grid]'));
  new MutationObserver(() => {
    requestAnimationFrame(drawCharts);
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-palette'],
  });

  if (document.fullscreenEnabled) {
    toggle.hidden = false;
    toggle.addEventListener('click', async () => {
      try {
        if (isFullscreen()) await document.exitFullscreen();
        else await screen.requestFullscreen();
      } catch {
        status.textContent = 'El navegador no pudo activar la pantalla completa.';
      }
    });
    document.addEventListener('fullscreenchange', () => {
      toggle.textContent = isFullscreen() ? 'Salir de pantalla completa' : 'Pantalla completa';
      requestAnimationFrame(drawCharts);
    });
  }

  async function update(url, filterChanged) {
    pendingRequest?.abort();
    const request = new AbortController();
    pendingRequest = request;
    const timeout = setTimeout(() => request.abort(), 10000);
    try {
      const response = await fetch(url, {cache: 'no-store', signal: request.signal});
      if (!response.ok) throw new Error();
      const updated = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (pendingRequest !== request) return;
      const selectors = [
        '[data-cap-period]', '[data-cap-freshness]', '[data-cap-kpis]', '[data-cap-capacity]',
        '[data-cap-list="machine-capacity"]', '[data-cap-list="diameter-capacity"]',
        '[data-cap-list="recent-closes"]',
        '[data-cap-customer-pie]',
        '[data-cap-list="clients"]', '[data-cap-order-table]', '[data-cap-orders-total]',
        '[data-cap-series="machine"]', '[data-cap-series="diameter"]', '[data-cap-details]',
      ];
      if (filterChanged || document.activeElement?.form !== form) {
        selectors.push('#cap-week', '#cap-client',
                       '[data-cap-chart-filter][name=chart_machine]', '[data-cap-chart-filter][name=chart_diameter]');
      }
      const fragments = selectors.map(selector => [document.querySelector(selector), updated.querySelector(selector)]);
      if (fragments.some(([current, incoming]) => !current || !incoming)) {
        status.textContent = response.redirected
          ? 'Sesión finalizada. Inicia sesión para actualizar el tablero.'
          : 'Datos sin actualizar. Se conserva la última consulta.';
        return;
      }
      for (const [current, incoming] of fragments) {
        const selectedValue = incoming.value;
        const list = current.matches('[data-cap-list]') ? current : current.querySelector('[data-cap-list]');
        const scrollTop = list?.scrollTop;
        current.replaceChildren(...incoming.childNodes);
        if (current instanceof HTMLSelectElement) current.value = selectedValue;
        const updatedList = list === current ? current : current.querySelector('[data-cap-list]');
        if (updatedList && scrollTop !== undefined) updatedList.scrollTop = scrollTop;
      }
      if (filterChanged) {
        history.replaceState(null, '', url);
      }
      drawCharts();
      status.textContent = '';
    } catch {
      if (pendingRequest === request) status.textContent = 'Datos sin actualizar. Se conserva la última consulta.';
    } finally {
      clearTimeout(timeout);
      if (pendingRequest === request) pendingRequest = undefined;
    }
  }

  function selectChartRow(row) {
    const name = row.dataset.chartMachine !== undefined ? 'chart_machine' : 'chart_diameter';
    const value = row.dataset.chartMachine ?? row.dataset.chartDiameter;
    const select = form.elements.namedItem(name);
    if (select && select.value !== value) {
      select.value = value;
      form.requestSubmit();
    }
  }

  screen.addEventListener('click', event => {
    const row = event.target.closest('[data-chart-machine], [data-chart-diameter]');
    if (row) selectChartRow(row);
  });

  screen.addEventListener('keydown', event => {
    const row = event.target.closest('[data-chart-machine], [data-chart-diameter]');
    if (row && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault();
      selectChartRow(row);
    }
  });

  screen.addEventListener('change', event => {
    if (event.target.matches('[data-cap-chart-filter]')) form.requestSubmit();
  });

  form.addEventListener('submit', event => {
    if (!isFullscreen()) return;
    event.preventDefault();
    const url = new URL(location.href);
    url.search = new URLSearchParams(new FormData(form));
    update(url, true);
  });

  setInterval(() => {
    if (isFullscreen() && !pendingRequest) update(location.href, false);
  }, 45000);
})();
