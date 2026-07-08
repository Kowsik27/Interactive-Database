/**
 * components/sidebar.js — Sidebar Rendering & Navigation
 * ========================================================
 * Manages:
 *   - Database + tables display
 *   - Session list rendering
 *   - Active session highlighting
 *   - Mobile sidebar open/close
 *   - Theme toggle (dark/light)
 */

const Sidebar = (() => {

  const $ = id => document.getElementById(id);

  // ── Init ────────────────────────────────────────────────────────────────────

  function init() {
    $('new-chat-btn').addEventListener('click', _newChat);
    $('disconnect-btn').addEventListener('click', _disconnect);
    $('sidebar-open').addEventListener('click', () => openSidebar());
    $('sidebar-close').addEventListener('click', () => closeSidebar());
    $('theme-toggle').addEventListener('click', _toggleTheme);

    // Close sidebar on overlay click (mobile)
    document.addEventListener('click', e => {
      const sidebar = $('sidebar');
      if (
        sidebar.classList.contains('open') &&
        !sidebar.contains(e.target) &&
        e.target !== $('sidebar-open')
      ) {
        closeSidebar();
      }
    });

    // Restore theme preference
    const savedTheme = localStorage.getItem('dbchat-theme') || 'dark';
    _applyTheme(savedTheme);
  }

  // ── Populate with session data ───────────────────────────────────────────────

  function populate(sessionData) {
    /**
     * sessionData shape (from /api/connect response):
     * { session_id, database, host, port, server_version, tables, table_count }
     */
    // Database badge
    $('sidebar-db-name').textContent = sessionData.database;
    $('sidebar-db-host').textContent = `${sessionData.host}:${sessionData.port}`;
    $('topbar-db').textContent = sessionData.database;

    // Welcome screen
    $('welcome-db-name').textContent = sessionData.database;

    // Tables
    renderTables(sessionData.tables || []);

    // Suggestion chips based on tables
    _renderSuggestions(sessionData.tables || []);
  }

  function renderTables(tables) {
    const list  = $('table-list');
    const badge = $('table-count-badge');
    badge.textContent = tables.length;

    if (!tables.length) {
      list.innerHTML = '<span class="session-empty">No tables found</span>';
      return;
    }

    list.innerHTML = tables.map(t => `
      <div class="table-item" data-table="${_esc(t)}" title="Ask about ${_esc(t)}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="3" width="18" height="18" rx="2"/>
          <line x1="3" y1="9" x2="21" y2="9"/>
          <line x1="3" y1="15" x2="21" y2="15"/>
          <line x1="9" y1="9" x2="9" y2="21"/>
        </svg>
        ${_esc(t)}
      </div>
    `).join('');

    // Click on a table → insert suggestion into input
    list.querySelectorAll('.table-item').forEach(item => {
      item.addEventListener('click', () => {
        const tableName = item.dataset.table;
        const input = document.getElementById('chat-input');
        if (input) {
          input.value = `Show all records from ${tableName}`;
          input.focus();
          input.dispatchEvent(new Event('input'));
        }
        closeSidebar();
      });
    });
  }

  // ── Session list ────────────────────────────────────────────────────────────

  function renderSessions(sessions, activeSessionId) {
    const list = $('session-list');

    if (!sessions.length) {
      list.innerHTML = '<div class="session-empty">No previous sessions</div>';
      return;
    }

    list.innerHTML = sessions.map(s => `
      <div class="session-item ${s.session_id === activeSessionId ? 'active' : ''}"
           data-session-id="${_esc(s.session_id)}">
        <div class="session-item-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <div class="session-item-info">
          <div class="session-item-title">${_esc(s.database)}</div>
          <div class="session-item-meta">${_formatDate(s.connected_at)}</div>
        </div>
      </div>
    `).join('');

    list.querySelectorAll('.session-item').forEach(item => {
      item.addEventListener('click', () => {
        document.dispatchEvent(new CustomEvent('session:select', {
          detail: { session_id: item.dataset.sessionId }
        }));
        closeSidebar();
      });
    });
  }

  // ── Suggestion chips ─────────────────────────────────────────────────────────

  function _renderSuggestions(tables) {
    const container = $('suggestion-chips');
    if (!container) return;

    const suggestions = _buildSuggestions(tables);
    container.innerHTML = suggestions.map(s =>
      `<button class="chip" data-prompt="${_esc(s)}">${_esc(s)}</button>`
    ).join('');

    container.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const input = document.getElementById('chat-input');
        if (input) {
          input.value = chip.dataset.prompt;
          input.focus();
          input.dispatchEvent(new Event('input'));
        }
      });
    });
  }

  function _buildSuggestions(tables) {
    const base = ['Show all tables', 'How many records are in each table?'];
    if (tables.length > 0) base.push(`Show first 10 rows from ${tables[0]}`);
    if (tables.length > 1) base.push(`Count rows in ${tables[1]}`);
    if (tables.length > 2) base.push(`Describe the structure of ${tables[2]}`);
    return base;
  }

  // ── Actions ──────────────────────────────────────────────────────────────────

  function _newChat() {
    document.dispatchEvent(new CustomEvent('chat:new'));
    closeSidebar();
  }

  async function _disconnect() {
    document.dispatchEvent(new CustomEvent('db:disconnect'));
    closeSidebar();
  }

  function openSidebar() {
    $('sidebar').classList.add('open');
  }

  function closeSidebar() {
    $('sidebar').classList.remove('open');
  }

  // ── Theme ────────────────────────────────────────────────────────────────────

  function _toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    _applyTheme(next);
    localStorage.setItem('dbchat-theme', next);
  }

  function _applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const sunIcon  = document.querySelector('.icon-sun');
    const moonIcon = document.querySelector('.icon-moon');
    if (sunIcon && moonIcon) {
      sunIcon.classList.toggle('hidden', theme !== 'light');
      moonIcon.classList.toggle('hidden', theme === 'light');
    }
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function _formatDate(isoString) {
    if (!isoString) return '';
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch { return ''; }
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  return { init, populate, renderTables, renderSessions, openSidebar, closeSidebar };
})();
