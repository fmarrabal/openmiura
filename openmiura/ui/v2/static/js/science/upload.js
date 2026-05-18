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
      uploadingId: null,
      uploadError: '',

      // Transient — only valid for files staged in this browser
      // session. After a hard refresh the metadata in `staged`
      // is still there but the actual File objects are gone, so
      // entries that haven't been uploaded yet show "stale" and
      // the upload button is disabled.
      _files: {},  // { entryId: File }

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
          uploaded:  false,
          server_upload_id: null,
        };
        this.staged.unshift(entry);
        this._files[entry.id] = file;
        writeStored(this.staged);
        this.progress.busy = false;
        this.progress.step = '';
        this.progress.name = '';
      },

      removeStaged(id) {
        this.staged = this.staged.filter((s) => s.id !== id);
        delete this._files[id];
        writeStored(this.staged);
      },

      clearAll() {
        this.staged = [];
        this._files = {};
        writeStored([]);
      },

      hasFileInMemory(id) {
        return !!this._files[id];
      },

      // ----- G4: NMR spectrum preview -----

      previewId: null,
      previewBusy: false,
      previewSvg: '',
      previewMeta: null,
      previewError: '',

      looksLikeSpectrum(entry) {
        if (!entry) return false;
        const name = (entry.name || '').toLowerCase();
        if (name.endsWith('.jdx') || name.endsWith('.dx') ||
            name.endsWith('.jcamp') || name.endsWith('.jcm')) return true;
        // H2.2: also accept CSV / XY plain text. Filter by
        // a few heuristic suffixes (.csv, .tsv, .xy, .txt
        // when paired with an "nmr" hint in the filename or
        // the JCAMP mime).
        if (name.endsWith('.csv') || name.endsWith('.tsv') ||
            name.endsWith('.xy')) return true;
        if (name.endsWith('.txt') && (name.indexOf('nmr') !== -1 ||
                                       name.indexOf('spec') !== -1)) {
          return true;
        }
        return (entry.mime || '').toLowerCase().includes('jcamp');
      },

      async openPreview(id) {
        if (!window.scienceNmr) {
          this.previewError = 'NMR viewer module not loaded.';
          return;
        }
        const entry = this.staged.find((s) => s.id === id);
        if (!entry) return;
        this.previewId = id;
        this.previewBusy = true;
        this.previewError = '';
        this.previewSvg = '';
        this.previewMeta = null;
        window.omModal.open('upload-preview');

        let text = '';
        // Prefer the in-memory file (zero round-trip). Fall
        // back to the server upload when only the metadata
        // survived a refresh.
        const file = this._files[id];
        if (file) {
          try {
            text = await file.text();
          } catch (e) {
            this.previewError = `Failed to read file: ${e && e.message || e}`;
            this.previewBusy = false;
            return;
          }
        } else if (entry.uploaded && entry.server_upload_id) {
          // Fetch the bytes back from /science/uploads/{id}.
          // We use omApi.request directly so the response is
          // returned as text rather than parsed as JSON.
          const url = `/science/uploads/${encodeURIComponent(entry.server_upload_id)}`;
          const r = await window.omApi.get(url);
          if (!r.ok) {
            this.previewError = `Fetch failed: HTTP ${r.status}: ${r.error}`;
            this.previewBusy = false;
            return;
          }
          // omApi.get returns the parsed JSON; for binary it
          // falls through to `data: { raw }`. Use `r.raw` here.
          text = r.raw || '';
          if (!text && r.data && typeof r.data.raw === 'string') {
            text = r.data.raw;
          }
        } else {
          this.previewError = (
            'File bytes not available — upload it first or re-drop ' +
            'the file in this browser session.'
          );
          this.previewBusy = false;
          return;
        }

        // H2.2: auto-detect format (JCAMP-DX or CSV/XY).
        const parsed = window.scienceNmr.parseSpectrum
          ? window.scienceNmr.parseSpectrum(text)
          : window.scienceNmr.parseJcampDx(text);
        if (!parsed.ok) {
          this.previewError = parsed.error || 'Parse failed.';
          this.previewBusy = false;
          return;
        }
        this.previewMeta = {
          title:      parsed.title,
          dataType:   parsed.dataType,
          xunits:     parsed.xunits,
          yunits:     parsed.yunits,
          firstx:     parsed.firstx,
          lastx:      parsed.lastx,
          npoints:    parsed.points.length,
          xydataKind: parsed.xydataKind,
          format:     parsed.format || 'JCAMP-DX',
          vendor_hint: parsed.vendor_hint || null,
        };
        this.previewSvg = window.scienceNmr.renderSvg(parsed);
        this.previewBusy = false;
      },

      closePreview() {
        this.previewId = null;
        this.previewSvg = '';
        this.previewMeta = null;
        this.previewError = '';
        window.omModal.close('upload-preview');
      },

      // ----- upload to /science/uploads (real server-side persist) -----

      async uploadToServer(id) {
        if (!this.authenticated()) {
          window.omToasts.warning('Connect first to upload');
          return;
        }
        const entry = this.staged.find((s) => s.id === id);
        if (!entry) return;
        if (entry.uploaded) {
          window.omToasts.info('Already uploaded');
          return;
        }
        const file = this._files[id];
        if (!file) {
          this.uploadError = (
            'File bytes not available — this entry was staged in a ' +
            'previous browser session. Re-drop the file to upload.'
          );
          return;
        }
        this.uploadingId = id;
        this.uploadError = '';
        const userId = userIdFromAuth();
        const fd = new FormData();
        fd.append('file', file, entry.name);
        fd.append('user_id', userId);
        // Tie the upload to the current chat session if one
        // exists, so a future audit query joining sessions ×
        // uploads has a key to use.
        try {
          const sid = window.localStorage.getItem('openmiura.v2.science.session_id');
          if (sid) fd.append('session_id', JSON.parse(sid));
        } catch (_) { /* ignore */ }
        // FormData → omApi.post leaves Content-Type unset so
        // the browser builds the multipart boundary itself.
        const r = await window.omApi.post('/science/uploads', fd);
        this.uploadingId = null;
        if (r.ok && r.data) {
          entry.uploaded = true;
          entry.server_upload_id = r.data.upload_id || null;
          // Sanity check: server-side sha256 must match what
          // we computed locally. If they disagree, surface a
          // warning — the bytes might have been mangled in
          // transit.
          if (r.data.sha256 && entry.sha256 && r.data.sha256 !== entry.sha256) {
            this.uploadError = (
              `sha256 mismatch for ${entry.name}: ` +
              `client=${entry.sha256.slice(0, 12)}… ` +
              `server=${r.data.sha256.slice(0, 12)}…`
            );
            entry.uploaded = false;
          }
          writeStored(this.staged);
          if (!this.uploadError) {
            window.omToasts.success(`Uploaded "${entry.name}"`);
          }
        } else {
          this.uploadError = `HTTP ${r.status}: ${r.error}`;
        }
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
        const stagedMeta = {
          name:   entry.name,
          size:   entry.size,
          mime:   entry.mime,
          sha256: entry.sha256,
          ts:     entry.ts,
        };
        // If the entry has been uploaded server-side, attach
        // the server upload id so the agent can call back into
        // /science/uploads/{id} to fetch the bytes.
        if (entry.uploaded && entry.server_upload_id) {
          stagedMeta.server_upload_id = entry.server_upload_id;
        }
        const body = {
          channel: 'http',
          user_id: userId,
          text:    promptText,
          metadata: { staged_file: stagedMeta },
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
