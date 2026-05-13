/**
 * API module — thin wrapper over fetch() that injects auth headers
 * and normalises error shapes.
 *
 * Used by every UI v2 page. Exposes a single global `omApi` with:
 *
 *   omApi.request(path, { method, body, headers, signal }) -> Promise<Result>
 *   omApi.get(path, opts?)
 *   omApi.post(path, body, opts?)
 *   omApi.put(path, body, opts?)
 *   omApi.del(path, opts?)
 *
 * Where Result is `{ ok, status, data, error, raw }`.
 *
 * The wrapper:
 *
 * - Prefixes paths with the configured base URL (from omAuth, falling
 *   back to `${location.origin}/broker`).
 * - Adds `Authorization: Bearer <token>` when omAuth has a token.
 * - Sets Content-Type and JSON-encodes object bodies automatically.
 * - Treats a 401 as a logout signal and emits `om:auth:expired`.
 * - Always returns; never throws on HTTP errors — callers inspect
 *   `result.ok` / `result.error`.
 */
(function () {
  'use strict';

  function baseUrl() {
    if (window.omAuth && window.omAuth.state && window.omAuth.state.baseUrl) {
      return window.omAuth.state.baseUrl.replace(/\/$/, '');
    }
    return `${location.origin.replace(/\/$/, '')}/broker`;
  }

  function authHeader() {
    if (window.omAuth && window.omAuth.state && window.omAuth.state.token) {
      return { Authorization: `Bearer ${window.omAuth.state.token}` };
    }
    return {};
  }

  async function request(path, options) {
    const opts = options || {};
    const url = path.startsWith('http')
      ? path
      : `${baseUrl()}${path.startsWith('/') ? path : '/' + path}`;

    const headers = Object.assign(
      {},
      authHeader(),
      opts.headers || {}
    );

    let body = opts.body;
    if (
      body !== undefined &&
      body !== null &&
      typeof body === 'object' &&
      !(body instanceof FormData) &&
      !(body instanceof Blob)
    ) {
      headers['Content-Type'] = headers['Content-Type'] || 'application/json';
      body = JSON.stringify(body);
    }

    let response;
    try {
      response = await fetch(url, {
        method: opts.method || 'GET',
        headers,
        body,
        signal: opts.signal,
        credentials: opts.credentials || 'same-origin',
      });
    } catch (err) {
      // Network-level failure (CORS, DNS, offline...). Report as
      // ok=false but distinguish from HTTP errors by a missing status.
      return { ok: false, status: 0, data: null, error: err.message || String(err), raw: '' };
    }

    const raw = await response.text();
    let data = null;
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch (_) {
        data = { raw };
      }
    }

    if (response.status === 401) {
      document.dispatchEvent(new CustomEvent('om:auth:expired'));
    }

    if (response.ok) {
      return { ok: true, status: response.status, data, error: null, raw };
    }
    const errorMessage =
      (data && (data.detail || data.error)) ||
      raw ||
      `HTTP ${response.status}`;
    return { ok: false, status: response.status, data, error: errorMessage, raw };
  }

  window.omApi = {
    request,
    get(path, opts) {
      return request(path, Object.assign({}, opts, { method: 'GET' }));
    },
    post(path, body, opts) {
      return request(path, Object.assign({}, opts, { method: 'POST', body }));
    },
    put(path, body, opts) {
      return request(path, Object.assign({}, opts, { method: 'PUT', body }));
    },
    del(path, opts) {
      return request(path, Object.assign({}, opts, { method: 'DELETE' }));
    },
    _baseUrl: baseUrl, // exposed for tests / debug only
  };
})();
