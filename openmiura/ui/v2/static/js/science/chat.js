/**
 * Science Chat view — Alpine data factory.
 *
 * First functional surface of the Science workspace. Drives a
 * conversational thread with the configured agent over the
 * stable HTTP message endpoint:
 *
 *   POST /http/message
 *       in:  { channel: "http", user_id, text, session_id?, metadata }
 *       out: { channel, user_id, session_id, agent_id, text, metadata }
 *
 * Design notes:
 *
 *   - State is **client-side**: messages live in a list under
 *     localStorage so a hard refresh keeps the thread. Each
 *     entry carries { role: 'user'|'agent'|'system',
 *     text, ts, raw, error? }.
 *
 *   - The session_id is persisted under
 *     `openmiura.v2.science.session_id` so successive turns
 *     reach the same conversation. A reset wipes both the
 *     transcript and the session id.
 *
 *   - The user_id comes from omAuth.state.me (preferred:
 *     principal_id, fallback: username / user_key). If the
 *     operator is not authenticated, the view shows a
 *     "connect first" empty state.
 *
 *   - The agent endpoint can take seconds. The composer
 *     disables the textarea + button and surfaces a "thinking"
 *     placeholder turn so the operator sees feedback.
 *
 * Phase D (interview demo) reuses the same factory shape.
 */
(function () {
  'use strict';

  const STORAGE_KEY_MESSAGES = 'openmiura.v2.science.messages';
  const STORAGE_KEY_SESSION  = 'openmiura.v2.science.session_id';
  const MAX_PERSISTED_TURNS  = 200; // safety: don't blow up localStorage

  function nowIso() {
    return new Date().toISOString();
  }

  function readStored(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      return parsed == null ? fallback : parsed;
    } catch (_) {
      return fallback;
    }
  }

  function writeStored(key, value) {
    try {
      if (value == null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, JSON.stringify(value));
    } catch (_) {
      /* quota / sandbox — ignore */
    }
  }

  function userIdFromAuth() {
    const me = window.omAuth && window.omAuth.state.me;
    if (!me) return null;
    return me.principal_id || me.username || me.user_key || null;
  }

  window.scienceChat = function () {
    return {
      messages: [],
      composer: { text: '', busy: false },
      sessionId: '',
      error: '',
      showRaw: false,
      lastTurnRaw: '',

      init() {
        this.messages = readStored(STORAGE_KEY_MESSAGES, []);
        this.sessionId = readStored(STORAGE_KEY_SESSION, '') || '';
        document.addEventListener('om:auth:logged-out', () => this._authLost());
      },

      _authLost() {
        // Don't drop the transcript — the operator may want to
        // re-authenticate and continue. Just clear any pending
        // state and surface a system marker.
        this.composer.busy = false;
        this.error = '';
        this.messages.push({
          role:  'system',
          text:  'Session ended (logged out). Reconnect to continue.',
          ts:    nowIso(),
        });
        this._persist();
      },

      authenticated() {
        return !!(window.omAuth && window.omAuth.state.token && userIdFromAuth());
      },

      // Streaming on by default — the SSE endpoint pseudo-
      // streams the response (chunks the final text into
      // pieces with small inter-chunk delays). When the LLM
      // clients gain native ``chat_stream``, the same client
      // code wins real token streaming for free.
      streamingEnabled: true,
      _streamAbort: null,

      // ----- send -----

      async send() {
        const text = (this.composer.text || '').trim();
        if (!text) return;
        if (!this.authenticated()) {
          window.omToasts.warning('Connect first to chat with the agent');
          return;
        }
        const userId = userIdFromAuth();
        // append user turn locally
        this.messages.push({
          role: 'user',
          text,
          ts:   nowIso(),
        });
        this.composer.text = '';
        this.composer.busy = true;
        this.error = '';
        this._persist();

        const body = {
          channel:    'http',
          user_id:    userId,
          text,
        };
        if (this.sessionId) body.session_id = this.sessionId;

        if (this.streamingEnabled) {
          await this._sendStreaming(body);
        } else {
          await this._sendOneShot(body);
        }
      },

      async _sendOneShot(body) {
        const r = await window.omApi.post('/http/message', body);
        this.composer.busy = false;
        if (r.ok && r.data) {
          if (r.data.session_id) {
            this.sessionId = r.data.session_id;
            writeStored(STORAGE_KEY_SESSION, this.sessionId);
          }
          this.messages.push({
            role:     'agent',
            text:     r.data.text || '(empty response)',
            ts:       nowIso(),
            agent_id: r.data.agent_id || null,
            raw:      JSON.stringify(r.data, null, 2),
          });
          this.lastTurnRaw = JSON.stringify(r.data, null, 2);
        } else {
          this.error = `HTTP ${r.status}: ${r.error}`;
          this.messages.push({
            role:  'system',
            text:  `Agent error: ${r.error || 'unknown'}`,
            ts:    nowIso(),
            error: true,
            raw:   r.raw || JSON.stringify(r, null, 2),
          });
          this.lastTurnRaw = r.raw || JSON.stringify(r, null, 2);
        }
        this._persist();
      },

      async _sendStreaming(body) {
        // EventSource only supports GET. We need POST + SSE,
        // so we do it with fetch + ReadableStream + manual
        // parsing. The result feeds an incrementally-growing
        // agent turn in the transcript.
        const agentTurn = {
          role:    'agent',
          text:    '',
          ts:      nowIso(),
          agent_id: null,
          raw:     '',
          streaming: true,
          // Native streaming (H1.5/H1.6) carries inline
          // tool_call + tool_result events. We render them
          // as an "activity" timeline above the text inside
          // the turn bubble.
          streaming_mode: null,   // 'native' | 'pseudo'
          tool_events:    [],     // [{ kind, name, id|call_id, arguments|output, error, ts }]
        };
        this.messages.push(agentTurn);
        this._persist();

        const base = (window.omAuth && window.omAuth.state && window.omAuth.state.baseUrl)
          ? window.omAuth.state.baseUrl.replace(/\/$/, '')
          : `${location.origin.replace(/\/$/, '')}/broker`;
        const token = (window.omAuth && window.omAuth.state && window.omAuth.state.token) || '';
        const url = `${base}/http/message/stream`;

        let resp;
        try {
          resp = await fetch(url, {
            method:  'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
              Accept: 'text/event-stream',
            },
            body: JSON.stringify(body),
            credentials: 'same-origin',
          });
        } catch (e) {
          this.composer.busy = false;
          agentTurn.streaming = false;
          agentTurn.error = true;
          agentTurn.text = `Network error: ${e && e.message || e}`;
          this.error = agentTurn.text;
          this._persist();
          return;
        }

        if (!resp.ok || !resp.body) {
          // Fall back to one-shot — preserves UX when the
          // streaming endpoint is missing (older deployment).
          this.messages.pop();  // remove the empty placeholder
          this._persist();
          await this._sendOneShot(body);
          return;
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        let currentEvent = null;
        const dataLines = [];
        let finalRaw = '';

        const flushEvent = () => {
          if (currentEvent === null) {
            dataLines.length = 0;
            return;
          }
          const dataStr = dataLines.join('\n');
          dataLines.length = 0;
          let payload = null;
          if (dataStr) {
            try { payload = JSON.parse(dataStr); }
            catch (_) { payload = { raw: dataStr }; }
          }
          this._handleSseEvent(currentEvent, payload, agentTurn);
          if (currentEvent === 'done') {
            finalRaw = dataStr;
          }
          currentEvent = null;
        };

        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });
            let nl;
            while ((nl = buf.indexOf('\n')) !== -1) {
              const line = buf.slice(0, nl).replace(/\r$/, '');
              buf = buf.slice(nl + 1);
              if (line === '') {
                flushEvent();
              } else if (line.startsWith('event: ')) {
                currentEvent = line.slice(7).trim();
              } else if (line.startsWith('data: ')) {
                dataLines.push(line.slice(6));
              }
              // ignore comment lines (": ...") and unknown fields
            }
          }
          // Flush a final pending event if the stream ended
          // without a terminating blank line.
          if (currentEvent !== null) flushEvent();
        } catch (e) {
          agentTurn.streaming = false;
          agentTurn.error = true;
          agentTurn.text = (agentTurn.text || '') + `\n[stream error: ${e && e.message || e}]`;
          this.error = `Stream error: ${e && e.message || e}`;
        }

        this.composer.busy = false;
        agentTurn.streaming = false;
        if (finalRaw) {
          agentTurn.raw = finalRaw;
          this.lastTurnRaw = finalRaw;
        }
        this._persist();
      },

      _handleSseEvent(event, payload, agentTurn) {
        if (!event || !payload) return;
        if (event === 'meta') {
          if (payload.session_id) {
            this.sessionId = payload.session_id;
            try { writeStored(STORAGE_KEY_SESSION, this.sessionId); }
            catch (_) { /* ignore */ }
          }
          agentTurn.streaming_mode = payload.streaming_mode || 'pseudo';
        } else if (event === 'chunk') {
          const delta = (payload && payload.delta) || '';
          if (!delta) return;
          // Native streaming: LLM tokens come pre-spaced
          // ("hello" + " world"). Concatenate verbatim.
          // Pseudo streaming: the backend splitter sliced the
          // text along sentence boundaries; we re-insert a
          // space between chunks if the previous one didn't
          // end with whitespace.
          if (agentTurn.streaming_mode === 'native') {
            agentTurn.text += delta;
          } else {
            if (agentTurn.text && !agentTurn.text.endsWith(' ') && !delta.startsWith(' ')) {
              agentTurn.text += ' ';
            }
            agentTurn.text += delta;
          }
        } else if (event === 'tool_call') {
          // H1.6: native-only event. The runtime tells us the
          // LLM is invoking a tool. Render an inline badge so
          // the operator sees the action without having to
          // open the raw payload.
          agentTurn.tool_events = agentTurn.tool_events || [];
          agentTurn.tool_events.push({
            kind:      'call',
            name:      payload.name || '',
            id:        payload.id || null,
            arguments: payload.arguments || {},
            ts:        nowIso(),
          });
        } else if (event === 'tool_result') {
          // H1.6: native-only event. The runtime ran the tool;
          // the output (or error) lands here. We match it back
          // to the originating tool_call by call_id so the UI
          // shows them as a pair.
          agentTurn.tool_events = agentTurn.tool_events || [];
          agentTurn.tool_events.push({
            kind:    'result',
            name:    payload.name || '',
            call_id: payload.call_id || null,
            output:  payload.output || '',
            error:   payload.error || null,
            ts:      nowIso(),
          });
        } else if (event === 'heartbeat') {
          agentTurn.last_heartbeat = payload.ts || null;
        } else if (event === 'done') {
          const m = (payload && payload.message) || {};
          if (m.text) agentTurn.text = m.text;
          if (m.agent_id) agentTurn.agent_id = m.agent_id;
          if (m.session_id) {
            this.sessionId = m.session_id;
            try { writeStored(STORAGE_KEY_SESSION, this.sessionId); }
            catch (_) { /* ignore */ }
          }
        } else if (event === 'error') {
          agentTurn.error = true;
          agentTurn.text = `Agent error: ${(payload && payload.error) || 'unknown'}`;
          this.error = agentTurn.text;
        }
      },

      // Small UI helper: truncate a tool_result output for the
      // inline badge (keep the full string in raw).
      truncateOutput(s, n) {
        const t = String(s || '');
        if (t.length <= n) return t;
        return t.slice(0, n) + '…';
      },

      toggleStreaming() {
        this.streamingEnabled = !this.streamingEnabled;
      },

      // ----- conversation management -----

      reset() {
        this.messages = [];
        this.sessionId = '';
        this.error = '';
        this.lastTurnRaw = '';
        writeStored(STORAGE_KEY_MESSAGES, []);
        writeStored(STORAGE_KEY_SESSION, '');
      },

      _persist() {
        // cap the transcript to avoid unbounded localStorage growth
        const tail = this.messages.length > MAX_PERSISTED_TURNS
          ? this.messages.slice(this.messages.length - MAX_PERSISTED_TURNS)
          : this.messages;
        writeStored(STORAGE_KEY_MESSAGES, tail);
      },

      // ----- derived -----

      isEmpty() {
        return this.messages.length === 0;
      },

      turnTone(role) {
        if (role === 'user')  return 'primary';
        if (role === 'agent') return 'accent';
        return 'neutral';
      },

      // testing hook — return the storage key constants so a
      // unit test can pin the contract.
      _storageKeys() {
        return { messages: STORAGE_KEY_MESSAGES, session: STORAGE_KEY_SESSION };
      },
    };
  };
})();
