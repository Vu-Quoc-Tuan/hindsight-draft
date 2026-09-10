/**
 * Table Component: Renders virtualized or paginated rows with badges and click handlers.
 */

export function renderTable(container, { columns, rows, onRowClick, emptyText = 'No data available' }) {
  if (!rows || rows.length === 0) {
    container.innerHTML = `
      <div style="padding: 3rem; text-align: center; color: var(--text-dim);">
        <p style="font-size: 0.95rem;">${emptyText}</p>
      </div>
    `;
    return;
  }

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const groups = [];
  columns.forEach((column) => {
    const name = column.group || '';
    const previous = groups[groups.length - 1];
    if (previous && previous.name === name) previous.span += 1;
    else groups.push({ name, span: 1 });
  });

  let html = `
    <div class="table-wrapper">
      <table class="data-table">
        <thead>
          <tr class="data-table-groups">
            ${groups.map(group => `<th colspan="${group.span}">${escapeHtml(group.name)}</th>`).join('')}
          </tr>
          <tr>
            ${columns.map(col => `<th class="${escapeHtml(col.className || '')}" title="${escapeHtml(`${col.active_consumer || ''} · coverage ${((col.coverage_ratio || 0) * 100).toFixed(1)}%`)}">${escapeHtml(col.label)}</th>`).join('')}
          </tr>
        </thead>
        <tbody>
  `;

  rows.forEach((row, idx) => {
    html += `<tr data-row-idx="${idx}" class="${onRowClick ? 'is-clickable' : ''}">`;
    columns.forEach(col => {
      let cellVal = col.render ? col.render(row) : (row[col.key] ?? '');
      html += `<td class="${escapeHtml(col.className || '')}">${cellVal}</td>`;
    });
    html += `</tr>`;
  });

  html += `
        </tbody>
      </table>
    </div>
  `;

  container.innerHTML = html;

  if (onRowClick) {
    container.querySelectorAll('tbody tr').forEach(tr => {
      tr.addEventListener('click', () => {
        const idx = parseInt(tr.dataset.rowIdx, 10);
        onRowClick(rows[idx]);
      });
    });
  }
}
