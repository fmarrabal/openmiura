/**
 * Auth module — connection state shared by every UI v2 page.
 *
 * Two supported modes:
 *
 *   - 'token' : a static admin / broker token is pasted by the
 *               operator; the page uses it on every request.
 *   - 'login' : username + password are POSTed to /auth/login,
 *               the returned session token replaces them in
 *               state.token.
 *
 * State is persisted to localStorage under `openmiura.v2.auth.*`.
 * Pages that need to react to changes subscribe to:
 *
 *   document.addEventListener('om:auth:changed', e => e.detail)
 *   document.addEventListener('om:auth:logged-in', e => e.detail)
 *   document.addEventListener('om:auth:logged-out', e => {})
 *   document.addEventListener('om:auth:expired',   e => {})  // 401
 *
 * The auth module deliberately does NOT depend on Alpine; the
 * matching reactive component lives in shell.js (`omAuthPanel`).
 */
(function () {
  'use strict';

  const KEYS = {
    baseUrl:  'openmiura.v2.auth.baseUrl',
    mode:     'openmiura.v2.auth.mode',
    token:    'openmiura.v2.auth.token',
    username: 'openmiura.v2.auth.username',
  };

  function read(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v === null || v === undefined ? fallback : v;
    } catch (_) {
      return fallback;
    }
  }

  function write(key, value) {
    try {
      if (value === null || value === undefined || value === '') {
        localStorage.removeItem(key);
      } else {
        localStorage.setItem(key, value);
      }
    } catch (_) {
      /* ignore */
    }
  }

  function emit(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail: detail || null }));
  }

  // --- State ---------------------------------------------------------

  const state = {
    baseUrl:  read(KEYS.baseUrl, `${location.origin.replace(/\/$/, '')}/broker`),
    mode:     read(KEYS.mode, 'token'),     // 'token' | 'login'
    token:    read(KEYS.token, ''),
    username: read(KEYS.username, ''),
    me:       null,                          // last fetched identity
    status:   'idle',                        // idle | connecting | connected | error
    error:    '',
  };

  function snapshot() {
    return Object.assign({}, state);
  }

  function update(partial) {
    Object.assign(state, partial);
    emit('om:auth:changed', snapshot());
  }

  function persist() {
    write(KEYS.baseUrl, state.baseUrl);
    write(KEYS.mode, state.mode);
    write(KEYS.token, state.token);
    write(KEYS.username, state.username);
  }

  // --- Public surface -----------------------------------------------

  async function fetchMe() {
    if (!window.omApi) throw new Error('omApi is not loaded');
    const result = await window.omApi.get('/auth/me');
    if (result.ok) {
      update({ me: result.data, status: 'connected', error: '' });
      return result.data;
    }
    update({ me: null, status: 'error', error: result.error });
    return null;
  }

  async function connectWithToken(token) {
    if (!token) {
      update({ status: 'error', error: 'token is required' });
      return false;
    }
    update({ mode: 'token', token, status: 'connecting', error: '' });
    persist();
    const me = await fetchMe();
    if (me) {
      emit('om:auth:logged-in', snapshot());
      return true;
    }
    return false;
  }

  async function connectWithLogin(username, password) {
    if (!window.omApi) throw new Error('omApi is not loaded');
    if (!username || !password) {
      update({ status: 'error', error: 'username and password are required' });
      return false;
    }
    update({
      mode: 'login',
      username,
      token: '',
      status: 'connecting',
      error: '',
    });
    persist();
    const result = await window.omApi.post('/auth/login', { username, password });
    if (!result.ok || !result.data || !result.data.token) {
      update({
        status: 'error',
        error: result.error || 'login response did not include a token',
        token: '',
        me: null,
      });
      return false;
    }
    update({ token: result.data.token });
    persist();
    const me = await fetchMe();
    if (me) {
      emit('om:auth:logged-in', snapshot());
      return true;
    }
    return false;
  }

  async function logout() {
    if (state.token && window.omApi) {
      // Best-effort logout against the broker; ignore failures.
      try {
        await window.omApi.post('/auth/logout', {});
      } catch (_) { /* ignore */ }
    }
    update({ token: '', me: null, status: 'idle', error: '' });
    persist();
    emit('om:auth:logged-out');
  }

  function setBaseUrl(url) {
    if (!url) return;
    const trimmed = url.trim().replace(/\/$/, '');
    update({ baseUrl: trimmed });
    persist();
  }

  // Auto-logout on 401 from any request
  document.addEventListener('om:auth:expired', () => {
    if (state.token || state.me) {
      update({ token: '', me: null, status: 'error', error: 'session expired (401)' });
      persist();
      emit('om:auth:logged-out');
    }
  });

  window.omAuth = {
    state,                  // direct read access (snapshot via getter below)
    snapshot,
    connectWithToken,
    connectWithLogin,
    logout,
    fetchMe,
    setBaseUrl,
    setMode(mode) {
      if (mode !== 'token' && mode !== 'login') return;
      update({ mode, error: '' });
      persist();
    },
  };

  // If we have a stored token and we're in token mode, validate it
  // silently on load. The page can still render before this resolves.
  if (state.mode === 'token' && state.token) {
    fetchMe().catch(() => { /* swallowed; status reflects the error */ });
  }
})();
