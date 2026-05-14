/**
 * Admin Dashboard view — Alpine data factory.
 *
 * Renders an overview of the active scope, a few key metrics (counts
 * for runtimes, recent events, sessions, evidence packs) and a list
 * of the most recent admin events. Each card has a "raw" toggle that
 * folds out the verbatim JSON payload from the underlying endpoint
 * — visual by default, JSON one click away for debug.
 *
 * Endpoints consulted (read-only):
 *   GET /admin/status
 *   GET /admin/sessions
 *   GET /admin/events?limit=10
 *   GET /admin/openclaw/runtimes
 *   GET /admin/canvas/documents
 *
 * The component handles three lifecycle states per card:
 *   loading | loaded | error
 *
 * Authentication is mandatory; when `omAuth` reports no token, the
 * dashboard renders a friendly "connect to see data" prompt instead
 * of attempting any request.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function fmtTime(ts) {
    if (!ts) return '—';
    const n = typeof ts === 'number' ? ts : Date.parse(ts);
    if (Number.isNaN(n)) return String(ts);
    return new Date(n * (n > 1e12 ? 1 : 1000)).toLocaleString();
  }

  window.adminDashboard = function () {
    return {
      // per-card state
      status:    emptyCard(),
      sessions:  emptyCard(),
      events:    emptyCard(),
      runtimes:  emptyCard(),
      canvas:    emptyCard(),

      showRaw: {
        status:    false,
        sessions:  false,
        events:    false,
        runtimes:  false,
        canvas:    false,
      },

      autoRefreshSeconds: 0, // 0 = off
      _refreshHandle: null,
      lastRefreshAt: null,

      init() {
        // First load if we are already authenticated.
        if (this._isAuthenticated()) {
          this.refreshAll();
        }
        // Auto-refresh on connect.
        document.addEventListener('om:auth:logged-in', () => this.refreshAll());
        document.addEventListener('om:auth:logged-out', () => this._clearAll());
      },

      destroy() {
        this._cancelAutoRefresh();
      },

      _isAuthenticated() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clearAll() {
        this.status = emptyCard();
        this.sessions = emptyCard();
        this.events = emptyCard();
        this.runtimes = emptyCard();
        this.canvas = emptyCard();
        this.lastRefreshAt = null;
        this._cancelAutoRefresh();
      },

      _cancelAutoRefresh() {
        if (this._refreshHandle) {
          clearInterval(this._refreshHandle);
          this._refreshHandle = null;
        }
      },

      toggleAutoRefresh() {
        if (this._refreshHandle) {
          this._cancelAutoRefresh();
          this.autoRefreshSeconds = 0;
        } else {
          this.autoRefreshSeconds = 15;
          this._refreshHandle = setInterval(() => this.refreshAll(), this.autoRefreshSeconds * 1000);
        }
      },

      async refreshAll() {
        if (!this._isAuthenticated()) {
          window.omToasts.warning('Connect first to load dashboard data');
          return;
        }
        this.lastRefreshAt = new Date();
        await Promise.all([
          this._load('status',   '/admin/status'),
          this._load('sessions', '/admin/sessions?limit=1'),
          this._load('events',   '/admin/events?limit=10'),
          this._load('runtimes', '/admin/openclaw/runtimes'),
          this._load('canvas',   '/admin/canvas/documents?limit=1'),
        ]);
      },

      async _load(key, path) {
        const card = this[key];
        card.state = 'loading';
        card.error = null;
        const result = await window.omApi.get(path);
        if (result.ok) {
          card.data = result.data;
          card.raw = JSON.stringify(result.data, null, 2);
          card.state = 'loaded';
        } else {
          card.data = null;
          card.error = `HTTP ${result.status}: ${result.error}`;
          card.raw = result.raw || JSON.stringify(result, null, 2);
          card.state = 'error';
        }
      },

      // ----- derived stats -----

      runtimesCount() {
        const d = this.runtimes.data;
        if (!d) return null;
        if (Array.isArray(d)) return d.length;
        if (Array.isArray(d.items)) return d.items.length;
        if (typeof d.count === 'number') return d.count;
        return Object.keys(d).length;
      },

      sessionsCount() {
        const d = this.sessions.data;
        if (!d) return null;
        if (typeof d.summary === 'object' && d.summary && typeof d.summary.count === 'number') {
          return d.summary.count;
        }
        if (Array.isArray(d.items)) return d.items.length;
        if (Array.isArray(d)) return d.length;
        return null;
      },

      eventsItems() {
        const d = this.events.data;
        if (!d) return [];
        if (Array.isArray(d)) return d;
        if (Array.isArray(d.items)) return d.items;
        return [];
      },

      canvasCount() {
        const d = this.canvas.data;
        if (!d) return null;
        if (Array.isArray(d.items)) return d.items.length;
        if (Array.isArray(d)) return d.length;
        if (typeof d.summary === 'object' && d.summary && typeof d.summary.count === 'number') {
          return d.summary.count;
        }
        return null;
      },

      scopeSummary() {
        const me = window.omAuth && window.omAuth.state.me;
        if (!me) return null;
        return {
          tenant_id:    me.tenant_id    || me.scope?.tenant_id    || '—',
          workspace_id: me.workspace_id || me.scope?.workspace_id || '—',
          environment:  me.environment  || me.scope?.environment  || '—',
          principal:    me.username || me.principal_id || me.user_key || '—',
          role:         me.role || me.auth_mode || '—',
        };
      },

      fmtTime,
    };
  };
})();
