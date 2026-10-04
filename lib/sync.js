// Why Academy — settings sync
//
// localStorage stays the source of truth for the app; this module mirrors the
// synced keys to /api/settings when a session cookie exists. The server keeps
// one versioned document per user; on a version conflict we merge and retry.
//
// Merge rules:
//   prefs      - per-key last-write-wins by timestamp (unsynced local = t 0)
//   playground - union; completed if either side completed
//   rootlock   - best streak is the max
//
// The OpenRouter API key is not synced. Must stay in sync with
// worker/settings.js.

(function (root) {
  'use strict';

  const PREF_KEYS = [
    'handwriteBackend',
    'handwriteEndpoint',
    'handwriteModel',
    'openrouterModel',
    'handwriteStrokeWidth',
  ];
  const PLAYGROUND_KEY = 'why-academy-playground-progress';
  const ROOTLOCK_KEY = 'why-academy.rootlock.progress.v1';
  const PREF_TIMES_KEY = 'why-academy.sync.pref-times';
  const PLAYGROUND_ID = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
  const PUSH_DELAY_MS = 1000;
  const MAX_CONFLICT_RETRIES = 3;

  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const isTimestamp = v => Number.isInteger(v) && v >= 0;

  function parseJson(text, fallback) {
    if (!text) return fallback;
    try {
      return JSON.parse(text);
    } catch (e) {
      console.warn('WhySync: ignoring corrupt localStorage value', e);
      return fallback;
    }
  }

  // ── Document <-> localStorage ──

  function emptyDoc() {
    return { v: 1, prefs: {}, playground: {}, rootlock: { bestStreak: 0 } };
  }

  function cleanPlaygroundEntry(p) {
    if (!p || typeof p !== 'object') return null;
    const out = { completed: p.completed === true };
    if (isTimestamp(p.firstCompleted)) out.firstCompleted = p.firstCompleted;
    if (isTimestamp(p.lastCompleted)) out.lastCompleted = p.lastCompleted;
    return out;
  }

  function readLocal(storage) {
    const doc = emptyDoc();

    const times = parseJson(storage.getItem(PREF_TIMES_KEY), {});
    for (const key of PREF_KEYS) {
      const value = storage.getItem(key);
      const t = isTimestamp(times[key]) ? times[key] : 0;
      if (value !== null || t > 0) doc.prefs[key] = { value: value === null ? null : value.slice(0, 500), t: t };
    }

    const playground = parseJson(storage.getItem(PLAYGROUND_KEY), {});
    if (playground && typeof playground === 'object') {
      for (const id of Object.keys(playground)) {
        if (!PLAYGROUND_ID.test(id)) continue;
        const entry = cleanPlaygroundEntry(playground[id]);
        if (entry) doc.playground[id] = entry;
      }
    }

    const rootlock = parseJson(storage.getItem(ROOTLOCK_KEY), null);
    if (rootlock && Number.isInteger(rootlock.bestStreak) && rootlock.bestStreak >= 0) {
      doc.rootlock.bestStreak = Math.min(rootlock.bestStreak, 1000000);
    }

    return doc;
  }

  // Writes doc into storage; returns the list of storage keys that changed.
  function writeLocal(storage, doc) {
    const changed = [];
    const set = (key, value) => {
      const before = storage.getItem(key);
      if (value === null) {
        if (before !== null) { storage.removeItem(key); changed.push(key); }
      } else if (before !== value) {
        storage.setItem(key, value);
        changed.push(key);
      }
    };

    const times = parseJson(storage.getItem(PREF_TIMES_KEY), {});
    for (const key of PREF_KEYS) {
      if (!hasOwn(doc.prefs, key)) continue;
      set(key, doc.prefs[key].value);
      times[key] = doc.prefs[key].t;
    }
    storage.setItem(PREF_TIMES_KEY, JSON.stringify(times));

    // Keep whatever extra fields the playground stores locally; only the
    // synced fields are overwritten.
    const localPlayground = parseJson(storage.getItem(PLAYGROUND_KEY), {}) || {};
    const nextPlayground = Object.assign({}, localPlayground);
    for (const id of Object.keys(doc.playground)) {
      nextPlayground[id] = Object.assign({}, localPlayground[id], doc.playground[id]);
    }
    if (stableStringify(localPlayground) !== stableStringify(nextPlayground)) {
      set(PLAYGROUND_KEY, JSON.stringify(nextPlayground));
    }

    const localRootlock = parseJson(storage.getItem(ROOTLOCK_KEY), null);
    const localBest = localRootlock && Number.isInteger(localRootlock.bestStreak) ? localRootlock.bestStreak : 0;
    if (doc.rootlock.bestStreak !== localBest) {
      set(ROOTLOCK_KEY, JSON.stringify(Object.assign({}, localRootlock, { bestStreak: doc.rootlock.bestStreak })));
    }

    return changed;
  }

  // ── Merge ──

  function minDefined(a, b) {
    if (a === undefined) return b;
    if (b === undefined) return a;
    return Math.min(a, b);
  }
  function maxDefined(a, b) {
    if (a === undefined) return b;
    if (b === undefined) return a;
    return Math.max(a, b);
  }

  // Ties prefer a.
  function merge(a, b) {
    a = a || emptyDoc();
    b = b || emptyDoc();
    const out = emptyDoc();

    for (const key of PREF_KEYS) {
      const pa = hasOwn(a.prefs, key) ? a.prefs[key] : null;
      const pb = hasOwn(b.prefs, key) ? b.prefs[key] : null;
      const winner = !pb ? pa : !pa ? pb : (pb.t > pa.t ? pb : pa);
      if (winner) out.prefs[key] = { value: winner.value, t: winner.t };
    }

    const ids = new Set(Object.keys(a.playground).concat(Object.keys(b.playground)));
    for (const id of ids) {
      const ea = hasOwn(a.playground, id) ? a.playground[id] : null;
      const eb = hasOwn(b.playground, id) ? b.playground[id] : null;
      if (!ea || !eb) { out.playground[id] = cleanPlaygroundEntry(ea || eb); continue; }
      const entry = { completed: ea.completed || eb.completed };
      const first = minDefined(ea.firstCompleted, eb.firstCompleted);
      const last = maxDefined(ea.lastCompleted, eb.lastCompleted);
      if (first !== undefined) entry.firstCompleted = first;
      if (last !== undefined) entry.lastCompleted = last;
      out.playground[id] = entry;
    }

    out.rootlock.bestStreak = Math.max(a.rootlock.bestStreak, b.rootlock.bestStreak);
    return out;
  }

  function stableStringify(value) {
    if (Array.isArray(value)) return '[' + value.map(stableStringify).join(',') + ']';
    if (value && typeof value === 'object') {
      return '{' + Object.keys(value).sort()
        .filter(k => value[k] !== undefined)
        .map(k => JSON.stringify(k) + ':' + stableStringify(value[k])).join(',') + '}';
    }
    return JSON.stringify(value);
  }

  // ── Server sync (browser only) ──

  const state = {
    active: false,
    version: 0,
    timer: null,
    queue: Promise.resolve(),
  };

  function storage() { return root.localStorage; }

  function applyMerged(serverDoc) {
    const merged = merge(readLocal(storage()), serverDoc);
    const changed = writeLocal(storage(), merged);
    if (changed.length > 0) {
      root.document.dispatchEvent(new CustomEvent('whysync:applied', { detail: { keys: changed } }));
    }
    return merged;
  }

  // Pull the server copy, merge it into localStorage, and push back anything
  // the server is missing. Resolves to true when a session exists.
  async function start() {
    let resp;
    try {
      resp = await fetch('/api/settings', { credentials: 'same-origin' });
    } catch (e) {
      console.warn('WhySync: settings fetch failed', e);
      return false;
    }
    if (resp.status === 401 || resp.status === 404) {
      // 401: signed out. 404: static host without the API (local http-server).
      state.active = false;
      return false;
    }
    if (!resp.ok) {
      console.error('WhySync: settings fetch returned', resp.status);
      return false;
    }

    const server = await resp.json();
    state.active = true;
    state.version = server.version;
    const merged = applyMerged(server.data);
    if (stableStringify(merged) !== stableStringify(server.data)) enqueuePush(false);
    return true;
  }

  function stop() {
    state.active = false;
    state.version = 0;
    clearTimeout(state.timer);
    state.timer = null;
  }

  function enqueuePush(keepalive) {
    state.queue = state.queue.then(() => push(keepalive)).catch(e => {
      console.error('WhySync: push failed', e);
    });
    return state.queue;
  }

  async function push(keepalive) {
    for (let attempt = 0; attempt <= MAX_CONFLICT_RETRIES; attempt++) {
      if (!state.active) return;
      const resp = await fetch('/api/settings', {
        method: 'PUT',
        credentials: 'same-origin',
        keepalive: keepalive,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: readLocal(storage()), baseVersion: state.version }),
      });

      if (resp.ok) {
        state.version = (await resp.json()).version;
        return;
      }
      if (resp.status === 409) {
        const { current } = await resp.json();
        state.version = current.version;
        applyMerged(current.data);
        continue;
      }
      if (resp.status === 401) {
        stop();
        return;
      }
      throw new Error('settings PUT returned ' + resp.status + ': ' + (await resp.text()));
    }
    throw new Error('settings PUT gave up after ' + MAX_CONFLICT_RETRIES + ' conflicts');
  }

  // Call after writing any synced key. Pref keys must go through markChanged
  // so their timestamps advance.
  function schedule() {
    if (!state.active) return;
    clearTimeout(state.timer);
    state.timer = setTimeout(() => {
      state.timer = null;
      enqueuePush(false);
    }, PUSH_DELAY_MS);
  }

  function markChanged(keys) {
    const times = parseJson(storage().getItem(PREF_TIMES_KEY), {});
    const now = Date.now();
    for (const key of keys) {
      if (PREF_KEYS.includes(key)) times[key] = now;
    }
    storage().setItem(PREF_TIMES_KEY, JSON.stringify(times));
    schedule();
  }

  function flushOnHide() {
    if (root.document.visibilityState !== 'hidden' || !state.timer) return;
    clearTimeout(state.timer);
    state.timer = null;
    enqueuePush(true);
  }

  const api = {
    start, stop, schedule, markChanged,
    // Exposed for tests.
    _internal: { readLocal, writeLocal, merge, stableStringify, emptyDoc },
  };
  root.WhySync = api;

  if (root.document && root.fetch) {
    root.document.addEventListener('visibilitychange', flushOnHide);
    start();
  }
})(globalThis);
