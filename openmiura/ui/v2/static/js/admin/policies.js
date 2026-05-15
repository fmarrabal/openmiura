/**
 * Admin Policies view — Alpine data factory.
 *
 * Renders the policy surface that an operator interacts with on
 * a daily basis: registered policy packs (read-only), a snapshot
 * of the current policy state (read-only), and three small forms
 * that hit the policy explorer:
 *
 *   - Explain  — why did (or would) this request resolve the way
 *                it did, given the active policy?
 *   - Simulate — what would change if I applied this candidate
 *                policy (YAML) instead of the active one?
 *   - Diff     — given a baseline and a candidate, list the
 *                differences and show how the same N sample
 *                requests would resolve under each.
 *
 * No write action ships in this PR. Applying a policy pack to a
 * runtime exists on the backend (POST /admin/openclaw/runtimes/
 * {id}/policy-pack) but is deferred to PR-B5 (Identities & RBAC)
 * once we have a confirmation pattern that fits.
 *
 * Endpoints (read-only unless flagged):
 *   GET  /admin/openclaw/policy-packs
 *   GET  /admin/policy-explorer/snapshot
 *   POST /admin/policies/explain               (read-modeled: no state change)
 *   POST /admin/policy-explorer/simulate       (read-modeled: no state change)
 *   POST /admin/policy-explorer/diff           (read-modeled: no state change)
 *
 * The factory mirrors the shape of adminDashboard / adminRuntimes:
 * per-card { state, data, error, raw } + show-raw toggles.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function emptyExplainForm() {
    return {
      scope:         'tool',
      resource_name: '',
      action:        'use',
      agent_name:    '',
      tool_name:     '',
      user_role:     '',
      tenant_id:     '',
      workspace_id:  '',
      environment:   '',
      channel:       '',
      domain:        '',
    };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.policy_packs)) return payload.policy_packs;
    return [];
  }

  function trimOrNull(s) {
    const v = (s == null ? '' : String(s)).trim();
    return v ? v : null;
  }

  function explainPayload(form) {
    // Strip empty optional fields so the backend defaults take
    // over; otherwise the JSON sends literal "" which fails
    // PolicyExplainRequest validation for fields like scope/resource.
    const out = {
      scope:         (form.scope || 'tool').trim(),
      resource_name: (form.resource_name || '').trim(),
      action:        (form.action || 'use').trim() || 'use',
    };
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

  window.adminPolicies = function () {
    return {
      // per-card state
      packs:           emptyCard(),
      snapshot:        emptyCard(),
      explainResult:   emptyCard(),
      simulateResult:  emptyCard(),
      diffResult:      emptyCard(),

      showRaw: {
        packs:          false,
        snapshot:       false,
        explainResult:  false,
        simulateResult: false,
        diffResult:     false,
      },

      filter: '',
      runtimeClass: '',

      explainForm:  emptyExplainForm(),
      simulateForm: {
        ...emptyExplainForm(),
        candidate_policy_yaml: '',
      },
      diffForm: {
        candidate_policy_yaml: '',
        baseline_policy_yaml:  '',
        samples_json:          '[]',
        samples_error:         '',
      },

      lastRefreshAt: null,

      init() {
        if (this._authed()) this.refreshAll();
        document.addEventListener('om:auth:logged-in', () => this.refreshAll());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.packs          = emptyCard();
        this.snapshot       = emptyCard();
        this.explainResult  = emptyCard();
        this.simulateResult = emptyCard();
        this.diffResult     = emptyCard();
        this.lastRefreshAt  = null;
      },

      // ----- reads -----

      async refreshAll() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load policies');
          return;
        }
        this.lastRefreshAt = new Date();
        await Promise.all([
          this.refreshPacks(),
          this.refreshSnapshot(),
        ]);
      },

      async refreshPacks() {
        const cls = (this.runtimeClass || '').trim();
        const path = cls
          ? `/admin/openclaw/policy-packs?runtime_class=${encodeURIComponent(cls)}`
          : '/admin/openclaw/policy-packs';
        await this._load('packs', path);
      },

      async refreshSnapshot() {
        await this._load('snapshot', '/admin/policy-explorer/snapshot');
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

      // ----- derived (packs list) -----

      packsList() {
        return asArray(this.packs.data);
      },

      filteredPacks() {
        const q = this.filter.trim().toLowerCase();
        const items = this.packsList();
        if (!q) return items;
        return items.filter((p) => JSON.stringify(p).toLowerCase().includes(q));
      },

      packCount() {
        return this.packsList().length;
      },

      // ----- writes (read-modeled) -----

      async submitExplain() {
        if (!this._authed()) return;
        const body = explainPayload(this.explainForm);
        if (!body.resource_name) {
          this.explainResult.state = 'error';
          this.explainResult.error = 'resource_name is required';
          return;
        }
        await this._post('explainResult', '/admin/policies/explain', body);
      },

      async submitSimulate() {
        if (!this._authed()) return;
        const request = explainPayload(this.simulateForm);
        if (!request.resource_name) {
          this.simulateResult.state = 'error';
          this.simulateResult.error = 'resource_name is required';
          return;
        }
        const body = { request, candidate_policy: {} };
        const yaml = (this.simulateForm.candidate_policy_yaml || '').trim();
        if (yaml) body.candidate_policy_yaml = yaml;
        await this._post('simulateResult', '/admin/policy-explorer/simulate', body);
      },

      async submitDiff() {
        if (!this._authed()) return;
        let samples = [];
        const txt = (this.diffForm.samples_json || '').trim();
        if (txt) {
          try {
            samples = JSON.parse(txt);
            if (!Array.isArray(samples)) {
              this.diffForm.samples_error = 'Samples must be a JSON array';
              return;
            }
          } catch (e) {
            this.diffForm.samples_error = `Invalid JSON: ${e.message || e}`;
            return;
          }
        }
        this.diffForm.samples_error = '';
        const body = {
          candidate_policy: {},
          baseline_policy:  {},
          samples,
        };
        const c = (this.diffForm.candidate_policy_yaml || '').trim();
        const b = (this.diffForm.baseline_policy_yaml  || '').trim();
        if (c) body.candidate_policy_yaml = c;
        if (b) body.baseline_policy_yaml  = b;
        await this._post('diffResult', '/admin/policy-explorer/diff', body);
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

      // ----- derived (explain/simulate/diff result summary) -----

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
        if (l === 'allow' || l === 'permit') return 'success';
        if (l === 'deny'  || l === 'block')  return 'danger';
        if (l === 'review' || l === 'pending') return 'warning';
        return 'neutral';
      },

      diffChangedCount() {
        const d = this.diffResult.data;
        if (!d) return null;
        if (typeof d.changed === 'number') return d.changed;
        if (Array.isArray(d.sample_results)) {
          return d.sample_results.filter((s) => s && s.changed).length;
        }
        return null;
      },
    };
  };
})();
