/**
 * Admin Evidence packs view — Alpine data factory.
 *
 * Closes out Phase B with the compliance-export surface every
 * GxP audit cycle needs. Two cards + one confirmed write:
 *
 *   - Summary  — GET /admin/compliance/summary
 *                Read-only overview for a (scope × window) pair
 *                with section counts (security, secret usage,
 *                approvals, config changes, tool calls,
 *                sessions). Surfaces an audit_event_id so the
 *                read itself appears on the audit trail.
 *
 *   - Export   — POST /admin/compliance/export
 *                Builds a downloadable evidence pack. Confirmed
 *                write because (a) it costs real CPU on the
 *                backend, (b) the action is recorded with a
 *                report_label that the auditor sees later.
 *
 * The "Debug pane" referenced in the PR-B7 brief is already
 * satisfied by the per-card show-raw toggle pattern shipped
 * across B1..B6 — every Alpine card has a raw-JSON pane one
 * click away. We do not duplicate that here.
 *
 * Endpoints:
 *   GET  /admin/compliance/summary
 *   POST /admin/compliance/export       (write, confirmed)
 *
 * Per-card { state, data, error, raw } pattern mirrors B1..B6.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  // Section keys mirror the backend default list in
  // ComplianceExportRequest.sections.
  const SECTION_KEYS = [
    'overview',
    'security',
    'secret_usage',
    'approvals',
    'config_changes',
    'tool_calls',
    'sessions',
  ];

  function defaultSectionState() {
    const out = {};
    for (const k of SECTION_KEYS) out[k] = true;
    return out;
  }

  function sectionsArray(state) {
    return SECTION_KEYS.filter((k) => state[k]);
  }

  window.adminEvidence = function () {
    return {
      summary:       emptyCard(),
      exportResult:  emptyCard(),

      showRaw: {
        summary:      false,
        exportResult: false,
      },

      filters: {
        tenant_id:         '',
        workspace_id:      '',
        environment:       '',
        window_hours:      72,
        limit_per_section: 20,
      },

      exportForm: {
        report_label: 'audit',
        sections:     defaultSectionState(),
        open:         false,
        busy:         false,
        error:        '',
      },

      lastRefreshAt: null,

      // expose constants for the template
      sectionKeys() { return SECTION_KEYS; },

      init() {
        if (this._authed()) this.refreshSummary();
        document.addEventListener('om:auth:logged-in',  () => this.refreshSummary());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.summary      = emptyCard();
        this.exportResult = emptyCard();
        this.lastRefreshAt = null;
      },

      _qs() {
        const parts = [];
        const f = this.filters;
        for (const key of ['tenant_id', 'workspace_id', 'environment']) {
          const v = (f[key] || '').trim();
          if (v) parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(v)}`);
        }
        const w = Math.max(1, Math.min(24 * 30, Number(f.window_hours) || 72));
        const l = Math.max(1, Math.min(200, Number(f.limit_per_section) || 20));
        parts.push(`window_hours=${w}`);
        parts.push(`limit_per_section=${l}`);
        return `?${parts.join('&')}`;
      },

      async refreshSummary() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load compliance summary');
          return;
        }
        this.lastRefreshAt = new Date();
        const card = this.summary;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.get(`/admin/compliance/summary${this._qs()}`);
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

      // ----- derived (summary) -----

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

      auditEventId() {
        const d = this.summary.data;
        return (d && d.audit_event_id) || null;
      },

      // ----- export (confirmed write) -----

      openExportDialog() {
        this.exportForm = {
          report_label: this.exportForm.report_label || 'audit',
          sections:     defaultSectionState(),
          open:         true,
          busy:         false,
          error:        '',
        };
        window.omModal.open('evidence-export');
      },

      closeExportDialog() {
        this.exportForm.open = false;
        window.omModal.close('evidence-export');
      },

      toggleSection(key) {
        this.exportForm.sections[key] = !this.exportForm.sections[key];
      },

      async submitExport() {
        const sections = sectionsArray(this.exportForm.sections);
        if (sections.length === 0) {
          this.exportForm.error = 'Pick at least one section to include in the pack.';
          return;
        }
        const label = (this.exportForm.report_label || 'audit').trim() || 'audit';
        this.exportForm.busy = true;
        this.exportForm.error = '';
        const body = {
          tenant_id:         (this.filters.tenant_id || '').trim() || null,
          workspace_id:      (this.filters.workspace_id || '').trim() || null,
          environment:       (this.filters.environment || '').trim() || null,
          window_hours:      Math.max(1, Math.min(24 * 30, Number(this.filters.window_hours) || 72)),
          limit_per_section: Math.max(1, Math.min(1000, Number(this.filters.limit_per_section) || 100)),
          sections,
          report_label:      label,
        };
        // Strip explicit null scope fields so the backend default
        // (active scope) kicks in.
        for (const k of ['tenant_id', 'workspace_id', 'environment']) {
          if (body[k] == null) delete body[k];
        }
        const card = this.exportResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/compliance/export', body);
        this.exportForm.busy = false;
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
          window.omToasts.success(`Evidence pack "${label}" exported`);
          this.closeExportDialog();
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
          this.exportForm.error = `HTTP ${r.status}: ${r.error}`;
        }
      },

      // ----- derived (export result) -----

      exportArtifactRef() {
        const d = this.exportResult.data;
        if (!d) return null;
        return d.artifact_ref || d.pack_id || d.report_id || d.evidence_pack_id || null;
      },
    };
  };
})();
