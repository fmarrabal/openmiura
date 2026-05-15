/**
 * Admin Identities & RBAC view — Alpine data factory.
 *
 * Surfaces the identity-link model openMiura uses internally:
 * a (channel_user_key, global_user_key) bridge that lets the
 * audit trail collapse a person operating across several
 * channels (Slack handle, Telegram alias, voice phone number,
 * ...) into a single global principal. The RBAC layer is
 * derived from the principal scope (tenant / workspace /
 * environment / role) and inspected here via the existing
 * read-modeled explain endpoints.
 *
 *   - Identities — list of (channel_user_key → global_user_key)
 *                  bindings; filter by global_user_key.
 *   - Sessions   — active operator sessions.
 *   - Link       — POST /admin/identities/link with a confirmation
 *                  modal (audit-only — it does not grant a role,
 *                  it records a binding that future policy
 *                  decisions can use).
 *   - Sandbox    — POST /admin/sandbox/explain: what capability
 *                  bundle does (role × scope) receive?
 *   - Security   — POST /admin/security/explain: would this (role
 *                  × scope) access the resource? Same per-card
 *                  pattern as the policies B3 explain.
 *
 * Endpoints:
 *   GET  /admin/identities[?global_user_key=...]
 *   GET  /admin/sessions[?limit=...]
 *   POST /admin/identities/link                 (write, confirmed)
 *   POST /admin/sandbox/explain                 (read-modeled)
 *   POST /admin/security/explain                (read-modeled)
 *
 * Per-card { state, data, error, raw } pattern mirrors B1..B4.
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

  function trimOrNull(s) {
    const v = (s == null ? '' : String(s)).trim();
    return v ? v : null;
  }

  function buildScopePayload(form) {
    // Optional scope fields shared by sandbox + security explain.
    const out = {};
    for (const key of [
      'agent_name', 'tool_name', 'user_role',
      'tenant_id', 'workspace_id', 'environment',
      'channel', 'domain',
    ]) {
      const v = trimOrNull(form[key]);
      if (v !== null) out[key] = v;
    }
    return out;
  }

  window.adminIdentities = function () {
    return {
      identities:      emptyCard(),
      sessions:        emptyCard(),
      sandboxResult:   emptyCard(),
      securityResult:  emptyCard(),

      showRaw: {
        identities:     false,
        sessions:       false,
        sandboxResult:  false,
        securityResult: false,
      },

      filters: {
        global_user_key: '',
        sessions_limit:  50,
      },

      linkForm: {
        channel_user_key: '',
        global_user_key:  '',
        linked_by:        'admin',
        open:             false,
        busy:             false,
        error:            '',
      },

      sandboxForm: {
        user_role:   '',
        tenant_id:   '',
        workspace_id:'',
        environment: '',
        channel:     '',
        agent_name:  '',
        tool_name:   '',
      },

      securityForm: {
        scope:         'tool',
        resource_name: '',
        action:        'use',
        user_role:     '',
        agent_name:    '',
        tool_name:     '',
        tenant_id:     '',
        workspace_id:  '',
        environment:   '',
        channel:       '',
        domain:        '',
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
        this.identities     = emptyCard();
        this.sessions       = emptyCard();
        this.sandboxResult  = emptyCard();
        this.securityResult = emptyCard();
        this.lastRefreshAt  = null;
      },

      // ----- reads -----

      async refreshAll() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load identities');
          return;
        }
        this.lastRefreshAt = new Date();
        await Promise.all([
          this.refreshIdentities(),
          this.refreshSessions(),
        ]);
      },

      async refreshIdentities() {
        const k = (this.filters.global_user_key || '').trim();
        const path = k
          ? `/admin/identities?global_user_key=${encodeURIComponent(k)}`
          : '/admin/identities';
        await this._load('identities', path);
      },

      async refreshSessions() {
        const limit = Math.max(1, Math.min(500, Number(this.filters.sessions_limit) || 50));
        await this._load('sessions', `/admin/sessions?limit=${limit}`);
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

      // ----- derived -----

      identitiesItems() {
        return asArray(this.identities.data);
      },

      sessionsItems() {
        return asArray(this.sessions.data);
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

      // ----- link identity (confirmed write) -----

      openLinkDialog() {
        this.linkForm = {
          channel_user_key: '',
          global_user_key:  '',
          linked_by:        'admin',
          open:             true,
          busy:             false,
          error:            '',
        };
        window.omModal.open('identities-link');
      },

      closeLinkDialog() {
        this.linkForm.open = false;
        window.omModal.close('identities-link');
      },

      async submitLink() {
        const channelKey = (this.linkForm.channel_user_key || '').trim();
        const globalKey  = (this.linkForm.global_user_key  || '').trim();
        const linkedBy   = (this.linkForm.linked_by        || 'admin').trim();
        if (!channelKey || !globalKey) {
          this.linkForm.error = 'channel_user_key and global_user_key are both required';
          return;
        }
        this.linkForm.busy = true;
        this.linkForm.error = '';
        const r = await window.omApi.post('/admin/identities/link', {
          channel_user_key: channelKey,
          global_user_key:  globalKey,
          linked_by:        linkedBy,
        });
        this.linkForm.busy = false;
        if (r.ok) {
          window.omToasts.success(`Linked ${channelKey} → ${globalKey}`);
          this.closeLinkDialog();
          await this.refreshIdentities();
        } else {
          this.linkForm.error = `HTTP ${r.status}: ${r.error}`;
        }
      },

      // ----- read-modeled writes (explain) -----

      async submitSandbox() {
        if (!this._authed()) return;
        const body = buildScopePayload(this.sandboxForm);
        await this._post('sandboxResult', '/admin/sandbox/explain', body);
      },

      async submitSecurity() {
        if (!this._authed()) return;
        const resource = (this.securityForm.resource_name || '').trim();
        if (!resource) {
          this.securityResult.state = 'error';
          this.securityResult.error = 'resource_name is required';
          return;
        }
        const body = {
          scope:         (this.securityForm.scope || 'tool').trim(),
          resource_name: resource,
          action:        (this.securityForm.action || 'use').trim() || 'use',
          ...buildScopePayload(this.securityForm),
        };
        await this._post('securityResult', '/admin/security/explain', body);
      },

      async _post(key, path, body) {
        const card = this[key];
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post(path, body);
        if (r.ok) {
          card.data = r.data;
          card.raw  = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw   = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
        }
      },
    };
  };
})();
