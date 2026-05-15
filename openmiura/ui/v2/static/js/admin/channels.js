/**
 * Admin Channels view — Alpine data factory.
 *
 * Drives the openMiura "channels wizard" surface. The wizard
 * lets the operator inspect every registered channel (Slack,
 * Telegram, voice/SMTP/...) and update its configuration via
 * a YAML editor, behind a two-step pipeline:
 *
 *   1. validate — POST /admin/config-center/channels-wizard/validate
 *                 Read-modeled. Re-parses the candidate YAML and
 *                 returns parsed-vs-required diagnostics. Safe to
 *                 call as often as the operator wants.
 *
 *   2. save     — POST /admin/config-center/channels-wizard/save
 *                 *Confirmed write*: rewrites the on-disk YAML
 *                 for the active scope. Wrapped by a modal so a
 *                 click can't go through by accident. Optional
 *                 reload_after_save attempts a live reload — if
 *                 the channel needs a restart, the response says
 *                 so and the operator schedules it manually.
 *
 *   - snapshot  — GET  /admin/config-center/channels-wizard
 *                 Read-only inventory: every channel with a
 *                 derived configured/incomplete badge.
 *
 * Endpoints:
 *   GET  /admin/config-center/channels-wizard
 *   POST /admin/config-center/channels-wizard/validate   (read-modeled)
 *   POST /admin/config-center/channels-wizard/save       (write, confirmed)
 *
 * Per-card { state, data, error, raw } pattern mirrors B1..B5.
 */
(function () {
  'use strict';

  function emptyCard() {
    return { state: 'idle', data: null, error: null, raw: '' };
  }

  function asChannelsList(payload) {
    if (!payload) return [];
    if (Array.isArray(payload.channels)) return payload.channels;
    if (Array.isArray(payload.items))    return payload.items;
    return [];
  }

  function channelTone(status) {
    const s = (status && (status.state || status.status || '')) || '';
    const l = String(s).toLowerCase();
    if (l === 'configured' || l === 'ok' || l === 'ready') return 'success';
    if (l === 'incomplete' || l === 'partial') return 'warning';
    if (l === 'invalid' || l === 'error') return 'danger';
    return 'neutral';
  }

  window.adminChannels = function () {
    return {
      snapshot:        emptyCard(),
      validateResult:  emptyCard(),
      saveResult:      emptyCard(),

      showRaw: {
        snapshot:       false,
        validateResult: false,
        saveResult:     false,
      },

      editor: {
        channel: '',
        content: '',
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
        this.editor         = { channel: '', content: '' };
        this.lastRefreshAt  = null;
      },

      async refreshSnapshot() {
        if (!this._authed()) {
          window.omToasts.warning('Connect first to load channels');
          return;
        }
        this.lastRefreshAt = new Date();
        await this._load('snapshot', '/admin/config-center/channels-wizard');
        // Pre-populate editor.content with the current raw YAML on
        // first load so the operator can edit in place.
        if (
          this.snapshot.state === 'loaded' &&
          this.snapshot.data &&
          typeof this.snapshot.data.raw === 'string' &&
          !this.editor.content
        ) {
          this.editor.content = this.snapshot.data.raw;
        }
        // Pre-select first channel if none chosen yet.
        const items = this.channelsList();
        if (!this.editor.channel && items.length > 0) {
          this.editor.channel = items[0].name || '';
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

      // ----- derived (channels list) -----

      channelsList() {
        return asChannelsList(this.snapshot.data);
      },

      selectedChannel() {
        return this.channelsList().find((c) => c.name === this.editor.channel) || null;
      },

      channelTone,

      selectChannel(name) {
        this.editor.channel = name || '';
      },

      // ----- validate (read-modeled) -----

      async submitValidate() {
        if (!this._authed()) return;
        const channel = (this.editor.channel || '').trim();
        if (!channel) {
          this.validateResult.state = 'error';
          this.validateResult.error = 'Pick a channel before validating';
          return;
        }
        const body = {
          channel,
          content: this.editor.content || '',
        };
        const card = this.validateResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/config-center/channels-wizard/validate', body);
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
        if (d.channel_status && typeof d.channel_status.configured === 'boolean') {
          return d.channel_status.configured;
        }
        if (typeof d.configured === 'boolean') return d.configured;
        return null;
      },

      // ----- save (confirmed write) -----

      openSaveDialog() {
        const channel = (this.editor.channel || '').trim();
        if (!channel) {
          window.omToasts.warning('Pick a channel before saving');
          return;
        }
        this.saveForm = {
          reload_after_save: false,
          actor:             'admin',
          open:              true,
          busy:              false,
          error:             '',
        };
        window.omModal.open('channels-save');
      },

      closeSaveDialog() {
        this.saveForm.open = false;
        window.omModal.close('channels-save');
      },

      async submitSave() {
        const channel = (this.editor.channel || '').trim();
        if (!channel) {
          this.saveForm.error = 'Pick a channel before saving';
          return;
        }
        const actor = (this.saveForm.actor || 'admin').trim() || 'admin';
        this.saveForm.busy = true;
        this.saveForm.error = '';
        const body = {
          channel,
          content: this.editor.content || '',
          reload_after_save: !!this.saveForm.reload_after_save,
          actor,
        };
        const card = this.saveResult;
        card.state = 'loading';
        card.error = null;
        const r = await window.omApi.post('/admin/config-center/channels-wizard/save', body);
        this.saveForm.busy = false;
        if (r.ok) {
          card.data = r.data;
          card.raw = JSON.stringify(r.data, null, 2);
          card.state = 'loaded';
          window.omToasts.success(`Channel ${channel} saved`);
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
