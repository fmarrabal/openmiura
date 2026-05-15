/**
 * Science Review drafts view — Alpine data factory.
 *
 * Surfaces the agent's recent activity for the operator to
 * skim and pick out the ones that need their attention. The
 * data comes from the operator-console overview that already
 * powers the admin's debug pane — same endpoint, different
 * filter defaults:
 *
 *   GET /admin/operator/overview?kind=session&status=&limit=50
 *
 * The view does not commit to any verdict; the *approvals*
 * sibling factory ships the act-on-it path. This module is
 * deliberately read-only.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.sessions)) return payload.sessions;
    return [];
  }

  window.scienceReview = function () {
    return {
      items:   emptyCard(),
      showRaw: false,
      filters: { q: '', status: '', kind: 'session', only_failures: false, limit: 50 },
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
        this.items = emptyCard();
        this.lastRefreshAt = null;
      },

      _qs() {
        const parts = [];
        const f = this.filters;
        for (const key of ['q', 'status', 'kind']) {
          const v = (f[key] || '').trim();
          if (v) parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(v)}`);
        }
        if (f.only_failures) parts.push('only_failures=true');
        const limit = Math.max(1, Math.min(100, Number(f.limit) || 20));
        parts.push(`limit=${limit}`);
        return parts.length ? `?${parts.join('&')}` : '';
      },

      async refresh() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load drafts');
          return;
        }
        this.lastRefreshAt = new Date();
        const card = this.items;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.get(`/admin/operator/overview${this._qs()}`);
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

      // ----- derived -----

      itemsList() {
        return asArray(this.items.data);
      },

      isEmpty() {
        return this.items.state === 'loaded' && this.itemsList().length === 0;
      },

      statusTone(status) {
        const s = (status || '').toLowerCase();
        if (s === 'success' || s === 'completed' || s === 'ok')   return 'success';
        if (s === 'failed'  || s === 'error'     || s === 'denied') return 'danger';
        if (s === 'pending' || s === 'in_progress')                 return 'warning';
        return 'neutral';
      },
    };
  };
})();
