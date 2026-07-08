/**
 * components/results.js — SQL Block & Query Results Renderer
 * ===========================================================
 * Responsible for rendering:
 *   - SQL code block (with syntax highlighting-lite via CSS classes)
 *   - Query metadata (row count, execution time)
 *   - Results table (sortable columns, null value handling)
 *   - Copy SQL button
 *   - Export CSV button
 *   - AI explanation block
 *   - Error block
 */

const Results = (() => {

  // ── Public render entry point ────────────────────────────────────────────────

  /**
   * Build the full result HTML for one AI response.
   *
   * @param {Object} data — ChatResponse from /api/chat
   * @returns {HTMLElement} — The assembled result DOM node
   */
  function render(data) {
    const container = document.createElement('div');
    container.className = 'result-block';

    // 1. AI explanation FIRST — user gets the answer immediately before
    //    having to scroll through SQL and a table.
    if (data.explanation) {
      container.appendChild(_buildExplanation(data.explanation));
    }

    // 2. SQL block — collapsible, so it doesn't dominate the view
    if (data.sql) {
      container.appendChild(_buildSQLBlock(data.sql));
    }

    // 3. Query metadata (row count + execution time)
    if (data.row_count !== null && data.row_count !== undefined) {
      container.appendChild(_buildMetaRow(data));
    }

    // 4. Error block (shown when query ran but DB returned an error)
    if (data.error && data.sql) {
      container.appendChild(_buildErrorBlock(data.error));
    }

    // 5. Results table
    if (data.columns && data.rows && data.columns.length > 0) {
      container.appendChild(_buildTableSection(data));
    }

    return container;
  }

  // ── SQL Block ────────────────────────────────────────────────────────────────

  function _buildSQLBlock(sql) {
    const block = document.createElement('div');
    block.className = 'sql-block';

    block.innerHTML = `
      <div class="sql-block-header" role="button" aria-expanded="true">
        <div class="sql-block-title">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>
          </svg>
          Generated SQL
        </div>
        <div class="sql-block-actions">
          <button class="btn btn-ghost copy-sql-btn" title="Copy SQL">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
            Copy
          </button>
          <svg class="sql-toggle-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </div>
      </div>
      <div class="sql-block-body collapsed">
        <pre>${_formatSQL(sql)}</pre>
      </div>
    `;

    // SQL starts collapsed — users read the explanation first.
    // They expand only when they want to inspect or copy the query.
    const header = block.querySelector('.sql-block-header');
    const body   = block.querySelector('.sql-block-body');
    const icon   = block.querySelector('.sql-toggle-icon');

    // Set initial state (collapsed)
    header.setAttribute('aria-expanded', 'false');
    icon.classList.add('rotated');

    header.addEventListener('click', e => {
      if (e.target.closest('.copy-sql-btn')) return; // don't collapse when copying
      const collapsed = body.classList.toggle('collapsed');
      icon.classList.toggle('rotated', collapsed);
      header.setAttribute('aria-expanded', String(!collapsed));
    });

    // Copy button
    block.querySelector('.copy-sql-btn').addEventListener('click', e => {
      e.stopPropagation();
      _copyToClipboard(sql, e.currentTarget);
    });

    return block;
  }

  // ── Query Metadata Row ───────────────────────────────────────────────────────

  function _buildMetaRow(data) {
    const row = document.createElement('div');
    row.className = 'query-meta';

    const timeIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`;
    const rowIcon  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`;

    const timeDisplay = data.execution_time_ms !== null
      ? (data.execution_time_ms < 1000
          ? `${Math.round(data.execution_time_ms)}ms`
          : `${(data.execution_time_ms / 1000).toFixed(2)}s`)
      : '—';

    const rowDisplay = data.row_count === 0
      ? 'No rows'
      : `${data.row_count?.toLocaleString()} row${data.row_count === 1 ? '' : 's'}`;

    row.innerHTML = `
      <span class="query-meta-item">${rowIcon}<span class="value">${rowDisplay}</span></span>
      <span class="query-meta-item">${timeIcon}<span class="value">${timeDisplay}</span></span>
      ${data.is_safe === true ? '<span class="query-meta-item text-success">✓ Validated safe</span>' : ''}
    `;

    return row;
  }

  // ── Results Table ────────────────────────────────────────────────────────────

  function _buildTableSection(data) {
    const section = document.createElement('div');

    // Export button row
    const actionBar = document.createElement('div');
    actionBar.className = 'table-actions';
    actionBar.innerHTML = `
      <span class="table-row-info">${data.rows.length.toLocaleString()} of ${data.row_count?.toLocaleString()} rows shown</span>
      <button class="btn btn-ghost export-csv-btn">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="7 10 12 15 17 10"/>
          <line x1="12" y1="15" x2="12" y2="3"/>
        </svg>
        Export CSV
      </button>
    `;

    actionBar.querySelector('.export-csv-btn').addEventListener('click', () => {
      _exportCSV(data.columns, data.rows);
    });

    section.appendChild(actionBar);

    // Table wrapper
    const wrap = document.createElement('div');
    wrap.className = 'result-table-wrap';
    wrap.appendChild(_buildTable(data.columns, data.rows));
    section.appendChild(wrap);

    return section;
  }

  function _buildTable(columns, rows) {
    const table = document.createElement('table');
    table.className = 'result-table';

    // Head
    const thead = document.createElement('thead');
    thead.innerHTML = `<tr>${columns.map(c => `<th title="${_esc(c)}">${_esc(c)}</th>`).join('')}</tr>`;
    table.appendChild(thead);

    // Body
    const tbody = document.createElement('tbody');
    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${columns.length}" style="text-align:center;padding:1.5rem;color:var(--text-muted)">No results</td></tr>`;
    } else {
      rows.forEach(row => {
        const tr = document.createElement('tr');
        tr.innerHTML = row.map(v =>
          v === null
            ? `<td><span class="null-value">NULL</span></td>`
            : `<td title="${_esc(String(v))}">${_esc(String(v))}</td>`
        ).join('');
        tbody.appendChild(tr);
      });
    }
    table.appendChild(tbody);

    return table;
  }

  // ── Explanation ──────────────────────────────────────────────────────────────

  function _buildExplanation(text) {
    const div = document.createElement('div');
    div.className = 'explanation-block';
    div.textContent = text;
    return div;
  }

  // ── Error Block ──────────────────────────────────────────────────────────────

  function _buildErrorBlock(error) {
    const div = document.createElement('div');
    div.className = 'error-block';
    div.innerHTML = `<strong>Error:</strong> ${_esc(error)}`;
    return div;
  }

  // ── Utilities ────────────────────────────────────────────────────────────────

  function _formatSQL(sql) {
    // Lightweight SQL keyword highlighting via HTML spans
    // (avoids an external syntax highlighting dependency)
    const keywords = [
      'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN',
      'OUTER JOIN', 'ON', 'GROUP BY', 'ORDER BY', 'HAVING', 'LIMIT', 'OFFSET',
      'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'AS', 'WITH', 'UNION', 'ALL',
      'DISTINCT', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'CASE', 'WHEN', 'THEN',
      'ELSE', 'END', 'BETWEEN', 'LIKE', 'ASC', 'DESC', 'EXISTS', 'SUBQUERY',
    ];
    let escaped = _esc(sql);
    // We only highlight standalone uppercase keywords to avoid false matches
    const pattern = new RegExp(`\\b(${keywords.join('|')})\\b`, 'g');
    return escaped.replace(pattern, '<span style="color:var(--accent);font-weight:600">$1</span>');
  }

  async function _copyToClipboard(text, btn) {
    try {
      await navigator.clipboard.writeText(text);
      const original = btn.innerHTML;
      btn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Copied!`;
      btn.style.color = 'var(--success)';
      setTimeout(() => {
        btn.innerHTML = original;
        btn.style.color = '';
      }, 2000);
    } catch {
      Toast.show('Failed to copy — please copy manually.', 'error');
    }
  }

  function _exportCSV(columns, rows) {
    const escape = v => {
      const s = v === null ? '' : String(v);
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? `"${s.replace(/"/g, '""')}"`
        : s;
    };

    const csvLines = [
      columns.map(escape).join(','),
      ...rows.map(row => row.map(escape).join(',')),
    ];
    const blob = new Blob([csvLines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = `dbchat_export_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    Toast.show('CSV exported successfully.', 'success');
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  return { render };
})();
