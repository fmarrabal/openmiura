/**
 * Admin Runtimes view — Alpine data factory.
 *
 * Lists registered OpenClaw runtime adapters, lets the operator
 * select one and inspect its concurrency state, alerts,
 * notification targets and alert-routing. Provides a single
 * write action in this PR: trigger a recovery job (confirmation
 * modal). Policy-pack registration is deferred to PR-B3
 * (Policies), batch dispatches to a follow-up.
 *
 * Endpoints (read-only unless flagged write):
 *   GET  /admin/openclaw/runtimes
 *   GET  /admin/openclaw/runtimes/{id}/concurrency
 *   GET  /admin/openclaw/runtimes/{id}/alerts
 *   GET  /admin/openclaw/runtimes/{id}/notification-targets
 *   GET  /admin/openclaw/runtimes/{id}/alert-routing
 *   POST /admin/openclaw/runtimes/{id}/recovery-jobs       (write)
 *
 * The factory mirrors the shape of adminDashboard from B1:
 * per-card { state, data, error, raw } + show-raw toggles.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asArray(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.items)) return payload.items;
    if (payload && Array.isArray(payload.runtimes)) return payload.runtimes;
    return [];
  }

  function runtimeId(item) {
    return (
      (item && (item.runtime_id || item.id || item.name)) || ''
    );
  }

  window.adminRuntimes = function () {
    return {
      runtimes:           emptyCard(),
      concurrency:        emptyCard(),
      alerts:             emptyCard(),
      notificationTargets: emptyCard(),
      alertRouting:       emptyCard(),

      showRaw: { runtimes: false, concurrency: false, alerts: false, notificationTargets: false, alertRouting: false },

      selectedId: '',
      filter: '',
      recoveryForm: { reason: '', open: false, busy: false, error: '' },
      lastRefreshAt: null,

      init() {
        if (this._authed()) this.refreshList();
        document.addEventListener('om:auth:logged-in', () => this.refreshList());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.runtimes = emptyCard();
        this.concurrency = emptyCard();
        this.alerts = emptyCard();
        this.notificationTargets = emptyCard();
        this.alertRouting = emptyCard();
        this.selectedId = '';
        this.lastRefreshAt = null;
      },

      // ----- list -----

      async refreshList() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load runtimes');
          return;
        }
        this.lastRefreshAt = new Date();
        await this._load('runtimes', '/admin/openclaw/runtimes');
        // Re-select if the previous one is still there.
        const items = this.itemsList();
        if (this.selectedId && items.find((r) => runtimeId(r) === this.selectedId)) {
          await this.refreshDetail();
        } else if (items.length > 0) {
          this.selectedId = runtimeId(items[0]);
          await this.refreshDetail();
        } else {
          this.selectedId = '';
        }
      },

      itemsList() {
        return asArray(this.runtimes.data);
      },

      filteredItems() {
        const q = this.filter.trim().toLowerCase();
        const items = this.itemsList();
        if (!q) return items;
        return items.filter((r) => {
          const blob = JSON.stringify(r).toLowerCase();
          return blob.includes(q);
        });
      },

      selectedRuntime() {
        return this.itemsList().find((r) => runtimeId(r) === this.selectedId) || null;
      },

      async select(id) {
        this.selectedId = id;
        if (this._authed() && id) await this.refreshDetail();
      },

      // ----- detail -----

      async refreshDetail() {
        if (!this.selectedId) return;
        const id = encodeURIComponent(this.selectedId);
        await Promise.all([
          this._load('concurrency',         `/admin/openclaw/runtimes/${id}/concurrency`),
          this._load('alerts',              `/admin/openclaw/runtimes/${id}/alerts`),
          this._load('notificationTargets', `/admin/openclaw/runtimes/${id}/notification-targets`),
          this._load('alertRouting',        `/admin/openclaw/runtimes/${id}/alert-routing`),
        ]);
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

      alertCount() {
        const items = asArray(this.alerts.data);
        return items.length;
      },

      notificationTargetCount() {
        return asArray(this.notificationTargets.data).length;
      },

      alertRoutingPolicyVersions() {
        const d = this.alertRouting.data;
        if (!d) return 0;
        if (Array.isArray(d.versions)) return d.versions.length;
        if (typeof d.version_count === 'number') return d.version_count;
        return null;
      },

      concurrencySummary() {
        const d = this.concurrency.data;
        if (!d) return null;
        const max = d.max_concurrent ?? d.max_inflight ?? d.limit ?? null;
        const cur = d.current ?? d.inflight ?? d.in_flight ?? null;
        return { current: cur, max };
      },

      // ----- write: trigger recovery job -----

      openRecoveryDialog() {
        if (!this.selectedId) {
          window.omToasts.warning('Select a runtime first');
          return;
        }
        this.recoveryForm = { reason: '', open: true, busy: false, error: '' };
        window.omModal.open('runtimes-recovery');
      },

      closeRecoveryDialog() {
        this.recoveryForm.open = false;
        window.omModal.close('runtimes-recovery');
      },

      async submitRecovery() {
        if (!this.selectedId) return;
        if (!this.recoveryForm.reason.trim()) {
          this.recoveryForm.error = 'A reason is required to keep the audit trail readable.';
          return;
        }
        this.recoveryForm.busy = true;
        this.recoveryForm.error = '';
        const id = encodeURIComponent(this.selectedId);
        const r = await window.omApi.post(
          `/admin/openclaw/runtimes/${id}/recovery-jobs`,
          { reason: this.recoveryForm.reason.trim() }
        );
        this.recoveryForm.busy = false;
        if (r.ok) {
          window.omToasts.success(`Recovery job created on ${this.selectedId}`);
          this.closeRecoveryDialog();
          await this.refreshDetail();
        } else {
          this.recoveryForm.error = `HTTP ${r.status}: ${r.error}`;
        }
      },
    };
  };
})();
