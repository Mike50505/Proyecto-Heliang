(() => {
  const screen = document.getElementById('capacity-screen');
  if (!screen) return;
  const toggle = screen.querySelector('[data-cap-fullscreen]');
  const form = screen.querySelector('[data-cap-filter]');
  const status = screen.querySelector('[data-cap-status]');
  const chartType = screen.querySelector('[data-cap-chart-type]');
  const chartPreferenceKey = 'mesa-capacity-chart-type';
  const isFullscreen = () => document.fullscreenElement === screen;
  let pages = [];
  let pendingRequest;

  function drawWeeklyChart(canvas) {
    const context = canvas.getContext('2d');
    if (!context) return;
    const {clientWidth: width, clientHeight: height} = canvas.parentElement;
    canvas.hidden = width < 120 || height < 50;
    if (canvas.hidden) return;

    const parse = value => value === '' ? null : Number(value);
    const rows = [...canvas.nextElementSibling.children].map(({dataset}) => ({
      label: dataset.label,
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
    requestAnimationFrame(() => {
      fitRows();
      drawCharts();
    });
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-palette'],
  });

  function showPage(page, index) {
    page.index = index % page.count;
    page.rows.forEach((row, i) => {
      row.hidden = Math.floor(i / page.size) !== page.index;
    });
    page.button.hidden = page.count <= 1;
    page.button.textContent = `Página ${page.index + 1} de ${page.count} · Siguiente`;
  }

  function fitRows() {
    pages = [...screen.querySelectorAll('[data-cap-pager]')].map((card, index) => {
      const list = card.querySelector('[data-cap-list]');
      if (!list) return null;
      const rows = [...list.querySelectorAll('[data-cap-row]')];
      const button = card.querySelector('[data-cap-next]');
      rows.forEach(row => { row.hidden = false; });
      button.hidden = true;
      if (!isFullscreen() || !rows.length) return null;
      const height = rows[0].getBoundingClientRect().height;
      let size = Math.max(1, Math.floor((list.clientHeight + 1) / height));
      if (size < rows.length) {
        button.hidden = false;
        size = Math.max(1, Math.floor((list.clientHeight + 1) / height));
      }
      const page = { rows, button, size, count: Math.ceil(rows.length / size) };
      showPage(page, pages[index]?.index || 0);
      return page;
    });
  }

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
      requestAnimationFrame(fitRows);
    });
    window.addEventListener('resize', fitRows);
  }

  screen.addEventListener('click', event => {
    const page = pages.find(item => item?.button === event.target);
    if (page) showPage(page, page.index + 1);
  });

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
        '[data-cap-list="clients"]', '[data-cap-list="orders"]', '[data-cap-orders-total]',
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
        current.replaceChildren(...incoming.childNodes);
        if (current instanceof HTMLSelectElement) current.value = selectedValue;
      }
      if (filterChanged) {
        history.replaceState(null, '', url);
        pages = [];
      }
      fitRows();
      drawCharts();
      status.textContent = '';
    } catch {
      if (pendingRequest === request) status.textContent = 'Datos sin actualizar. Se conserva la última consulta.';
    } finally {
      clearTimeout(timeout);
      if (pendingRequest === request) pendingRequest = undefined;
    }
  }

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
    if (!isFullscreen()) return;
    for (const page of pages) {
      if (page?.count > 1 && page.button !== document.activeElement) showPage(page, page.index + 1);
    }
  }, 20000);

  setInterval(() => {
    if (isFullscreen() && !pendingRequest) update(location.href, false);
  }, 45000);
})();
