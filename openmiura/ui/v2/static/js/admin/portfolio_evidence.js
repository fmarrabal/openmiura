/**
 * Admin Portfolio evidence view — Alpine data factory.
 *
 * Portfolio-aware add-on to the (non-portfolio) Evidence
 * packs view (B7). Each portfolio carries its own bundle of
 * evidence packages: the operator picks a portfolio_id, the
 * view lists the packages, and the action endpoints expose
 * export / prune / verify / restore.
 *
 *   GET  /admin/openclaw/alert-governance/portfolios
 *   GET  /admin/openclaw/alert-governance/portfolios/{id}/evidence-packages
 *   POST /admin/openclaw/alert-governance/portfolios/{id}/evidence-package-export  (confirmed)
 *   POST /admin/openclaw/alert-governance/portfolios/{id}/evidence-packages/prune  (confirmed)
 *   POST /admin/openclaw/alert-governance/portfolios/{id}/evidence-artifact-verify (confirmed)
 *   POST /admin/openclaw/alert-governance/portfolios/{id}/evidence-artifact-restore (confirmed)
 *
 * Every write goes through a single shared confirmation
 * modal (the action verb lives in actionForm.action).
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.portfolios)) return payload.portfolios;
    if (payload && Array.isArray(payload.packages)) return payload.packages;
    if (payload && Array.isArray(payload.evidence_packages)) return payload.evidence_packages;
    return [];
  }

  // Action verb → backend path suffix (under
  // /admin/openclaw/alert-governance/portfolios/{id}/).
  const ACTION_PATHS = {
    export:  'evidence-package-export',
    prune:   'evidence-packages/prune',
    verify:  'evidence-artifact-verify',
    restore: 'evidence-artifact-restore',
  };

  window.adminPortfolioEvidence = function () {
    return {
      portfolios:   emptyCard(),
      packages:     emptyCard(),
      actionResult: emptyCard(),

      showRaw: {
        portfolios:   false,
        packages:     false,
        actionResult: false,
      },

      selectedPortfolioId: '',

      actionForm: {
        action:       'export',     // 'export' | 'prune' | 'verify' | 'restore'
        report_label: 'audit',
        artifact_ref: '',           // for verify / restore
        older_than:   '',           // for prune (ISO date or duration; backend parses)
        actor:        'admin',
        open:         false,
        busy:         false,
        error:        '',
      },

      lastRefreshAt: null,

      init() {
        if (this._authed()) this.refreshPortfolios();
        document.addEventListener('om:auth:logged-in',  () => this.refreshPortfolios());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.portfolios   = emptyCard();
        this.packages     = emptyCard();
        this.actionResult = emptyCard();
        this.selectedPortfolioId = '';
        this.lastRefreshAt = null;
      },

      async refreshPortfolios() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load portfolios');
          return;
        }
        this.lastRefreshAt = new Date();
        await this._load('portfolios', '/admin/openclaw/alert-governance/portfolios');
        // Pre-select the first portfolio if none chosen.
        const items = this.portfoliosList();
        if (!this.selectedPortfolioId && items.length > 0) {
          const id = items[0].portfolio_id || items[0].id || '';
          if (id) this.selectPortfolio(id);
        }
      },

      async selectPortfolio(id) {
        this.selectedPortfolioId = id || '';
        if (this._authed() && id) {
          await this._load(
            'packages',
            `/admin/openclaw/alert-governance/portfolios/${encodeURIComponent(id)}/evidence-packages`
          );
        } else {
          this.packages = emptyCard();
        }
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

      portfoliosList() { return asArray(this.portfolios.data); },
      packagesList()   { return asArray(this.packages.data); },

      // ----- action modal (export / prune / verify / restore) -----

      openActionDialog(action, prefillArtifactRef) {
        const a = (action || 'export').trim();
        this.actionForm = {
          action:       a,
          report_label: a === 'export' ? 'audit' : '',
          artifact_ref: prefillArtifactRef || '',
          older_than:   '',
          actor:        'admin',
          open:         true,
          busy:         false,
          error:        '',
        };
        window.omModal.open('portfolio-evidence-action');
      },

      closeActionDialog() {
        this.actionForm.open = false;
        window.omModal.close('portfolio-evidence-action');
      },

      async submitAction() {
        const id = (this.selectedPortfolioId || '').trim();
        const action = (this.actionForm.action || '').trim();
        if (!id) {
          this.actionForm.error = 'Pick a portfolio first';
          return;
        }
        const suffix = ACTION_PATHS[action];
        if (!suffix) {
          this.actionForm.error = `Unknown action: ${action}`;
          return;
        }
        if ((action === 'verify' || action === 'restore') && !this.actionForm.artifact_ref.trim()) {
          this.actionForm.error = `${action} requires an artifact_ref`;
          return;
        }
        const actor = (this.actionForm.actor || 'admin').trim() || 'admin';
        const body = { actor };
        if (action === 'export') {
          body.report_label = (this.actionForm.report_label || 'audit').trim() || 'audit';
        }
        if (action === 'prune') {
          const ot = (this.actionForm.older_than || '').trim();
          if (ot) body.older_than = ot;
        }
        if (action === 'verify' || action === 'restore') {
          body.artifact_ref = this.actionForm.artifact_ref.trim();
        }
        this.actionForm.busy = true;
        this.actionForm.error = '';
        const card = this.actionResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post(
          `/admin/openclaw/alert-governance/portfolios/${encodeURIComponent(id)}/${suffix}`,
          body
        );
        this.actionForm.busy = false;
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
          window.omToasts.success(`Portfolio ${id} → ${action}`);
          this.closeActionDialog();
          await this.selectPortfolio(id);
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
          this.actionForm.error = `HTTP ${r.status}: ${r.error}`;
        }
      },
    };
  };
})();
