/**
 * Theme module — light/dark switching with localStorage persistence.
 *
 * Used by every UI v2 entry point. Loaded *before* alpine.min.js so
 * the initial theme is applied before paint (avoids the flash of
 * unstyled content).
 *
 * Exposes a single global `omTheme` object:
 *
 *   omTheme.current()         -> 'light' | 'dark'
 *   omTheme.set(value)         -> set + persist + emit `om:theme` event
 *   omTheme.toggle()           -> flip + persist
 *   omTheme.respectSystem()    -> clear stored preference, follow OS
 */
(function () {
  'use strict';

  const STORAGE_KEY = 'openmiura.v2.theme';
  const ROOT = document.documentElement;

  function systemPreference() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light';
  }

  function readStored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (_) {
      return null;
    }
  }

  function write(value) {
    try {
      if (value === null) {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, value);
      }
    } catch (_) {
      /* ignore quota / disabled-storage errors */
    }
  }

  function apply(value) {
    ROOT.setAttribute('data-theme', value);
    document.dispatchEvent(
      new CustomEvent('om:theme', { detail: { theme: value } })
    );
  }

  // Apply initial theme before paint.
  const initial = readStored() || systemPreference();
  apply(initial);

  // Follow OS changes only when there is no explicit user preference.
  try {
    window
      .matchMedia('(prefers-color-scheme: dark)')
      .addEventListener('change', (event) => {
        if (!readStored()) {
          apply(event.matches ? 'dark' : 'light');
        }
      });
  } catch (_) {
    /* ignore in older browsers */
  }

  window.omTheme = {
    current: () => ROOT.getAttribute('data-theme') || systemPreference(),
    set(value) {
      if (value !== 'light' && value !== 'dark') return;
      write(value);
      apply(value);
    },
    toggle() {
      this.set(this.current() === 'dark' ? 'light' : 'dark');
    },
    respectSystem() {
      write(null);
      apply(systemPreference());
    },
  };
})();
