/**
 * Admin Debug pane — Alpine data factory.
 *
 * Covers the two sidebar items under the Debug group:
 *
 *   - Event log    (id: 'events')     → GET /admin/events
 *   - Tool calls   (id: 'tool-calls') → GET /admin/traces (+ detail)
 *
 * Two factories live in this module:
 *
 *   adminEventLog()    — recent admin events, channel filter.
 *   adminToolCalls()   — recent decision traces with filters
 *                        (session/user/agent/channel/status),
 *                        plus a trace-detail card when an
 *                        operator clicks a row.
 *
 * Both are strictly read-only.
 *
 *   GET /admin/events?limit=&channel=...
 *   GET /admin/traces?limit=&session_id=&user_key=&agent_id=&channel=&status=...
 *   GET /admin/traces/{trace_id}
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.events)) return payload.events;
    if (payload && Array.isArray(payload.traces)) return payload.traces;
    return [];
  }

  function buildQS(params) {
    const parts = [];
    for (const [k, v] of Object.entries(params || {})) {
      const s = (v == null ? '' : String(v)).trim();
      if (s) parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(s)}`);
    }
    return parts.length ? `?${parts.join('&')}` : '';
  }

  function statusTone(status) {
    const s = (status || '').toLowerCase();
    if (s === 'allow' || s === 'success' || s === 'ok' || s === 'completed') return 'success';
    if (s === 'deny'  || s === 'failed'  || s === 'error') return 'danger';
    if (s === 'review' || s === 'pending' || s === 'queued') return 'warning';
    return 'neutral';
  }

  // ------------------------------------------------------------------
  // Event log factory
  // ------------------------------------------------------------------

  window.adminEventLog = function () {
    return {
      list:    emptyCard(),
      showRaw: false,
      filters: { channel: '', limit: 100 },
      lastRefreshAt: null,

      init() {
        if (this._authed()) this.refresh();
        document.addEventListener('om:auth:logged-in',  () => this.refresh());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.list = emptyCard();
        this.lastRefreshAt = null;
      },

      async refresh() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load the event log');
          return;
        }
        this.lastRefreshAt = new Date();
        const qs = buildQS({
          channel: this.filters.channel,
          limit:   Math.max(1, Math.min(500, Number(this.filters.limit) || 100)),
        });
        const card = this.list;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.get(`/admin/events${qs}`);
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
        }
      },

      itemsList() { return asArray(this.list.data); },
      isEmpty()   { return this.list.state === 'loaded' && this.itemsList().length === 0; },
    };
  };

  // ------------------------------------------------------------------
  // Tool calls factory (decision traces)
  // ------------------------------------------------------------------

  window.adminToolCalls = function () {
    return {
      list:    emptyCard(),
      detail:  emptyCard(),
      showRaw: { list: false, detail: false },

      filters: {
        session_id: '',
        user_key:   '',
        agent_id:   '',
        channel:    '',
        status:     '',
        limit:      100,
      },

      selectedId: '',
      lastRefreshAt: null,

      init() {
        if (this._authed()) this.refresh();
        document.addEventListener('om:auth:logged-in',  () => this.refresh());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.list   = emptyCard();
        this.detail = emptyCard();
        this.selectedId = '';
        this.lastRefreshAt = null;
      },

      async refresh() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load decision traces');
          return;
        }
        this.lastRefreshAt = new Date();
        const qs = buildQS({
          session_id: this.filters.session_id,
          user_key:   this.filters.user_key,
          agent_id:   this.filters.agent_id,
          channel:    this.filters.channel,
          status:     this.filters.status,
          limit:      Math.max(1, Math.min(200, Number(this.filters.limit) || 100)),
        });
        const card = this.list;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.get(`/admin/traces${qs}`);
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
        }
      },

      async select(traceId) {
        this.selectedId = traceId || '';
        if (this._authed() && traceId) {
          const card = this.detail;
          card.state = 'loading';
          card.error = null;
          const r = await window.omApi.get(`/admin/traces/${encodeURIComponent(traceId)}`);
          if (r.ok) {
            card.data = r.data;
            card.raw = JSON.stringify(r.data, null, 2);
            card.state = 'loaded';
          } else {
            card.data = null;
            card.error = `HTTP ${r.status}: ${r.error}`;
            card.raw = r.raw || JSON.stringify(r, null, 2);
            card.state = 'error';
          }
        } else {
          this.detail = emptyCard();
        }
      },

      itemsList() { return asArray(this.list.data); },
      isEmpty()   { return this.list.state === 'loaded' && this.itemsList().length === 0; },
      statusTone,
    };
  };
})();
