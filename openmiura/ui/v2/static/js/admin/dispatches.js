/**
 * Admin Dispatches view — Alpine data factory.
 *
 * Lists OpenClaw dispatch records (action executions across
 * runtimes) and lets the operator act on a stuck one. Three
 * confirmed-write actions per dispatch:
 *
 *   - cancel    — POST /admin/openclaw/dispatches/{id}/cancel
 *   - retry     — POST /admin/openclaw/dispatches/{id}/retry
 *   - reconcile — POST /admin/openclaw/dispatches/{id}/reconcile
 *                 (manual status override; the most surgical
 *                 of the three — used when retry/cancel can't
 *                 untangle a half-applied state).
 *
 * Endpoints:
 *   GET  /admin/openclaw/dispatches?runtime_id=&action=&status=&limit=...
 *   GET  /admin/openclaw/dispatches/{dispatch_id}
 *   POST /admin/openclaw/dispatches/{dispatch_id}/cancel       (confirmed)
 *   POST /admin/openclaw/dispatches/{dispatch_id}/retry        (confirmed)
 *   POST /admin/openclaw/dispatches/{dispatch_id}/reconcile    (confirmed)
 *
 * Per-card { state, data, error, raw } pattern.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.dispatches)) return payload.dispatches;
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
    if (s === 'succeeded' || s === 'success' || s === 'completed' || s === 'ok') return 'success';
    if (s === 'failed' || s === 'error' || s === 'cancelled' || s === 'denied') return 'danger';
    if (s === 'pending' || s === 'in_progress' || s === 'queued' || s === 'running') return 'warning';
    return 'neutral';
  }

  window.adminDispatches = function () {
    return {
      list:        emptyCard(),
      detail:      emptyCard(),
      actionResult: emptyCard(),

      showRaw: {
        list:         false,
        detail:       false,
        actionResult: false,
      },

      filters: {
        runtime_id: '',
        action:     '',
        status:     '',
        limit:      100,
      },

      selectedId: '',

      // Generic action form drives cancel / retry / reconcile.
      actionForm: {
        dispatch_id:   '',
        action:        'cancel',     // 'cancel' | 'retry' | 'reconcile'
        reason:        '',
        target_status: '',           // reconcile only
        actor:         'admin',
        open:          false,
        busy:          false,
        error:         '',
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
          window.omToasts.warning('Connect first to load dispatches');
          return;
        }
        this.lastRefreshAt = new Date();
        const qs = buildQS({
          runtime_id: this.filters.runtime_id,
          action:     this.filters.action,
          status:     this.filters.status,
          limit:      Math.max(1, Math.min(300, Number(this.filters.limit) || 100)),
        });
        await this._load('list', `/admin/openclaw/dispatches${qs}`);
      },

      async select(id) {
        this.selectedId = id || '';
        if (this._authed() && id) {
          await this._load('detail', `/admin/openclaw/dispatches/${encodeURIComponent(id)}`);
        } else {
          this.detail = emptyCard();
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

      itemsList()    { return asArray(this.list.data); },
      isEmpty()      { return this.list.state === 'loaded' && this.itemsList().length === 0; },
      statusTone,

      openActionDialog(dispatchId, action) {
        this.actionForm = {
          dispatch_id:   dispatchId || '',
          action:        action || 'cancel',
          reason:        '',
          target_status: '',
          actor:         'admin',
          open:          true,
          busy:          false,
          error:         '',
        };
        window.omModal.open('dispatches-action');
      },

      closeActionDialog() {
        this.actionForm.open = false;
        window.omModal.close('dispatches-action');
      },

      async submitAction() {
        const id     = (this.actionForm.dispatch_id || '').trim();
        const action = (this.actionForm.action || '').trim();
        const reason = (this.actionForm.reason || '').trim();
        const actor  = (this.actionForm.actor  || 'admin').trim() || 'admin';
        if (!id || !action) {
          this.actionForm.error = 'dispatch_id and action are required';
          return;
        }
        if (!reason) {
          this.actionForm.error = 'A short reason is required (audit trail).';
          return;
        }
        if (action === 'reconcile') {
          const tgt = (this.actionForm.target_status || '').trim();
          if (!tgt) {
            this.actionForm.error = 'reconcile requires a target_status';
            return;
          }
        }
        this.actionForm.busy = true;
        this.actionForm.error = '';
        const body = { reason, actor };
        if (action === 'reconcile') {
          body.target_status = (this.actionForm.target_status || '').trim();
        }
        const card = this.actionResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post(
          `/admin/openclaw/dispatches/${encodeURIComponent(id)}/${encodeURIComponent(action)}`,
          body
        );
        this.actionForm.busy = false;
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
          window.omToasts.success(`Dispatch ${id} → ${action}`);
          this.closeActionDialog();
          await this.refresh();
          if (id === this.selectedId) await this.select(id);
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
