(() => {
  'use strict';
  const csrf = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  const path = location.pathname;
  if (path.includes('universo-ramos-arizpe')) {
    const table = document.querySelector('.table-wrap table');
    if (table) {
      const headers = [...table.tHead.rows[0].cells];
      headers.forEach((h, i) => { h.tabIndex = 0; h.title = 'Ordenar'; h.addEventListener('click', () => {
        const rows = [...table.tBodies[0].rows].filter(r => r.cells.length > 1); const dir = h.dataset.dir === 'asc' ? -1 : 1; h.dataset.dir = dir === 1 ? 'asc' : 'desc';
        rows.sort((a,b) => (a.cells[i]?.textContent.trim()||'').localeCompare(b.cells[i]?.textContent.trim()||'', 'es', {numeric:true}) * dir).forEach(r => table.tBodies[0].appendChild(r));
      }); h.addEventListener('keydown', e => { if (e.key === 'Enter') h.click(); }); });
    }
  }
  if (path.includes('heliang')) {
    const board = document.querySelector('.priority-panel table tbody');
    if (!board) return;
    const rows = [...board.querySelectorAll('tr.priority-row')];
    rows.forEach(row => { row.draggable = true; row.addEventListener('dragstart', () => row.classList.add('dragging')); row.addEventListener('dragend', async () => {
      row.classList.remove('dragging'); [...board.querySelectorAll('tr.priority-row')].forEach((r, i) => { const input = r.querySelector('.priority-input'); if (input) input.value = i + 1; });
    }); row.addEventListener('dragover', e => { e.preventDefault(); const dragging = board.querySelector('.dragging'); if (dragging && dragging !== row) board.insertBefore(dragging, row); }); });
    const notice = document.createElement('div'); notice.className = 'priority-feedback'; notice.textContent = 'Arrastra una orden para ajustar su prioridad'; board.parentElement.parentElement.prepend(notice);
  }
})();
