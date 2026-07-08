/**
 * components/connection.js — Connection Form Logic
 * =================================================
 * Handles the connection screen form:
 *   - Input validation
 *   - API call to POST /api/connect
 *   - Loading state management
 *   - Error display
 *   - Password visibility toggle
 *
 * This component fires a custom event `db:connected` on success,
 * which script.js listens to in order to transition to the chat UI.
 */

const ConnectionForm = (() => {

  // ── State ───────────────────────────────────────────────────────────────────
  let _connecting = false;

  // ── DOM refs (lazy-loaded) ──────────────────────────────────────────────────
  const $ = id => document.getElementById(id);

  // ── Init ────────────────────────────────────────────────────────────────────

  function init() {
    const form = $('connection-form');
    if (!form) return;

    form.addEventListener('submit', _handleSubmit);
    $('toggle-password').addEventListener('click', _togglePassword);

    // Allow Enter in any field to submit (except the button which submits naturally)
    form.querySelectorAll('input').forEach(input => {
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); form.requestSubmit(); }
      });
    });
  }

  // ── Form submission ──────────────────────────────────────────────────────────

  async function _handleSubmit(e) {
    e.preventDefault();
    if (_connecting) return;

    _clearError();

    // Collect values
    const payload = {
      host:     $('db-host').value.trim(),
      port:     parseInt($('db-port').value, 10),
      username: $('db-username').value.trim(),
      password: $('db-password').value,      // password may contain spaces/specials — don't trim
      database: $('db-database').value.trim(),
    };

    // Client-side validation (fast feedback before hitting the server)
    const validationError = _validate(payload);
    if (validationError) { _showError(validationError); return; }

    _setLoading(true);

    try {
      const response = await API.post('/api/connect', payload);
      // Fire the connected event — script.js handles the transition
      document.dispatchEvent(new CustomEvent('db:connected', { detail: response }));
    } catch (err) {
      _showError(err.message || 'Connection failed. Check your credentials and try again.');
    } finally {
      _setLoading(false);
    }
  }

  // ── Validation ────────────────────────────────────────────────────────────────

  function _validate({ host, port, username, database }) {
    if (!host) return 'Host is required.';
    if (!port || port < 1 || port > 65535) return 'Port must be between 1 and 65535.';
    if (!username) return 'Username is required.';
    if (!database) return 'Database name is required.';
    return null;
  }

  // ── UI helpers ────────────────────────────────────────────────────────────────

  function _setLoading(loading) {
    _connecting = loading;
    const btn     = $('connect-btn');
    const btnText = btn.querySelector('.btn-text');
    const spinner = btn.querySelector('.btn-spinner');

    btn.disabled = loading;
    btnText.textContent = loading ? 'Connecting...' : 'Connect to Database';
    spinner.classList.toggle('hidden', !loading);
  }

  function _showError(message) {
    const el = $('connect-error');
    el.textContent = message;
    el.classList.remove('hidden');
  }

  function _clearError() {
    const el = $('connect-error');
    el.textContent = '';
    el.classList.add('hidden');
  }

  function _togglePassword() {
    const input   = $('db-password');
    const eyeOpen = $('eye-open');
    const eyeShut = $('eye-closed');
    const isHidden = input.type === 'password';
    input.type = isHidden ? 'text' : 'password';
    eyeOpen.classList.toggle('hidden', isHidden);
    eyeShut.classList.toggle('hidden', !isHidden);
  }

  return { init };
})();
