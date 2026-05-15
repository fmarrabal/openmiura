/**
 * Science Approvals view — Alpine data factory.
 *
 * Pending-approvals worklist for the science operator. Reads
 * the same operator-console overview as the review factory
 * but filters to kind=approval, then exposes an act-on-it
 * confirmation modal that posts:
 *
 *   POST /admin/operator/approvals/{approval_id}/actions/{action}
 *
 * The action is part of the URL path (typically "approve",
 * "deny", or a domain-specific verb the policy admits). The
 * body carries the actor + reason for the audit trail.
 *
 * The view is gated behind a modal so a click cannot go
 * through by accident — every action lands on the audit trail
 * with the reason text the operator typed.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.approvals)) return payload.approvals;
    return [];
  }

  function actorFromAuth() {
    const me = window.omAuth && window.omAuth.state.me;
    if (!me) return 'science';
    return me.principal_id || me.username || me.user_key || 'science';
  }

  window.scienceApprovals = function () {
    return {
      items:        emptyCard(),
      actionResult: emptyCard(),
      showRaw:      false,
      filters: { q: '', status: 'pending', kind: 'approval', only_failures: false, limit: 50 },

      actionForm: {
        approval_id: '',
        action:      'approve',
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
        this.items        = emptyCard();
        this.actionResult = emptyCard();
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
        return `?${parts.join('&')}`;
      },

      async refresh() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load approvals');
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

      itemsList() {
        return asArray(this.items.data);
      },

      isEmpty() {
        return this.items.state === 'loaded' && this.itemsList().length === 0;
      },

      // ----- act on an approval (confirmed) -----

      openActionDialog(approvalId, action) {
        this.actionForm = {
          approval_id: approvalId || '',
          action:      action || 'approve',
          reason:      '',
          open:        true,
          busy:        false,
          error:       '',
        };
        window.omModal.open('science-approval-action');
      },

      closeActionDialog() {
        this.actionForm.open = false;
        window.omModal.close('science-approval-action');
      },

      async submitAction() {
        const id     = (this.actionForm.approval_id || '').trim();
        const action = (this.actionForm.action || '').trim();
        const reason = (this.actionForm.reason || '').trim();
        if (!id || !action) {
          this.actionForm.error = 'approval_id and action are both required';
          return;
        }
        if (!reason) {
          this.actionForm.error = 'A short reason is required to keep the audit trail readable.';
          return;
        }
        this.actionForm.busy = true;
        this.actionForm.error = '';
        const r = await window.omApi.post(
          `/admin/operator/approvals/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`,
          { reason, actor: actorFromAuth() }
        );
        this.actionForm.busy = false;
        if (r.ok) {
          this.actionResult.data = r.data;
          this.actionResult.raw  = JSON.stringify(r.data, null, 2);
          this.actionResult.state = 'loaded';
          window.omToasts.success(`Approval ${id} → ${action}`);
          this.closeActionDialog();
          await this.refresh();
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
