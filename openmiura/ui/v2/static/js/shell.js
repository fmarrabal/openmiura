/**
 * Shell components — Alpine.js data factories shared by all UI v2
 * entry points.
 *
 * Each function returns an object that an HTML element registers via
 * `x-data="omShell({ ... })"`. Alpine wires reactivity around it; we
 * never call these directly.
 *
 * Conventions:
 *
 * - Public state on the returned object is fully reactive in Alpine.
 * - Private helpers are kept inside closures, not on the object.
 * - DOM reads happen in init(); subsequent state is data-driven.
 */
(function () {
  'use strict';

  const NAV_GROUPS = {
    admin: [
      {
        title: 'Operate',
        items: [
          { id: 'dashboard',  label: 'Dashboard',         icon: 'gauge' },
          { id: 'runtimes',   label: 'Runtimes',          icon: 'cpu' },
          { id: 'dispatches', label: 'Dispatches',        icon: 'send' },
          { id: 'evidence',   label: 'Evidence packs',    icon: 'shield-check' },
        ],
      },
      {
        title: 'Govern',
        items: [
          { id: 'policies',    label: 'Policies',          icon: 'scroll-text' },
          { id: 'approvals',   label: 'Approvals',         icon: 'check-circle' },
          { id: 'secrets',     label: 'Secrets',           icon: 'key' },
          { id: 'identities',  label: 'Identities & RBAC', icon: 'users' },
        ],
      },
      {
        title: 'Configure',
        items: [
          { id: 'channels',         label: 'Channels',           icon: 'plug' },
          { id: 'secrets-wizard',   label: 'Secrets wizard',     icon: 'key' },
          { id: 'workflows',        label: 'Workflows',          icon: 'workflow' },
          { id: 'system',           label: 'System & config',    icon: 'settings' },
        ],
      },
      {
        title: 'Debug',
        items: [
          { id: 'events',     label: 'Event log',          icon: 'list' },
          { id: 'tool-calls', label: 'Tool calls',         icon: 'terminal' },
        ],
      },
    ],
    science: [
      {
        title: 'Workspace',
        items: [
          { id: 'chat',        label: 'Chat with agent',   icon: 'message-circle' },
          { id: 'upload',      label: 'Upload spectrum',   icon: 'upload-cloud' },
          { id: 'review',      label: 'Review drafts',     icon: 'file-search' },
        ],
      },
      {
        title: 'Governance',
        items: [
          { id: 'approvals',   label: 'My approvals',      icon: 'check-circle' },
          { id: 'history',     label: 'My evidence',       icon: 'history' },
        ],
      },
    ],
    interview: [
      {
        title: 'Demo',
        items: [
          { id: 'overview',    label: 'Overview',          icon: 'layout-dashboard' },
          { id: 'walkthrough', label: 'Walkthrough',       icon: 'play-circle' },
          { id: 'evidence',    label: 'Evidence inspector', icon: 'shield-check' },
        ],
      },
    ],
  };

  const PROFILE_LABELS = {
    admin:     { title: 'Admin console',           tagline: 'Configure, govern, observe.' },
    science:   { title: 'Science workspace',       tagline: 'Run governed agent flows.' },
    interview: { title: 'openMiura, in 5 minutes', tagline: 'Guided demo for QA / RA reviewers.' },
  };

  /**
   * Top-level Alpine data factory.
   * @param {object} options
   * @param {'admin'|'science'|'interview'} options.profile  Which nav set to render.
   * @param {string=}  options.activeId    Sidebar item to highlight initially.
   * @param {Array=}   options.breadcrumbs Optional breadcrumb trail.
   */
  function omShell(options) {
    const profile = (options && options.profile) || 'admin';
    if (!NAV_GROUPS[profile]) {
      console.warn(`omShell: unknown profile "${profile}"; falling back to admin`);
    }
    const groups = NAV_GROUPS[profile] || NAV_GROUPS.admin;
    const meta = PROFILE_LABELS[profile] || PROFILE_LABELS.admin;

    return {
      profile,
      profileTitle: meta.title,
      profileTagline: meta.tagline,
      groups,
      activeId: (options && options.activeId) || groups[0].items[0].id,
      breadcrumbs: (options && options.breadcrumbs) || [],
      sidebarCollapsed: false,
      mobileMenuOpen: false,
      theme: (window.omTheme && window.omTheme.current()) || 'light',

      auth: window.omAuth ? window.omAuth.snapshot() : null,

      init() {
        // Reflect external theme changes (system flips, other tabs)
        document.addEventListener('om:theme', (event) => {
          this.theme = event.detail.theme;
        });
        // Mirror omAuth state so the topbar badge is reactive.
        if (window.omAuth) {
          document.addEventListener('om:auth:changed', (event) => {
            this.auth = event.detail;
          });
        }
      },

      isAuthenticated() {
        return !!(this.auth && this.auth.token && this.auth.me);
      },

      authStatusLabel() {
        const a = this.auth || {};
        if (!a.token) return 'not authenticated';
        if (a.status === 'connecting') return 'connecting…';
        if (a.status === 'error') return 'auth error';
        if (a.me) {
          const role = a.me.role || a.me.auth_mode || 'connected';
          const who = a.me.username || a.me.principal_id || a.me.user_key || '';
          return who ? `${who} · ${role}` : role;
        }
        return 'token set';
      },

      isActive(itemId) {
        return this.activeId === itemId;
      },

      setActive(itemId) {
        this.activeId = itemId;
        this.mobileMenuOpen = false;
      },

      toggleSidebar() {
        this.sidebarCollapsed = !this.sidebarCollapsed;
      },

      toggleMobileMenu() {
        this.mobileMenuOpen = !this.mobileMenuOpen;
      },

      toggleTheme() {
        if (window.omTheme) {
          window.omTheme.toggle();
        }
      },
    };
  }

  /**
   * Alpine data factory for the auth panel embedded in the topbar.
   * Drives the connect form (token | username+password), reflects
   * omAuth.state and emits no events of its own — all writes go
   * through `window.omAuth.*`.
   */
  function omAuthPanel() {
    const snap = window.omAuth
      ? window.omAuth.snapshot()
      : { baseUrl: '', mode: 'token', token: '', username: '', me: null, status: 'idle', error: '' };
    return {
      open: false,
      baseUrl: snap.baseUrl,
      mode: snap.mode,
      token: snap.token,
      username: snap.username,
      password: '',
      status: snap.status,
      error: snap.error,
      me: snap.me,
      busy: false,

      init() {
        document.addEventListener('om:auth:changed', (event) => {
          const a = event.detail || {};
          this.baseUrl = a.baseUrl;
          this.mode = a.mode;
          this.token = a.token;
          this.username = a.username;
          this.status = a.status;
          this.error = a.error;
          this.me = a.me;
        });
      },

      toggle() { this.open = !this.open; },
      close()  { this.open = false; },

      async connect() {
        if (!window.omAuth) { this.error = 'auth module not loaded'; return; }
        this.busy = true;
        window.omAuth.setBaseUrl(this.baseUrl);
        window.omAuth.setMode(this.mode);
        let ok = false;
        if (this.mode === 'token') {
          ok = await window.omAuth.connectWithToken(this.token);
        } else {
          ok = await window.omAuth.connectWithLogin(this.username, this.password);
          this.password = ''; // never keep the password in component state
        }
        this.busy = false;
        if (ok) this.open = false;
      },

      async disconnect() {
        if (!window.omAuth) return;
        this.busy = true;
        await window.omAuth.logout();
        this.busy = false;
      },
    };
  }

  window.omShell = omShell;
  window.omAuthPanel = omAuthPanel;
  window.omNavGroups = NAV_GROUPS; // exposed for tests + future debug pane
})();
