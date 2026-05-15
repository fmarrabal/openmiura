/**
 * Science Evidence history view — Alpine data factory.
 *
 * The operator-facing read of the compliance summary that B7
 * already exposes for admins. Same endpoint, no scope filters
 * by default so the science user sees their active-scope
 * window without typing tenant/workspace ids.
 *
 * Endpoint:
 *   GET /admin/compliance/summary?window_hours=72&limit_per_section=20
 *
 * Strictly read-only — there is no export trigger here. To
 * actually build a downloadable pack the operator drops into
 * the admin Evidence packs view (PR-B7 #52); this surface
 * just lets a science user verify their work appears on the
 * trail.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  const SECTION_KEYS = [
    'overview',
    'security',
    'secret_usage',
    'approvals',
    'config_changes',
    'tool_calls',
    'sessions',
  ];

  window.scienceHistory = function () {
    return {
      summary: emptyCard(),
      showRaw: false,
      filters: { window_hours: 72, limit_per_section: 20 },
      lastRefreshAt: null,

      sectionKeys() { return SECTION_KEYS; },

      init() {
        if (this._authed()) this.refresh();
        document.addEventListener('om:auth:logged-in',  () => this.refresh());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.summary = emptyCard();
        this.lastRefreshAt = null;
      },

      _qs() {
        const w = Math.max(1, Math.min(24 * 30, Number(this.filters.window_hours) || 72));
        const l = Math.max(1, Math.min(200, Number(this.filters.limit_per_section) || 20));
        return `?window_hours=${w}&limit_per_section=${l}`;
      },

      async refresh() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load your evidence history');
          return;
        }
        this.lastRefreshAt = new Date();
        const card = this.summary;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.get(`/admin/compliance/summary${this._qs()}`);
        if (r.ok) {
          card.data = r.data;
          card.raw  = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw  = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
        }
      },

      sectionCount(key) {
        const d = this.summary.data;
        if (!d) return null;
        const sec = d[key] || (d.sections && d.sections[key]) || null;
        if (!sec) return null;
        if (Array.isArray(sec)) return sec.length;
        if (Array.isArray(sec.items)) return sec.items.length;
        if (typeof sec.count === 'number') return sec.count;
        if (typeof sec.total === 'number') return sec.total;
        return null;
      },
    };
  };
})();
