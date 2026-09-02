let progressRows = JSON.parse(document.getElementById('progress-data').textContent);
const state = {week: null, client: null};
let chartStyle = localStorage.getItem('mesa-progress-chart-style') || 'horizontal';
const numberFormat = new Intl.NumberFormat('es-MX', {maximumFractionDigits: 3});

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
  const legend = target.closest('.chart-card').querySelector('[data-chart-legend]');
  target.classList.remove('style-horizontal', 'style-classic', 'style-donut');
  target.classList.add(`style-${chartStyle}`);
  if (chartStyle === 'classic') {
    legend.innerHTML = '<span><i class="programmed"></i>Programado</span><span><i class="completed"></i>Terminado</span><small>Altura = cantidad de piezas</small>';
  } else {
    legend.innerHTML = '<span><i class="completed"></i>Terminado</span><span><i class="pending"></i>Pendiente</span><small>Color = porcentaje de avance</small>';
  }
  if (!groups.length) {
    target.innerHTML = '<div class="empty-chart">No hay datos para esta selección.</div>';
    return;
  }
  const maxProgrammed = Math.max(...groups.map(item => item.programmed), 1);
  target.innerHTML = groups.map(item => {
    const selected = state[filterKey] === item.name ? ' selected' : '';
    if (chartStyle === 'classic') {
      const programmedHeight = item.programmed / maxProgrammed * 100;
      const completedHeight = Math.min(item.completed / maxProgrammed * 100, 100);
      return `<button class="classic-bar${selected}" type="button" data-filter="${filterKey}" data-value="${escapeHtml(item.name)}" title="${escapeHtml(item.name)}: ${item.percent.toFixed(1)}% completado">
        <div class="classic-plot"><i style="height:${programmedHeight}%" title="${numberFormat.format(item.programmed)} programadas"></i><i class="completed" style="height:${completedHeight}%" title="${numberFormat.format(item.completed)} terminadas"></i></div>
        <div class="classic-values"><span>P: ${numberFormat.format(item.programmed)}</span><span>T: ${numberFormat.format(item.completed)}</span></div>
        <b>${escapeHtml(item.name)}</b><small>${item.percent.toFixed(1)}% completado</small>
      </button>`;
    }
    if (chartStyle === 'donut') {
      return `<button class="mini-donut-card${selected}" type="button" data-filter="${filterKey}" data-value="${escapeHtml(item.name)}" title="Filtrar por ${escapeHtml(item.name)}">
        <span class="mini-donut" style="--progress:${item.percent * 3.6}deg"><b>${item.percent.toFixed(1)}%</b></span>
        <b>${escapeHtml(item.name)}</b><small>${numberFormat.format(item.completed)} / ${numberFormat.format(item.programmed)}</small>
      </button>`;
    }
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

const chartStyleSelect = document.getElementById('chart-style');
if (![...chartStyleSelect.options].some(option => option.value === chartStyle)) chartStyle = 'horizontal';
chartStyleSelect.value = chartStyle;
chartStyleSelect.addEventListener('change', () => {
  chartStyle = chartStyleSelect.value;
  localStorage.setItem('mesa-progress-chart-style', chartStyle);
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

const refreshStatus = document.getElementById('progress-refresh-status');
let refreshing = false;

async function refreshProgress() {
  if (refreshing || document.hidden) return;
  refreshing = true;
  try {
    const response = await fetch(window.progressDataUrl, {
      headers: {'X-Requested-With': 'XMLHttpRequest'},
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    progressRows = data.progress_data;
    render();
    refreshStatus.textContent = 'Actualizado · próxima consulta en 30 segundos';
  } catch (error) {
    refreshStatus.textContent = 'Sin conexión · reintentando';
    console.error('No se pudo actualizar el avance de producción', error);
  } finally {
    refreshing = false;
  }
}

setInterval(refreshProgress, 30000);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshProgress();
});
