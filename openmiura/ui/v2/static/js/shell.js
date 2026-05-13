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
          { id: 'channels',   label: 'Channels',           icon: 'plug' },
          { id: 'workflows',  label: 'Workflows',          icon: 'workflow' },
          { id: 'system',     label: 'System & config',    icon: 'settings' },
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

      init() {
        // Reflect external theme changes (system flips, other tabs)
        document.addEventListener('om:theme', (event) => {
          this.theme = event.detail.theme;
        });
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

  window.omShell = omShell;
  window.omNavGroups = NAV_GROUPS; // exposed for tests + future debug pane
})();
