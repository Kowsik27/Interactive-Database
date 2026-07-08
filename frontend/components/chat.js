/**
 * components/chat.js — Chat Message Rendering
 * =============================================
 * Manages the chat messages area:
 *   - Rendering user messages
 *   - Rendering AI messages (with results embedded via Results.render)
 *   - Typing indicator
 *   - Auto-scroll behaviour
 *   - Welcome state show/hide
 *
 * Message format:
 *   { role: 'user' | 'ai', content: string, data?: ChatResponse, timestamp: Date }
 */

const Chat = (() => {

  const $ = id => document.getElementById(id);
  let _typingEl = null;

  // ── Public API ──────────────────────────────────────────────────────────────

  /**
   * Append a user message bubble to the chat area.
   */
  function appendUserMessage(text) {
    _hideWelcome();
    const el = _createMessage('user', text);
    $('messages-container').appendChild(el);
    _scrollToBottom();
  }

  /**
   * Append a full AI response (explanation + optional results).
   * @param {Object} data — ChatResponse from backend
   */
  function appendAIResponse(data) {
    removeTypingIndicator();
    _hideWelcome();

    const msg = document.createElement('div');
    msg.className = 'message message--ai';
    msg.setAttribute('data-session-id', data.session_id || '');

    const avatar = _makeAvatar('ai');
    const body   = document.createElement('div');
    body.className = 'message-body';

    const hasResults = data.sql || (data.columns && data.columns.length > 0);

    if (hasResults) {
      // When we have SQL + results, the Results block renders everything
      // including the explanation at the bottom — no separate bubble needed.
      body.appendChild(Results.render(data));
    } else {
      // Pure text response (no SQL generated) — render as a plain bubble.
      const bubble = document.createElement('div');
      bubble.className = 'message-bubble';
      bubble.textContent = data.explanation || '…';
      body.appendChild(bubble);

      // Show error detail if present
      if (data.error) {
        const errEl = document.createElement('div');
        errEl.className = 'error-block';
        errEl.style.marginTop = '0.5rem';
        errEl.innerHTML = `<strong>Error:</strong> ${_esc(data.error)}`;
        body.appendChild(errEl);
      }
    }

    // Timestamp
    const meta = document.createElement('div');
    meta.className = 'message-meta';
    meta.textContent = _formatTime(data.timestamp || new Date().toISOString());
    body.appendChild(meta);

    msg.appendChild(avatar);
    msg.appendChild(body);
    $('messages-container').appendChild(msg);
    _scrollToBottom();
  }

  /**
   * Show a 3-dot typing indicator while waiting for the API.
   */
  function showTypingIndicator() {
    removeTypingIndicator();
    _hideWelcome();

    const msg = document.createElement('div');
    msg.className = 'message message--ai';
    msg.id = 'typing-message';

    const avatar = _makeAvatar('ai');
    const body   = document.createElement('div');
    body.className = 'message-body';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.innerHTML = `
      <div class="typing-indicator">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    `;

    body.appendChild(bubble);
    msg.appendChild(avatar);
    msg.appendChild(body);
    $('messages-container').appendChild(msg);
    _typingEl = msg;
    _scrollToBottom();
  }

  function removeTypingIndicator() {
    const el = $('typing-message');
    if (el) el.remove();
    _typingEl = null;
  }

  /**
   * Clear all messages (new chat).
   */
  function clearMessages() {
    $('messages-container').innerHTML = '';
    _showWelcome();
  }

  /**
   * Restore messages from stored history array.
   * @param {Array} history — array of { user, assistant, sql, timestamp }
   */
  function restoreHistory(history) {
    clearMessages();
    history.forEach(turn => {
      appendUserMessage(turn.user);
      appendAIResponse({
        explanation: turn.assistant,
        sql: turn.sql || null,
        columns: null,
        rows: null,
        row_count: null,
        execution_time_ms: null,
        error: null,
        is_safe: null,
        timestamp: turn.timestamp,
      });
    });
  }

  // ── Private helpers ─────────────────────────────────────────────────────────

  function _createMessage(role, text) {
    const el = document.createElement('div');
    el.className = `message message--${role}`;

    const avatar = _makeAvatar(role);
    const body   = document.createElement('div');
    body.className = 'message-body';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = text;

    const meta = document.createElement('div');
    meta.className = 'message-meta';
    meta.textContent = _formatTime(new Date().toISOString());

    body.appendChild(bubble);
    body.appendChild(meta);
    el.appendChild(avatar);
    el.appendChild(body);
    return el;
  }

  function _makeAvatar(role) {
    const div = document.createElement('div');
    div.className = 'message-avatar';
    div.textContent = role === 'user' ? 'U' : 'AI';
    return div;
  }

  function _hideWelcome() {
    const w = $('welcome-state');
    if (w) w.style.display = 'none';
  }

  function _showWelcome() {
    const w = $('welcome-state');
    if (w) w.style.display = '';
  }

  function _scrollToBottom() {
    const area = $('chat-area');
    if (area) area.scrollTop = area.scrollHeight;
  }

  function _formatTime(isoString) {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch { return ''; }
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  return {
    appendUserMessage,
    appendAIResponse,
    showTypingIndicator,
    removeTypingIndicator,
    clearMessages,
    restoreHistory,
  };
})();
