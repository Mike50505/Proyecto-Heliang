const progressRows = JSON.parse(document.getElementById('progress-data').textContent);
const state = {week: null, client: null};
const numberFormat = new Intl.NumberFormat('es-MX', {maximumFractionDigits: 0});

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
}

function filtered({ignoreWeek = false, ignoreClient = false} = {}) {
  return progressRows.filter(row =>
    (ignoreWeek || !state.week || row.week === state.week) &&
    (ignoreClient || !state.client || row.client === state.client)
  );
}

function summarize(rows) {
  const programmed = rows.reduce((sum, row) => sum + row.programmed, 0);
  const completed = rows.reduce((sum, row) => sum + row.completed, 0);
  const pending = Math.max(programmed - completed, 0);
  const percent = programmed ? Math.min(completed / programmed * 100, 100) : 0;
  return {programmed, completed, pending, percent, orders: rows.length};
}

function group(rows, key) {
  const groups = new Map();
  rows.forEach(row => {
    if (!groups.has(row[key])) groups.set(row[key], []);
    groups.get(row[key]).push(row);
  });
  return [...groups.entries()].map(([name, values]) => ({name, ...summarize(values)}));
}

function weekOrder(a, b) {
  const an = Number((a.name.match(/\d+/) || [9999])[0]);
  const bn = Number((b.name.match(/\d+/) || [9999])[0]);
  return an - bn || a.name.localeCompare(b.name, 'es');
}

function renderBars(targetId, groups, filterKey) {
  const target = document.getElementById(targetId);
  if (!groups.length) {
    target.innerHTML = '<div class="empty-chart">No hay datos para esta selección.</div>';
    return;
  }
  target.innerHTML = groups.map(item => {
    const selected = state[filterKey] === item.name ? ' selected' : '';
    return `<button class="chart-bar${selected}" type="button" data-filter="${filterKey}" data-value="${escapeHtml(item.name)}" title="Filtrar por ${escapeHtml(item.name)}">
      <div class="bar-meta"><b>${escapeHtml(item.name)}</b><span>${item.percent.toFixed(1)}%</span></div>
      <div class="bar-track"><i style="width:${item.percent}%"></i></div>
      <div class="bar-values"><span>${numberFormat.format(item.completed)} terminadas</span><span>${numberFormat.format(item.programmed)} programadas</span></div>
    </button>`;
  }).join('');
}

function renderFilters() {
  const filters = [];
  if (state.week) filters.push(`<span class="filter-chip">Semana: ${escapeHtml(state.week)}</span>`);
  if (state.client) filters.push(`<span class="filter-chip">Cliente: ${escapeHtml(state.client)}</span>`);
  document.getElementById('active-filters').innerHTML = filters.join('') || 'Todos los datos';
}

function renderDetail(rows) {
  document.getElementById('detail-count').textContent = `${rows.length} registros`;
  document.getElementById('detail-body').innerHTML = rows.map(row => {
    const percent = row.programmed ? Math.min(row.completed / row.programmed * 100, 100) : 0;
    return `<tr><td>${escapeHtml(row.week)}</td><td>${escapeHtml(row.client)}</td><td>${escapeHtml(row.part)}</td><td>${numberFormat.format(row.programmed)}</td><td>${numberFormat.format(row.completed)}</td><td>${percent.toFixed(1)}%</td></tr>`;
  }).join('') || '<tr><td colspan="6">No hay órdenes para los filtros seleccionados.</td></tr>';
}

function render() {
  const rows = filtered();
  const total = summarize(rows);
  document.getElementById('kpi-programmed').textContent = numberFormat.format(total.programmed);
  document.getElementById('kpi-completed').textContent = numberFormat.format(total.completed);
  document.getElementById('kpi-pending').textContent = numberFormat.format(total.pending);
  document.getElementById('kpi-orders').textContent = numberFormat.format(total.orders);
  document.getElementById('total-percent').textContent = `${total.percent.toFixed(1)}%`;
  document.getElementById('total-donut').style.setProperty('--progress', `${total.percent * 3.6}deg`);
  document.getElementById('legend-completed').textContent = numberFormat.format(total.completed);
  document.getElementById('legend-pending').textContent = numberFormat.format(total.pending);
  document.getElementById('total-context').textContent = [state.week, state.client].filter(Boolean).join(' · ') || 'Todos los datos';

  renderBars('week-chart', group(filtered({ignoreWeek: true}), 'week').sort(weekOrder), 'week');
  renderBars('client-chart', group(filtered({ignoreClient: true}), 'client').sort((a,b) => b.programmed - a.programmed), 'client');
  renderFilters();
  renderDetail(rows);
}

document.addEventListener('click', event => {
  const bar = event.target.closest('[data-filter]');
  if (!bar) return;
  const key = bar.dataset.filter;
  state[key] = state[key] === bar.dataset.value ? null : bar.dataset.value;
  render();
});

document.getElementById('clear-filters').addEventListener('click', () => {
  state.week = null;
  state.client = null;
  render();
});

const progressScreen = document.getElementById('progress-screen');
const screenMode = document.getElementById('screen-mode');
function updateScreenMode() {
  const active = document.fullscreenElement === progressScreen;
  screenMode.innerHTML = active ? '<span>×</span> Salir de pantalla' : '<span>⛶</span> Modo pantalla';
}
screenMode.addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await progressScreen.requestFullscreen();
  } catch (error) {
    console.error('No se pudo activar el modo pantalla', error);
  }
});
document.addEventListener('fullscreenchange', updateScreenMode);

render();
