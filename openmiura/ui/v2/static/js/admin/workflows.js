/**
 * Admin Workflows view — Alpine data factory.
 *
 * Lists workflow records (via the operator-console overview)
 * and lets the operator inspect a single workflow's timeline
 * + act on it.
 *
 *   GET  /admin/operator/overview?kind=workflow&status=&limit=...
 *   GET  /admin/operator/workflows/{workflow_id}
 *   POST /admin/operator/workflows/{workflow_id}/actions/{action}
 *        body: { reason, actor }                        (confirmed)
 *
 * The action verb is part of the URL path; the backend
 * decides which verbs the workflow admits.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.workflows)) return payload.workflows;
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
    if (s === 'success' || s === 'completed' || s === 'succeeded' || s === 'ok') return 'success';
    if (s === 'failed' || s === 'error' || s === 'cancelled') return 'danger';
    if (s === 'pending' || s === 'in_progress' || s === 'running' || s === 'queued') return 'warning';
    return 'neutral';
  }

  function actorFromAuth() {
    const me = window.omAuth && window.omAuth.state.me;
    if (!me) return 'admin';
    return me.principal_id || me.username || me.user_key || 'admin';
  }

  window.adminWorkflows = function () {
    return {
      list:         emptyCard(),
      detail:       emptyCard(),
      actionResult: emptyCard(),

      showRaw: { list: false, detail: false, actionResult: false },

      filters: { q: '', status: '', kind: 'workflow', only_failures: false, limit: 100 },

      selectedId: '',

      actionForm: {
        workflow_id: '',
        action:      'cancel',
        reason:      '',
        open:        false,
        busy:        false,
        error:       '',
      },

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
        this.list         = emptyCard();
        this.detail       = emptyCard();
        this.actionResult = emptyCard();
        this.selectedId   = '';
        this.lastRefreshAt = null;
      },

      async refresh() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load workflows');
          return;
        }
        this.lastRefreshAt = new Date();
        const qs = buildQS({
          q:             this.filters.q,
          status:        this.filters.status,
          kind:          this.filters.kind,
          only_failures: this.filters.only_failures ? 'true' : '',
          limit:         Math.max(1, Math.min(100, Number(this.filters.limit) || 100)),
        });
        const card = this.list;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.get(`/admin/operator/overview${qs}`);
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

      async select(id) {
        this.selectedId = id || '';
        if (this._authed() && id) {
          const card = this.detail;
          card.state = 'loading';
          card.error = null;
          const r = await window.omApi.get(`/admin/operator/workflows/${encodeURIComponent(id)}`);
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

      openActionDialog(workflowId, action) {
        this.actionForm = {
          workflow_id: workflowId || '',
          action:      action || 'cancel',
          reason:      '',
          open:        true,
          busy:        false,
          error:       '',
        };
        window.omModal.open('workflows-action');
      },

      closeActionDialog() {
        this.actionForm.open = false;
        window.omModal.close('workflows-action');
      },

      async submitAction() {
        const id     = (this.actionForm.workflow_id || '').trim();
        const action = (this.actionForm.action || '').trim();
        const reason = (this.actionForm.reason || '').trim();
        if (!id || !action) {
          this.actionForm.error = 'workflow_id and action are required';
          return;
        }
        if (!reason) {
          this.actionForm.error = 'A short reason is required (audit trail).';
          return;
        }
        this.actionForm.busy = true;
        this.actionForm.error = '';
        const r = await window.omApi.post(
          `/admin/operator/workflows/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`,
          { reason, actor: actorFromAuth() }
        );
        this.actionForm.busy = false;
        if (r.ok) {
          this.actionResult.data = r.data;
          this.actionResult.raw  = JSON.stringify(r.data, null, 2);
          this.actionResult.state = 'loaded';
          window.omToasts.success(`Workflow ${id} → ${action}`);
          this.closeActionDialog();
          await this.refresh();
          if (id === this.selectedId) await this.select(id);
        } else {
          this.actionResult.data = null;
          this.actionResult.error = `HTTP ${r.status}: ${r.error}`;
          this.actionResult.raw   = r.raw || JSON.stringify(r, null, 2);
          this.actionResult.state = 'error';
          this.actionForm.error = `HTTP ${r.status}: ${r.error}`;
        }
      },
    };
  };
})();
