/**
 * openMiura UI v2 — base component primitives.
 *
 * Exposes two managers (Toasts + Modals) and Alpine data factories
 * that pages instantiate via `x-data`. Together with the CSS in
 * @layer components and the icon registry in icons.js, this file
 * is the standard library every functional page draws from.
 *
 *   window.omToasts.push(message, { type, duration })
 *   window.omToasts.dismiss(id)
 *   window.omModal.open(id)
 *   window.omModal.close(id)
 *
 * Alpine wires:
 *
 *   x-data="omToastTray()"     -> place once near </body>
 *   x-data="omModalRoot()"     -> place once near </body>
 */
(function () {
  'use strict';

  // ===== Toasts =================================================

  let toastSeq = 0;
  const toastListeners = new Set();
  const toasts = [];

  function emitToasts() {
    toastListeners.forEach((fn) => fn(toasts.slice()));
  }

  function push(message, options) {
    const opts = options || {};
    const id = ++toastSeq;
    const item = {
      id,
      message: String(message || ''),
      type: opts.type || 'info', // 'info' | 'success' | 'warning' | 'danger'
      duration: typeof opts.duration === 'number' ? opts.duration : 4000,
      createdAt: Date.now(),
    };
    toasts.push(item);
    emitToasts();
    if (item.duration > 0) {
      setTimeout(() => dismiss(id), item.duration);
    }
    return id;
  }

  function dismiss(id) {
    const idx = toasts.findIndex((t) => t.id === id);
    if (idx === -1) return false;
    toasts.splice(idx, 1);
    emitToasts();
    return true;
  }

  function clear() {
    if (toasts.length === 0) return;
    toasts.length = 0;
    emitToasts();
  }

  window.omToasts = {
    push,
    info(msg, dur)    { return push(msg, { type: 'info',    duration: dur }); },
    success(msg, dur) { return push(msg, { type: 'success', duration: dur }); },
    warning(msg, dur) { return push(msg, { type: 'warning', duration: dur }); },
    danger(msg, dur)  { return push(msg, { type: 'danger',  duration: dur }); },
    dismiss,
    clear,
    list() { return toasts.slice(); },
    _subscribe(fn) { toastListeners.add(fn); return () => toastListeners.delete(fn); },
  };

  /**
   * Alpine factory for the tray that renders the toast stack.
   * Render once per page, immediately before </body>.
   *   <div x-data="omToastTray()" class="om-toast-tray">...</div>
   */
  window.omToastTray = function () {
    return {
      items: window.omToasts.list(),
      init() {
        this._unsub = window.omToasts._subscribe((next) => { this.items = next; });
      },
      destroy() {
        if (this._unsub) this._unsub();
      },
      dismiss(id) { window.omToasts.dismiss(id); },
      iconFor(type) {
        if (type === 'success') return 'circle-check';
        if (type === 'warning') return 'triangle-alert';
        if (type === 'danger')  return 'circle-alert';
        return 'info';
      },
    };
  };

  // ===== Modals =================================================

  const modalListeners = new Set();
  const openModals = new Set();

  function emitModals() {
    modalListeners.forEach((fn) => fn(new Set(openModals)));
  }

  function openModal(id) {
    if (!id) return;
    openModals.add(id);
    emitModals();
  }

  function closeModal(id) {
    if (!id) return;
    openModals.delete(id);
    emitModals();
  }

  function closeAllModals() {
    if (openModals.size === 0) return;
    openModals.clear();
    emitModals();
  }

  window.omModal = {
    open: openModal,
    close: closeModal,
    closeAll: closeAllModals,
    isOpen(id) { return openModals.has(id); },
    _subscribe(fn) { modalListeners.add(fn); return () => modalListeners.delete(fn); },
  };

  // Esc key closes the topmost modal.
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && openModals.size > 0) {
      const last = Array.from(openModals).pop();
      closeModal(last);
    }
  });

  /**
   * Alpine factory for a single modal instance. Register inside the
   * dialog's <div x-data="omModalFor('my-id')">. The factory
   * exposes:
   *   $data.open   -> true while this id is open
   *   $data.close()-> close this id
   * Combined with the omModal global API, any code path can open the
   * dialog via `window.omModal.open('my-id')`.
   */
  window.omModalFor = function (id) {
    return {
      id,
      open: window.omModal.isOpen(id),
      init() {
        this._unsub = window.omModal._subscribe((set) => {
          this.open = set.has(this.id);
        });
      },
      destroy() { if (this._unsub) this._unsub(); },
      close() { window.omModal.close(this.id); },
    };
  };
})();
