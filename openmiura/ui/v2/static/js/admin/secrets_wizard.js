/**
 * Admin Secrets wizard view — Alpine data factory.
 *
 * Sibling of the channels wizard B6. Drives the
 * config-center secrets wizard: read the snapshot, edit a
 * profile's YAML, validate it (read-modeled), save it
 * (confirmed write to disk).
 *
 *   GET  /admin/config-center/secrets-wizard?env_prefix=...
 *   POST /admin/config-center/secrets-wizard/validate     (read-modeled)
 *   POST /admin/config-center/secrets-wizard/save         (write, confirmed)
 *
 * The save path mutates dotenv profiles on disk; it is
 * deliberately separated from the secret-governance view
 * (B4) so an operator who only wants to inspect denied
 * events doesn't see the on-disk edit surface.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asProfilesList(payload) {
    if (!payload) return [];
    if (Array.isArray(payload.profiles)) return payload.profiles;
    if (Array.isArray(payload.items))    return payload.items;
    return [];
  }

  function profileTone(status) {
    const s = (status && (status.state || status.status || '')) || '';
    const l = String(s).toLowerCase();
    if (l === 'configured' || l === 'ok' || l === 'ready') return 'success';
    if (l === 'incomplete' || l === 'partial') return 'warning';
    if (l === 'invalid' || l === 'error') return 'danger';
    return 'neutral';
  }

  window.adminSecretsWizard = function () {
    return {
      snapshot:       emptyCard(),
      validateResult: emptyCard(),
      saveResult:     emptyCard(),

      showRaw: {
        snapshot:       false,
        validateResult: false,
        saveResult:     false,
      },

      editor: {
        profile:    '',
        content:    '',
        env_prefix: 'OPENMIURA',
      },

      saveForm: {
        reload_after_save: false,
        actor:             'admin',
        open:              false,
        busy:              false,
        error:             '',
      },

      lastRefreshAt: null,

      init() {
        if (this._authed()) this.refreshSnapshot();
        document.addEventListener('om:auth:logged-in',  () => this.refreshSnapshot());
        document.addEventListener('om:auth:logged-out', () => this._clear());
      },

      _authed() {
        return !!(window.omAuth && window.omAuth.state.token);
      },

      _clear() {
        this.snapshot       = emptyCard();
        this.validateResult = emptyCard();
        this.saveResult     = emptyCard();
        this.editor         = { profile: '', content: '', env_prefix: 'OPENMIURA' };
        this.lastRefreshAt  = null;
      },

      async refreshSnapshot() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load secrets wizard');
          return;
        }
        this.lastRefreshAt = new Date();
        const prefix = (this.editor.env_prefix || 'OPENMIURA').trim() || 'OPENMIURA';
        await this._load('snapshot', `/admin/config-center/secrets-wizard?env_prefix=${encodeURIComponent(prefix)}`);
        // Pre-populate editor.content with raw YAML if blank.
        if (
          this.snapshot.state === 'loaded' &&
          this.snapshot.data &&
          typeof this.snapshot.data.raw === 'string' &&
          !this.editor.content
        ) {
          this.editor.content = this.snapshot.data.raw;
        }
        const items = this.profilesList();
        if (!this.editor.profile && items.length > 0) {
          this.editor.profile = items[0].name || '';
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

      profilesList() {
        return asProfilesList(this.snapshot.data);
      },

      selectedProfile() {
        return this.profilesList().find((p) => p.name === this.editor.profile) || null;
      },

      profileTone,

      selectProfile(name) {
        this.editor.profile = name || '';
      },

      async submitValidate() {
        if (!this._authed()) return;
        const profile = (this.editor.profile || '').trim();
        if (!profile) {
          this.validateResult.state = 'error';
          this.validateResult.error = 'Pick a profile before validating';
          return;
        }
        const body = {
          profile,
          content:    this.editor.content || '',
          env_prefix: (this.editor.env_prefix || 'OPENMIURA').trim() || 'OPENMIURA',
        };
        const card = this.validateResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/config-center/secrets-wizard/validate', body);
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

      validateConfigured() {
        const d = this.validateResult.data;
        if (!d) return null;
        if (d.profile_status && typeof d.profile_status.configured === 'boolean') {
          return d.profile_status.configured;
        }
        if (typeof d.configured === 'boolean') return d.configured;
        return null;
      },

      openSaveDialog() {
        const profile = (this.editor.profile || '').trim();
        if (!profile) {
          window.omToasts.warning('Pick a profile before saving');
          return;
        }
        this.saveForm = {
          reload_after_save: false,
          actor:             'admin',
          open:              true,
          busy:              false,
          error:             '',
        };
        window.omModal.open('secrets-wizard-save');
      },

      closeSaveDialog() {
        this.saveForm.open = false;
        window.omModal.close('secrets-wizard-save');
      },

      async submitSave() {
        const profile = (this.editor.profile || '').trim();
        if (!profile) {
          this.saveForm.error = 'Pick a profile before saving';
          return;
        }
        const actor = (this.saveForm.actor || 'admin').trim() || 'admin';
        this.saveForm.busy = true;
        this.saveForm.error = '';
        const body = {
          profile,
          content:           this.editor.content || '',
          env_prefix:        (this.editor.env_prefix || 'OPENMIURA').trim() || 'OPENMIURA',
          reload_after_save: !!this.saveForm.reload_after_save,
          actor,
        };
        const card = this.saveResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/config-center/secrets-wizard/save', body);
        this.saveForm.busy = false;
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
          window.omToasts.success(`Profile ${profile} saved`);
          this.closeSaveDialog();
          await this.refreshSnapshot();
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
    };
  };
})();
