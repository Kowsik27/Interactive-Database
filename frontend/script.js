/**
 * script.js — DBChat AI Application Controller
 * ==============================================
 * This is the top-level orchestrator for the frontend.
 *
 * Responsibilities:
 *   - Global application state management
 *   - API communication layer (fetch wrapper with error handling)
 *   - Toast notification system
 *   - Event coordination between components
 *   - Session persistence (localStorage)
 *   - Screen transitions (connection → chat)
 *   - Chat input handling (send, Enter, auto-resize)
 *   - New chat / session switching logic
 *
 * Architecture:
 *   API     — pure functions that call the backend
 *   State   — single source of truth for app state
 *   Toast   — global notification system (accessible by all components)
 *   App     — main controller, wires everything together
 *
 * All components (connection.js, chat.js, sidebar.js, results.js) are
 * self-contained and communicate with App via CustomEvents — no coupling.
 */

'use strict';

// ════════════════════════════════════════════════════════════════════════
// API LAYER — All backend communication happens here
// ════════════════════════════════════════════════════════════════════════

const API = (() => {
  const BASE_URL = 'http://localhost:8000';

  /**
   * Make a JSON request to the backend.
   * @param {string} method  — HTTP method
   * @param {string} path    — API path (e.g. '/api/connect')
   * @param {Object} [body]  — Request body (auto-serialised to JSON)
   * @returns {Promise<Object>} — Parsed JSON response
   * @throws {Error} with a user-readable message on any failure
   */
  async function request(method, path, body = null) {
    const options = {
      method,
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    };
    if (body) options.body = JSON.stringify(body);

    let response;
    try {
      response = await fetch(BASE_URL + path, options);
    } catch (networkErr) {
      throw new Error(
        'Cannot reach the backend server. ' +
        'Make sure uvicorn is running on port 8000.'
      );
    }

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(`Server returned non-JSON response (${response.status}).`);
    }

    if (!response.ok) {
      // Use the backend's error field if present
      const message = data.detail || data.error || `Request failed (${response.status})`;
      throw new Error(message);
    }

    return data;
  }

  const post   = (path, body) => request('POST',   path, body);
  const get    = (path)       => request('GET',    path);
  const del    = (path)       => request('DELETE', path);

  return { post, get, del, request };
})();


// ════════════════════════════════════════════════════════════════════════
// TOAST NOTIFICATION SYSTEM
// ════════════════════════════════════════════════════════════════════════

const Toast = (() => {
  /**
   * Show a toast notification.
   * @param {string} message
   * @param {'success'|'error'|'info'|'warning'} type
   * @param {number} duration — ms before auto-dismiss
   */
  function show(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
      success: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>`,
      error:   `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
      info:    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
      warning: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
    };

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span>${message}</span>`;
    container.appendChild(toast);

    const dismiss = () => {
      toast.classList.add('hiding');
      toast.addEventListener('animationend', () => toast.remove());
    };

    const timer = setTimeout(dismiss, duration);
    toast.addEventListener('click', () => { clearTimeout(timer); dismiss(); });
  }

  return { show };
})();


// ════════════════════════════════════════════════════════════════════════
// APPLICATION STATE
// ════════════════════════════════════════════════════════════════════════

const State = (() => {
  let _state = {
    sessionId: null,         // active backend session UUID
    sessionData: null,       // full ConnectResponse from /api/connect
    sessions: [],            // all stored sessions (from localStorage)
    isSending: false,        // request in flight?
    currentChatId: null,     // UUID for the current chat (local)
    localHistory: {},        // { [chatId]: [{user, assistant, sql, timestamp}] }
  };

  const STORAGE_KEY = 'dbchat-sessions';

  function get() { return { ..._state }; }

  function set(partial) { Object.assign(_state, partial); }

  // ── LocalStorage persistence ────────────────────────────────────────────────

  /**
   * Persist the list of sessions and their histories to localStorage.
   * We don't store DB credentials — only metadata and conversation history.
   */
  function saveToStorage() {
    try {
      const toSave = _state.sessions.map(s => ({
        ...s,
        history: _state.localHistory[s.chatId] || [],
      }));
      localStorage.setItem(STORAGE_KEY, JSON.stringify(toSave));
    } catch (e) {
      console.warn('Failed to save sessions to localStorage:', e);
    }
  }

  function loadFromStorage() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return;

      // Rebuild state from stored data
      const localHistory = {};
      parsed.forEach(s => {
        if (s.history) localHistory[s.chatId] = s.history;
      });
      _state.sessions = parsed.map(s => { const { history, ...rest } = s; return rest; });
      _state.localHistory = localHistory;
    } catch (e) {
      console.warn('Failed to load sessions from localStorage:', e);
    }
  }

  function clearStorage() {
    localStorage.removeItem(STORAGE_KEY);
  }

  return { get, set, saveToStorage, loadFromStorage, clearStorage };
})();


// ════════════════════════════════════════════════════════════════════════
// MAIN APPLICATION CONTROLLER
// ════════════════════════════════════════════════════════════════════════

const App = (() => {
  const $ = id => document.getElementById(id);

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  function init() {
    // Initialise all component modules
    ConnectionForm.init();
    Sidebar.init();

    // Restore previously saved sessions to sidebar
    State.loadFromStorage();
    _refreshSidebarSessions();

    // Wire up events from components
    document.addEventListener('db:connected',  e => _onConnected(e.detail));
    document.addEventListener('db:disconnect', _onDisconnect);
    document.addEventListener('chat:new',      _onNewChat);
    document.addEventListener('session:select', e => _onSessionSelect(e.detail));

    // Chat input
    _initChatInput();

    // Show connection screen (default state)
    _showScreen('connection-screen');
  }

  // ── Screen management ────────────────────────────────────────────────────────

  function _showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const target = $(screenId);
    if (target) target.classList.add('active');
  }

  // ── Connection events ────────────────────────────────────────────────────────

  function _onConnected(sessionData) {
    /**
     * sessionData is the full ConnectResponse from /api/connect:
     * { session_id, database, host, port, server_version, tables, table_count, connected_at }
     */
    const chatId = _generateId();

    State.set({
      sessionId: sessionData.session_id,
      sessionData,
      currentChatId: chatId,
    });

    // Register this session in the local session list
    const state = State.get();
    state.sessions.push({
      chatId,
      session_id: sessionData.session_id,
      database: sessionData.database,
      host: sessionData.host,
      port: sessionData.port,
      connected_at: sessionData.connected_at,
    });
    State.set({ sessions: state.sessions });
    State.saveToStorage();

    // Transition UI
    Sidebar.populate(sessionData);
    _refreshSidebarSessions();
    Chat.clearMessages();
    _showScreen('app-screen');
    _enableInput();

    Toast.show(`Connected to ${sessionData.database} (${sessionData.table_count} tables)`, 'success');
  }

  async function _onDisconnect() {
    const { sessionId, sessionData } = State.get();
    if (!sessionId) { _goToConnectionScreen(); return; }

    try {
      await API.del(`/api/disconnect/${sessionId}`);
    } catch {
      // Ignore server errors on disconnect — we're cleaning up anyway
    }

    Toast.show(`Disconnected from ${sessionData?.database || 'database'}`, 'info');
    _goToConnectionScreen();
  }

  function _goToConnectionScreen() {
    State.set({ sessionId: null, sessionData: null, currentChatId: null });
    Chat.clearMessages();
    _disableInput();
    _showScreen('connection-screen');
  }

  // ── Chat management ──────────────────────────────────────────────────────────

  async function _onNewChat() {
    const chatId = _generateId();
    const { sessions, sessionData, sessionId } = State.get();

    if (!sessionId) return;

    // Clear the backend's conversation history for this session so the LLM
    // starts fresh — otherwise it would still see the old chat context.
    try {
      await API.del(`/api/history/${sessionId}`);
    } catch {
      // Non-fatal — proceed with new chat even if clearing fails
    }

    // Add a new session entry to the local list
    sessions.push({
      chatId,
      session_id: sessionId,
      database: sessionData.database,
      host: sessionData.host,
      port: sessionData.port,
      connected_at: new Date().toISOString(),
    });

    State.set({ currentChatId: chatId, sessions });
    State.saveToStorage();
    Chat.clearMessages();
    _refreshSidebarSessions();
  }

  function _onSessionSelect(detail) {
    // detail.session_id is actually chatId (see _refreshSidebarSessions)
    const { sessions, localHistory } = State.get();
    const session = sessions.find(s => s.chatId === detail.session_id);
    if (!session) return;

    State.set({ currentChatId: session.chatId });
    const history = localHistory[session.chatId] || [];
    Chat.restoreHistory(history);
    _refreshSidebarSessions();
  }

  // ── Chat input handling ──────────────────────────────────────────────────────

  function _initChatInput() {
    const input   = $('chat-input');
    const sendBtn = $('send-btn');
    const counter = $('char-count');

    if (!input || !sendBtn) return;

    // Auto-resize textarea as user types
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;

      const len = input.value.length;
      counter.textContent = `${len}/2000`;
      counter.classList.toggle('warning', len > 1800);

      sendBtn.disabled = input.value.trim().length === 0 || State.get().isSending;
    });

    // Send on Enter (Shift+Enter = newline)
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!sendBtn.disabled) _sendMessage();
      }
    });

    sendBtn.addEventListener('click', _sendMessage);
  }

  async function _sendMessage() {
    const { sessionId, isSending } = State.get();
    if (!sessionId || isSending) return;

    const input = $('chat-input');
    const message = input.value.trim();
    if (!message) return;

    // Capture message, clear input immediately
    input.value = '';
    input.style.height = 'auto';
    $('char-count').textContent = '0/2000';
    $('send-btn').disabled = true;

    State.set({ isSending: true });
    Chat.appendUserMessage(message);
    Chat.showTypingIndicator();

    try {
      const response = await API.post('/api/chat', {
        session_id: sessionId,
        message,
      });

      Chat.appendAIResponse(response);

      // Persist this turn in local history
      _saveLocalTurn(message, response);

    } catch (err) {
      Chat.removeTypingIndicator();
      Chat.appendAIResponse({
        explanation: `Something went wrong: ${err.message}`,
        sql: null, columns: null, rows: null,
        row_count: null, execution_time_ms: null,
        error: err.message, is_safe: null,
        timestamp: new Date().toISOString(),
      });
      Toast.show(err.message, 'error');
    } finally {
      State.set({ isSending: false });
      const newInput = $('chat-input');
      if (newInput) {
        newInput.disabled = false;
        $('send-btn').disabled = newInput.value.trim().length === 0;
      }
    }
  }

  function _saveLocalTurn(userMessage, response) {
    const { currentChatId, localHistory } = State.get();
    if (!currentChatId) return;

    if (!localHistory[currentChatId]) localHistory[currentChatId] = [];
    localHistory[currentChatId].push({
      user: userMessage,
      assistant: response.explanation || '',
      sql: response.sql || null,
      timestamp: response.timestamp || new Date().toISOString(),
    });

    State.set({ localHistory });
    State.saveToStorage();
  }

  // ── Input enable / disable ────────────────────────────────────────────────────

  function _enableInput() {
    const input = $('chat-input');
    if (input) input.disabled = false;
  }

  function _disableInput() {
    const input   = $('chat-input');
    const sendBtn = $('send-btn');
    if (input) { input.disabled = true; input.value = ''; }
    if (sendBtn) sendBtn.disabled = true;
  }

  // ── Sidebar helpers ───────────────────────────────────────────────────────────

  function _refreshSidebarSessions() {
    const { sessions, currentChatId } = State.get();
    // Show the most recent chats first (each "New Chat" is its own entry)
    const sorted = [...sessions].reverse().slice(0, 20);
    Sidebar.renderSessions(
      sorted.map(s => ({
        session_id: s.chatId,      // use chatId as the unique key per-chat
        database: s.database,
        connected_at: s.connected_at,
        chatId: s.chatId,
      })),
      currentChatId,               // highlight the currently active chat
    );
  }

  // ── Utilities ──────────────────────────────────────────────────────────────────

  function _generateId() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }

  return { init };
})();


// ════════════════════════════════════════════════════════════════════════
// BOOTSTRAP
// ════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => App.init());
