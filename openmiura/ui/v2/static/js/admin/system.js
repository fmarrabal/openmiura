/**
 * Admin System & config view — Alpine data factory.
 *
 * Drives the config-center surface (every YAML config section
 * openMiura ships with) plus the reload-assistant that decides
 * which sections can hot-reload vs. require a restart.
 *
 *   GET  /admin/config-center
 *   POST /admin/config-center/validate                      (read-modeled)
 *   POST /admin/config-center/save                          (confirmed write)
 *   GET  /admin/config-center/reload-assistant
 *   POST /admin/config-center/reload-assistant/apply        (confirmed write)
 *
 * The save and reload-apply endpoints both touch disk +
 * process state; both are wrapped by their own modal.
 *
 * Packaging endpoints (admin/phaseN/packaging/...) are
 * deliberately out of scope here — they are a build/SRE
 * surface, not a day-to-day config surface.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asSectionsList(payload) {
    if (!payload) return [];
    if (Array.isArray(payload.sections)) return payload.sections;
    if (Array.isArray(payload.items))    return payload.items;
    return [];
  }

  function sectionTone(status) {
    const s = (status && (status.state || status.status || '')) || '';
    const l = String(s).toLowerCase();
    if (l === 'configured' || l === 'ok' || l === 'ready' || l === 'valid') return 'success';
    if (l === 'incomplete' || l === 'partial' || l === 'pending') return 'warning';
    if (l === 'invalid' || l === 'error') return 'danger';
    return 'neutral';
  }

  window.adminSystem = function () {
    return {
      configCenter:  emptyCard(),
      reloadStatus:  emptyCard(),
      validateResult: emptyCard(),
      saveResult:    emptyCard(),
      reloadResult:  emptyCard(),

      showRaw: {
        configCenter:   false,
        reloadStatus:   false,
        validateResult: false,
        saveResult:     false,
        reloadResult:   false,
      },

      editor: {
        section: '',
        content: '',
      },

      saveForm: {
        reload_after_save: false,
        actor:             'admin',
        open:              false,
        busy:              false,
        error:             '',
      },

      reloadForm: {
        sections:               [],   // chosen sections
        apply_live_reload:      true,
        request_restart:        false,
        execute_restart_hook:   false,
        actor:                  'admin',
        open:                   false,
        busy:                   false,
        error:                  '',
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
        this.configCenter   = emptyCard();
        this.reloadStatus   = emptyCard();
        this.validateResult = emptyCard();
        this.saveResult     = emptyCard();
        this.reloadResult   = emptyCard();
        this.editor         = { section: '', content: '' };
        this.lastRefreshAt  = null;
      },

      async refresh() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load system config');
          return;
        }
        this.lastRefreshAt = new Date();
        await Promise.all([
          this._load('configCenter', '/admin/config-center'),
          this._load('reloadStatus', '/admin/config-center/reload-assistant'),
        ]);
        // Pre-select first section
        const items = this.sectionsList();
        if (!this.editor.section && items.length > 0) {
          this.editor.section = items[0].name || '';
          // Pre-populate content from snapshot if available
          if (items[0].raw && !this.editor.content) {
            this.editor.content = items[0].raw;
          }
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

      sectionsList() {
        return asSectionsList(this.configCenter.data);
      },

      selectedSection() {
        return this.sectionsList().find((s) => s.name === this.editor.section) || null;
      },

      sectionTone,

      selectSection(name) {
        this.editor.section = name || '';
        const sec = this.selectedSection();
        if (sec && typeof sec.raw === 'string') {
          this.editor.content = sec.raw;
        }
      },

      reloadSectionsList() {
        const d = this.reloadStatus.data;
        if (!d) return [];
        if (Array.isArray(d.sections)) return d.sections;
        if (Array.isArray(d.items)) return d.items;
        return [];
      },

      restartHookConfigured() {
        const d = this.reloadStatus.data;
        if (!d || !d.restart_hook) return null;
        return d.restart_hook.configured === true;
      },

      // ----- validate (read-modeled) -----

      async submitValidate() {
        if (!this._authed()) return;
        const section = (this.editor.section || '').trim();
        if (!section) {
          this.validateResult.state = 'error';
          this.validateResult.error = 'Pick a section before validating';
          return;
        }
        const body = {
          section,
          content: this.editor.content || '',
        };
        const card = this.validateResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/config-center/validate', body);
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

      validateValid() {
        const d = this.validateResult.data;
        if (!d) return null;
        if (typeof d.valid === 'boolean') return d.valid;
        return null;
      },

      // ----- save (confirmed write) -----

      openSaveDialog() {
        const section = (this.editor.section || '').trim();
        if (!section) {
          window.omToasts.warning('Pick a section before saving');
          return;
        }
        this.saveForm = {
          reload_after_save: false,
          actor:             'admin',
          open:              true,
          busy:              false,
          error:             '',
        };
        window.omModal.open('system-save');
      },

      closeSaveDialog() {
        this.saveForm.open = false;
        window.omModal.close('system-save');
      },

      async submitSave() {
        const section = (this.editor.section || '').trim();
        if (!section) {
          this.saveForm.error = 'Pick a section before saving';
          return;
        }
        const actor = (this.saveForm.actor || 'admin').trim() || 'admin';
        this.saveForm.busy = true;
        this.saveForm.error = '';
        const body = {
          section,
          content:           this.editor.content || '',
          reload_after_save: !!this.saveForm.reload_after_save,
          actor,
        };
        const card = this.saveResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/config-center/save', body);
        this.saveForm.busy = false;
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
          window.omToasts.success(`Section ${section} saved`);
          this.closeSaveDialog();
          await this.refresh();
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
          this.saveForm.error = `HTTP ${r.status}: ${r.error}`;
        }
      },

      saveRestartRequired() {
        const d = this.saveResult.data;
        if (!d) return null;
        return d.restart_required === true;
      },

      // ----- reload-assistant apply (confirmed write) -----

      openReloadDialog() {
        this.reloadForm = {
          sections:             [],
          apply_live_reload:    true,
          request_restart:      false,
          execute_restart_hook: false,
          actor:                'admin',
          open:                 true,
          busy:                 false,
          error:                '',
        };
        window.omModal.open('system-reload');
      },

      closeReloadDialog() {
        this.reloadForm.open = false;
        window.omModal.close('system-reload');
      },

      toggleReloadSection(name) {
        if (!name) return;
        const i = this.reloadForm.sections.indexOf(name);
        if (i === -1) this.reloadForm.sections.push(name);
        else this.reloadForm.sections.splice(i, 1);
      },

      async submitReload() {
        if (!this._authed()) return;
        if (this.reloadForm.sections.length === 0) {
          this.reloadForm.error = 'Pick at least one section to apply';
          return;
        }
        const actor = (this.reloadForm.actor || 'admin').trim() || 'admin';
        this.reloadForm.busy = true;
        this.reloadForm.error = '';
        const body = {
          sections:               this.reloadForm.sections,
          apply_live_reload:      !!this.reloadForm.apply_live_reload,
          request_restart:        !!this.reloadForm.request_restart,
          execute_restart_hook:   !!this.reloadForm.execute_restart_hook,
          actor,
        };
        const card = this.reloadResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/config-center/reload-assistant/apply', body);
        this.reloadForm.busy = false;
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
          window.omToasts.success(`Reload applied (${this.reloadForm.sections.length} section(s))`);
          this.closeReloadDialog();
          await this._load('reloadStatus', '/admin/config-center/reload-assistant');
        } else {
          card.data = null;
          card.error = `HTTP ${r.status}: ${r.error}`;
          card.raw = r.raw || JSON.stringify(r, null, 2);
          card.state = 'error';
          this.reloadForm.error = `HTTP ${r.status}: ${r.error}`;
        }
      },
    };
  };
})();
