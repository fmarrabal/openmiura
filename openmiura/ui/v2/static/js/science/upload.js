/**
 * Science Upload view — Alpine data factory.
 *
 * Lets the operator stage files (NMR spectra, mass-spec runs,
 * raw instrument exports, ...) and reference them in a chat
 * turn with the agent.
 *
 * Design constraint: openMiura currently has no dedicated
 * file-upload endpoint exposed in the public HTTP surface.
 * The honest UI here:
 *
 *   1. Captures each file in the browser memory + persists a
 *      small metadata record under
 *      `openmiura.v2.science.uploads`. The raw bytes are NOT
 *      persisted (localStorage has a ~5 MB quota and we do not
 *      want to spill spectra into the operator's profile).
 *
 *   2. Computes a SHA-256 of the file via Web Crypto so the
 *      operator and the agent can agree on file identity later
 *      without needing the bytes round-trip.
 *
 *   3. Offers a "Discuss with agent" action that POSTs to
 *      /http/message with a chat prompt of the form
 *      "I just staged file <name> (<size>, sha256=<hash>).
 *       Please process it." and embeds the metadata under
 *      message.metadata.staged_file so a future backend
 *      ingest path can pick it up.
 *
 *   4. Files can be removed from the staging area; future
 *      C3/C4 PRs can list staged files as part of the review
 *      and approval flows.
 *
 * Endpoints:
 *   POST /http/message       (same chat surface as C1)
 *
 * localStorage:
 *   openmiura.v2.science.uploads   (metadata-only list)
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'openmiura.v2.science.uploads';
  const MAX_STAGED  = 20;
  const MAX_FILE_BYTES = 50 * 1024 * 1024; // 50 MB hard cap for staging

  function nowIso() { return new Date().toISOString(); }

  function readStored() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) { return []; }
  }

  function writeStored(value) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value || []));
    } catch (_) { /* quota — ignore */ }
  }

  function formatBytes(n) {
    if (typeof n !== 'number' || !isFinite(n) || n < 0) return '—';
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
    if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MiB`;
    return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
  }

  async function sha256Hex(arrayBuffer) {
    if (!(window.crypto && window.crypto.subtle && window.crypto.subtle.digest)) {
      return null;
    }
    const digest = await window.crypto.subtle.digest('SHA-256', arrayBuffer);
    const bytes = new Uint8Array(digest);
    let hex = '';
    for (let i = 0; i < bytes.length; i++) {
      hex += bytes[i].toString(16).padStart(2, '0');
    }
    return hex;
  }

  function userIdFromAuth() {
    const me = window.omAuth && window.omAuth.state.me;
    if (!me) return null;
    return me.principal_id || me.username || me.user_key || null;
  }

  window.scienceUpload = function () {
    return {
      staged: [],
      dragging: false,
      progress: { busy: false, name: '', step: '' },
      error: '',
      sendingId: null,
      sendError: '',

      init() {
        this.staged = readStored();
        document.addEventListener('om:auth:logged-out', () => this._authLost());
      },

      _authLost() {
        // Keep the staged metadata across logout — it's
        // already in the operator's own browser.
        this.error = '';
      },

      authenticated() {
        return !!(window.omAuth && window.omAuth.state.token && userIdFromAuth());
      },

      // ----- staging -----

      onDragOver(ev) {
        if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
        this.dragging = true;
      },
      onDragLeave() { this.dragging = false; },

      async onDrop(ev) {
        if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
        this.dragging = false;
        const dt = ev && ev.dataTransfer;
        const files = (dt && dt.files) ? Array.from(dt.files) : [];
        if (files.length === 0) return;
        await this._stageFiles(files);
      },

      async onFileInput(ev) {
        const input = ev && ev.target;
        const files = (input && input.files) ? Array.from(input.files) : [];
        if (files.length === 0) return;
        await this._stageFiles(files);
        if (input) input.value = '';
      },

      async _stageFiles(files) {
        this.error = '';
        for (const f of files) {
          if (!f) continue;
          if (this.staged.length >= MAX_STAGED) {
            this.error = `Staging area full (max ${MAX_STAGED} files). Remove some first.`;
            break;
          }
          if (f.size > MAX_FILE_BYTES) {
            this.error = `${f.name} exceeds the ${formatBytes(MAX_FILE_BYTES)} staging cap.`;
            continue;
          }
          await this._stageOne(f);
        }
      },

      async _stageOne(file) {
        this.progress.busy = true;
        this.progress.name = file.name;
        this.progress.step = 'hashing';
        let sha = null;
        try {
          const buf = await file.arrayBuffer();
          sha = await sha256Hex(buf);
        } catch (e) {
          this.progress.step = 'error';
          this.error = `Failed to hash ${file.name}: ${e && e.message || e}`;
          this.progress.busy = false;
          return;
        }
        const entry = {
          id:        `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          name:      file.name,
          size:      file.size,
          mime:      file.type || 'application/octet-stream',
          sha256:    sha,
          ts:        nowIso(),
          discussed: false,
        };
        this.staged.unshift(entry);
        writeStored(this.staged);
        this.progress.busy = false;
        this.progress.step = '';
        this.progress.name = '';
      },

      removeStaged(id) {
        this.staged = this.staged.filter((s) => s.id !== id);
        writeStored(this.staged);
      },

      clearAll() {
        this.staged = [];
        writeStored([]);
      },

      // ----- send a discussion turn -----

      async discuss(id) {
        if (!this.authenticated()) {
          window.omToasts.warning('Connect first to discuss with the agent');
          return;
        }
        const entry = this.staged.find((s) => s.id === id);
        if (!entry) return;
        this.sendingId = id;
        this.sendError = '';
        const userId = userIdFromAuth();
        const promptText =
          `I just staged file "${entry.name}" ` +
          `(${formatBytes(entry.size)}, type=${entry.mime}, ` +
          `sha256=${entry.sha256 || 'unavailable'}).\n` +
          `Please review it and draft what you'd do next.`;
        const body = {
          channel: 'http',
          user_id: userId,
          text:    promptText,
          metadata: {
            staged_file: {
              name:   entry.name,
              size:   entry.size,
              mime:   entry.mime,
              sha256: entry.sha256,
              ts:     entry.ts,
            },
          },
        };
        // Re-use the chat session id from C1 if present so the
        // discussion lands in the same conversation thread.
        try {
          const sid = window.localStorage.getItem('openmiura.v2.science.session_id');
          if (sid) body.session_id = JSON.parse(sid);
        } catch (_) { /* ignore */ }
        const r = await window.omApi.post('/http/message', body);
        this.sendingId = null;
        if (r.ok) {
          window.omToasts.success(`Sent "${entry.name}" to the agent`);
          entry.discussed = true;
          writeStored(this.staged);
        } else {
          this.sendError = `HTTP ${r.status}: ${r.error}`;
        }
      },

      // ----- derived -----

      formatBytes,
      isEmpty()  { return this.staged.length === 0; },
      stagedCount() { return this.staged.length; },

      // testing hook
      _storageKey() { return STORAGE_KEY; },
    };
  };
})();
