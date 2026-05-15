/**
 * Admin Secrets view — Alpine data factory.
 *
 * Renders the secret-governance surface that the openMiura
 * admin exposes for compliance and forensics. Four read-only
 * cards + one read-modeled explain form:
 *
 *   - Summary   — denied vs allowed access events, latency
 *                 percentiles and a tone for the global health.
 *   - Catalog   — declared secret refs visible in the scope
 *                 (governance inventory; the values themselves
 *                 never leave the backend).
 *   - Timeline  — access events filtered by ref / tool / outcome.
 *   - Usage     — per-(ref, tool) counts.
 *   - Explain   — POST /admin/secrets/explain: replay a
 *                 (ref, tool_name, user_role) decision and
 *                 surface the policy reason without consuming
 *                 the secret. Read-modeled — no state change.
 *
 * The config-center secrets wizard (POST save) is out of scope
 * for this PR; it mutates dotenv profiles on disk and deserves
 * its own confirmation pattern. It is read-only-reachable from
 * the B6 (Channels) view when the wizard ships.
 *
 * Endpoints (read-only unless flagged):
 *   GET  /admin/secrets/summary
 *   GET  /admin/secrets/catalog
 *   GET  /admin/secrets/timeline
 *   GET  /admin/secrets/usage
 *   POST /admin/secrets/explain
 *
 * Per-card { state, data, error, raw } pattern mirrors B1/B2/B3.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
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

  window.adminSecrets = function () {
    return {
      summary:        emptyCard(),
      catalog:        emptyCard(),
      timeline:       emptyCard(),
      usage:          emptyCard(),
      explainResult:  emptyCard(),

      showRaw: {
        summary:        false,
        catalog:        false,
        timeline:       false,
        usage:          false,
        explainResult:  false,
      },

      // shared filters
      filters: {
        q:       '',
        ref:     '',
        tool:    '',
        outcome: '',  // for timeline only
        limit:   100,
      },

      explainForm: {
        ref:       '',
        tool_name: '',
        user_role: '',
      },

      lastRefreshAt: null,

      init() {
        if (this._authed()) this.refreshAll();
        document.addEventListener('om:auth:logged-in',  () => this.refreshAll());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.summary       = emptyCard();
        this.catalog       = emptyCard();
        this.timeline      = emptyCard();
        this.usage         = emptyCard();
        this.explainResult = emptyCard();
        this.lastRefreshAt = null;
      },

      // ----- reads -----

      async refreshAll() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load secret governance');
          return;
        }
        this.lastRefreshAt = new Date();
        await Promise.all([
          this.refreshSummary(),
          this.refreshCatalog(),
          this.refreshTimeline(),
          this.refreshUsage(),
        ]);
      },

      async refreshSummary() {
        const qs = buildQS({ limit: this.filters.limit });
        await this._load('summary', `/admin/secrets/summary${qs}`);
      },

      async refreshCatalog() {
        const qs = buildQS({
          q:     this.filters.q,
          limit: this.filters.limit,
        });
        await this._load('catalog', `/admin/secrets/catalog${qs}`);
      },

      async refreshTimeline() {
        const qs = buildQS({
          q:         this.filters.q,
          ref:       this.filters.ref,
          tool_name: this.filters.tool,
          outcome:   this.filters.outcome,
          limit:     this.filters.limit,
        });
        await this._load('timeline', `/admin/secrets/timeline${qs}`);
      },

      async refreshUsage() {
        const qs = buildQS({
          q:         this.filters.q,
          ref:       this.filters.ref,
          tool_name: this.filters.tool,
          limit:     this.filters.limit,
        });
        await this._load('usage', `/admin/secrets/usage${qs}`);
      },

      async _load(key, path) {
        const card = this[key];
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.get(path);
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

      // ----- write (read-modeled) -----

      async submitExplain() {
        const ref = (this.explainForm.ref || '').trim();
        const tool = (this.explainForm.tool_name || '').trim();
        if (!ref || !tool) {
          this.explainResult.state = 'error';
          this.explainResult.error = 'ref and tool_name are both required';
          return;
        }
        const body = { ref, tool_name: tool };
        const role = (this.explainForm.user_role || '').trim();
        if (role) body.user_role = role;
        const card = this.explainResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/secrets/explain', body);
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

      summaryStats() {
        const d = this.summary.data;
        const s = (d && d.summary) || d || {};
        const total  = s.total_events  ?? s.total  ?? null;
        const denied = s.denied_events ?? s.denied ?? null;
        const allowed = (total != null && denied != null) ? total - denied : null;
        const rate = (total != null && denied != null && total > 0)
          ? Math.round((denied / total) * 1000) / 10  // one decimal %
          : null;
        return { total, denied, allowed, deny_rate_pct: rate };
      },

      summaryTone() {
        const s = this.summaryStats();
        if (s.deny_rate_pct == null) return 'neutral';
        if (s.deny_rate_pct === 0) return 'success';
        if (s.deny_rate_pct < 5)   return 'warning';
        return 'danger';
      },

      catalogItems() {
        return asArray(this.catalog.data);
      },

      timelineItems() {
        return asArray(this.timeline.data);
      },

      usageItems() {
        return asArray(this.usage.data);
      },

      decisionLabel(d) {
        if (!d) return '—';
        if (typeof d.decision === 'string') return d.decision;
        if (typeof d.outcome  === 'string') return d.outcome;
        if (d.allow === true)  return 'allow';
        if (d.allow === false) return 'deny';
        return '—';
      },

      decisionTone(label) {
        const l = (label || '').toLowerCase();
        if (l === 'allow' || l === 'permit')   return 'success';
        if (l === 'deny'  || l === 'block')    return 'danger';
        if (l === 'review' || l === 'pending') return 'warning';
        return 'neutral';
      },
    };
  };
})();
