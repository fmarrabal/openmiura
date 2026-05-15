/**
 * Interview demo — Alpine data factory.
 *
 * Exposes three factories used by the three sidebar views of
 * the /ui/v2/interview.html page:
 *
 *   - interviewOverview()    drives the narrative entry page
 *   - interviewWalkthrough() drives the step-by-step demo
 *   - interviewEvidence()    drives the evidence-pack inspector
 *
 * Unlike admin / science, this profile makes **no backend
 * calls**. Every artefact (sessions, signatures, audit lines,
 * approvals) is synthetic and hardcoded here. The goal is to
 * give a QA / RA reviewer five minutes of context without
 * needing a running broker or a populated database.
 *
 * The samples are kept honest: every record matches the real
 * shape of what the corresponding live endpoint would return
 * (per the schemas in admin._models). A reviewer who later
 * looks at /admin/compliance/summary or
 * /admin/operator/overview should recognise the structure.
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------
  // Synthetic dataset (shared across the three factories).
  // The cast: a single canonical demo session by user "curro" on
  // tenant "ual-nmr" doing an NMR spectrum review.
  // ------------------------------------------------------------------

  const DEMO_TENANT      = 'ual-nmr';
  const DEMO_WORKSPACE   = 'spectroscopy-lab';
  const DEMO_ENVIRONMENT = 'production';
  const DEMO_PRINCIPAL   = 'curro@ual.es';
  const DEMO_SESSION_ID  = 'sess_DEMO_0001-aabbccdd';

  const STEPS = [
    {
      id:    'login',
      title: 'A scientist authenticates',
      lede:  'Curro signs in through the broker. The principal id resolves to the science role on the UAL NMR tenant. Every subsequent call inherits that scope.',
      detail: [
        'channel: http',
        'tenant_id: ' + DEMO_TENANT,
        'workspace_id: ' + DEMO_WORKSPACE,
        'environment: ' + DEMO_ENVIRONMENT,
        'principal_id: ' + DEMO_PRINCIPAL,
        'role: science',
      ],
    },
    {
      id:    'upload',
      title: 'Spectrum file is staged',
      lede:  'Curro drags a Bruker NMR file (.zip, 12.3 MiB) into the staging area. The browser computes a SHA-256; the bytes themselves never leave the operator\'s machine.',
      detail: [
        'name: 2024-09-12-pent-2-ol.zip',
        'mime: application/zip',
        'size: 12_897_244',
        'sha256: 8f1b…d3e0   (truncated)',
      ],
    },
    {
      id:    'agent',
      title: 'Agent receives a chat turn',
      lede:  'Curro asks: "Process the spectrum I just staged and draft an assignment". The chat turn lands on POST /http/message with the file metadata under message.metadata.staged_file. The agent picks a tool — read_spectrum — to do the parse.',
      detail: [
        'POST /http/message',
        'session_id: ' + DEMO_SESSION_ID,
        'agent_id: openmiura.science',
        'tool_name: read_spectrum',
      ],
    },
    {
      id:    'policy',
      title: 'Policy decides',
      lede:  'Before the tool actually runs, the policy engine evaluates (scope=tool, resource_name=read_spectrum, role=science). The decision lands on the audit trail.',
      detail: [
        'scope: tool',
        'resource_name: read_spectrum',
        'action: use',
        'decision: allow',
        'reason: tool allowed for role=science in this scope',
      ],
    },
    {
      id:    'approval',
      title: 'A write requires approval',
      lede:  'The agent drafts the assignment and tries to commit it as the canonical version of the spectrum metadata. That action is gated. A pending approval lands in My approvals.',
      detail: [
        'kind: approval',
        'status: pending',
        'approval_id: appr_DEMO_004f',
        'requested_action: commit_assignment',
        'agent_id: openmiura.science',
      ],
    },
    {
      id:    'evidence',
      title: 'Audit trail + evidence pack',
      lede:  'Every step above is on the audit trail. A reviewer can pull a compliance summary for the last 72 h and export a signed evidence pack. The pack lists every decision the policy made, with the verbatim payload.',
      detail: [
        'GET /admin/compliance/summary?window_hours=72',
        'POST /admin/compliance/export',
        'report_label: nmr-review-2024-09',
        'artifact_ref: ep_DEMO_0fa2-…',
        'sections: overview · security · approvals · tool_calls · sessions',
      ],
    },
  ];

  const SAMPLE_PACK = {
    artifact_ref: 'ep_DEMO_0fa2-aabbccdd-eeff-1122-3344-556677889900',
    report_label: 'nmr-review-2024-09',
    generated_at: '2024-09-12T17:42:18Z',
    actor:        DEMO_PRINCIPAL,
    scope: {
      tenant_id:    DEMO_TENANT,
      workspace_id: DEMO_WORKSPACE,
      environment:  DEMO_ENVIRONMENT,
    },
    sections: {
      overview: {
        count:        6,
        window_hours: 72,
        session_id:   DEMO_SESSION_ID,
      },
      security: {
        count: 0,
        items: [],
      },
      approvals: {
        count: 1,
        items: [
          {
            approval_id: 'appr_DEMO_004f',
            requested_action: 'commit_assignment',
            status: 'approved',
            actor:  DEMO_PRINCIPAL,
            reason: 'spectrum matches reference (pent-2-ol); double-checked peak list',
            ts:     '2024-09-12T17:39:02Z',
          },
        ],
      },
      tool_calls: {
        count: 2,
        items: [
          { tool_name: 'read_spectrum', decision: 'allow', ts: '2024-09-12T17:38:11Z' },
          { tool_name: 'draft_assignment', decision: 'allow', ts: '2024-09-12T17:38:25Z' },
        ],
      },
      sessions: {
        count: 1,
        items: [
          {
            session_id: DEMO_SESSION_ID,
            agent_id:   'openmiura.science',
            started_at: '2024-09-12T17:35:00Z',
            principal:  DEMO_PRINCIPAL,
          },
        ],
      },
    },
    signature: {
      algorithm:   'ed25519',
      public_key:  'DEMO_KEY-7f9c…',
      signed_at:   '2024-09-12T17:42:18Z',
      digest_sha256: '4af1…920c',
    },
  };

  // ------------------------------------------------------------------
  // Factory: Overview
  // ------------------------------------------------------------------

  window.interviewOverview = function () {
    return {
      // Each pillar is initially collapsed except the first.
      pillars: [
        {
          id:   'plane',
          icon: 'workflow',
          title: 'Governance plane for LLM agents',
          summary:
            'openMiura sits between an LLM agent and the systems it touches (Slack, Telegram, file stores, ...). It does not run the agent — it audits, gates and signs every action the agent takes.',
          open: true,
        },
        {
          id:   'policy',
          icon: 'scroll-text',
          title: 'Policy-first, not allowlist-first',
          summary:
            'Every tool call, every secret read, every channel message resolves a policy decision before it happens. The decision is recorded as part of the audit trail along with the inputs that produced it — auditable years later.',
          open: false,
        },
        {
          id:   'evidence',
          icon: 'shield-check',
          title: 'Evidence as a first-class output',
          summary:
            'For each session the platform produces a downloadable evidence pack: a digitally signed bundle of decisions, tool calls, approvals and the configuration in force at the time. Match this to ALCOA+ / 21 CFR Part 11 review.',
          open: false,
        },
        {
          id:   'scope',
          icon: 'users',
          title: 'Scope = tenant + workspace + environment',
          summary:
            'No global "user has admin rights" check. A principal is granted a role within a (tenant, workspace, environment) scope. Roles do not promote across scopes — the audit trail is segmented along the same axes.',
          open: false,
        },
      ],
      togglePillar(id) {
        const p = this.pillars.find((x) => x.id === id);
        if (p) p.open = !p.open;
      },
    };
  };

  // ------------------------------------------------------------------
  // Factory: Walkthrough
  // ------------------------------------------------------------------

  window.interviewWalkthrough = function () {
    return {
      steps: STEPS,
      currentIdx: 0,
      autoplay: false,
      _timer: null,

      init() {
        document.addEventListener('keydown', (e) => {
          // Arrow keys move through steps when the walkthrough is the
          // active view — bound on the window because Alpine inputs
          // would intercept otherwise. We test the activeId via the
          // closest x-data shell so a typing-in-textarea-elsewhere
          // doesn't accidentally page through.
          if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
          if (e.key === 'ArrowRight') this.next();
          else if (e.key === 'ArrowLeft') this.prev();
        });
      },
      destroy() {
        this._stopTimer();
      },
      currentStep()  { return this.steps[this.currentIdx] || null; },
      progress()     { return Math.round(((this.currentIdx + 1) / this.steps.length) * 100); },
      isFirst()      { return this.currentIdx === 0; },
      isLast()       { return this.currentIdx === this.steps.length - 1; },
      next()         { if (!this.isLast())  this.currentIdx += 1; },
      prev()         { if (!this.isFirst()) this.currentIdx -= 1; },
      goto(idx)      {
        const i = Number(idx);
        if (Number.isInteger(i) && i >= 0 && i < this.steps.length) this.currentIdx = i;
      },
      toggleAutoplay() {
        this.autoplay = !this.autoplay;
        if (this.autoplay) this._startTimer();
        else this._stopTimer();
      },
      _startTimer() {
        this._stopTimer();
        this._timer = setInterval(() => {
          if (this.isLast()) {
            this._stopTimer();
            this.autoplay = false;
            return;
          }
          this.next();
        }, 5000);
      },
      _stopTimer() {
        if (this._timer) {
          clearInterval(this._timer);
          this._timer = null;
        }
      },
    };
  };

  // ------------------------------------------------------------------
  // Factory: Evidence inspector
  // ------------------------------------------------------------------

  window.interviewEvidence = function () {
    return {
      pack: SAMPLE_PACK,
      showRaw: false,
      expandedSections: { overview: true, approvals: true, tool_calls: false, sessions: false, security: false },
      toggleSection(key) {
        this.expandedSections[key] = !this.expandedSections[key];
      },
      sectionKeys() {
        return Object.keys(this.pack.sections || {});
      },
      sectionCount(key) {
        const s = (this.pack.sections || {})[key] || {};
        if (typeof s.count === 'number') return s.count;
        if (Array.isArray(s.items)) return s.items.length;
        return null;
      },
      sectionItems(key) {
        const s = (this.pack.sections || {})[key] || {};
        return Array.isArray(s.items) ? s.items : [];
      },
      rawJson() {
        return JSON.stringify(this.pack, null, 2);
      },
    };
  };
})();
