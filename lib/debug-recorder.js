// Why Academy — diagnostics recorder
//
// Loaded before every other script so it sees everything: console errors and
// warnings, uncaught errors, unhandled promise rejections, failed requests and
// every AI call (status, timing, error body). Bug reports attach a snapshot.
//
// Privacy: no request bodies, prompts or headers are kept (API keys travel in
// headers); URLs lose their query strings. Bug reports go to a public GitHub
// repo, so this stays limited to what a developer needs to debug.

(function () {
  'use strict';

  const LIMIT = 40;
  const logs = [];
  const requests = [];
  const ai = [];
  let errorCount = 0;
  const listeners = new Set();

  function push(list, entry) {
    list.push(entry);
    if (list.length > LIMIT) list.shift();
  }

  function changed() {
    for (const fn of listeners) {
      try {
        fn(errorCount);
      } catch (e) {
        // A broken listener must not break logging.
      }
    }
  }

  function text(v) {
    if (v instanceof Error) return (v.name + ': ' + v.message + (v.stack ? '\n' + v.stack.split('\n').slice(1, 4).join('\n') : '')).slice(0, 1200);
    if (typeof v === 'string') return v.slice(0, 1200);
    try {
      return JSON.stringify(v).slice(0, 1200);
    } catch (e) {
      return String(v).slice(0, 1200);
    }
  }

  function record(level, args) {
    push(logs, { t: new Date().toISOString(), level, message: Array.from(args).map(text).join(' ') });
    if (level === 'error') {
      errorCount++;
      changed();
    }
  }

  for (const level of ['error', 'warn']) {
    const orig = console[level].bind(console);
    console[level] = function () {
      record(level, arguments);
      return orig.apply(null, arguments);
    };
  }
  window.addEventListener('error', e => record('error', ['Uncaught: ' + (e.error ? text(e.error) : e.message) + ' @ ' + (e.filename || '') + ':' + (e.lineno || '')]));
  window.addEventListener('unhandledrejection', e => record('error', ['Unhandled rejection: ' + text(e.reason)]));

  function cleanUrl(u) {
    try {
      const url = new URL(u, location.href);
      return (url.origin === location.origin ? '' : url.origin) + url.pathname;
    } catch (e) {
      return String(u).split('?')[0].slice(0, 200);
    }
  }

  function isAiCall(url) {
    return /\/chat\/completions$/.test(url);
  }

  // What an AI request asked for, without its content (prompts can contain
  // paper text).
  function aiRequest(init) {
    try {
      const body = JSON.parse(init && init.body);
      const hasImage = (body.messages || []).some(m => Array.isArray(m.content) && m.content.some(p => p.type === 'image_url'));
      return { model: body.model, max_tokens: body.max_tokens, stream: !!body.stream, image: hasImage };
    } catch (e) {
      return {};
    }
  }

  const origFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = cleanUrl(typeof input === 'string' ? input : input.url);
    const method = (init && init.method) || (input && input.method) || 'GET';
    const started = performance.now();
    const isAi = isAiCall(url);
    const entry = { t: new Date().toISOString(), method, url };
    if (isAi) Object.assign(entry, aiRequest(init));
    try {
      const resp = await origFetch(input, init);
      entry.status = resp.status;
      entry.ms = Math.round(performance.now() - started);
      if (!resp.ok) {
        // Read the error body from a clone; the caller still gets the original.
        resp.clone().text().then(t => { entry.body = t.slice(0, 600); }).catch(() => {});
        push(requests, entry);
        errorCount++;
        changed();
      }
      if (isAi) push(ai, entry);
      return resp;
    } catch (e) {
      entry.error = text(e);
      entry.ms = Math.round(performance.now() - started);
      push(requests, entry);
      if (isAi) push(ai, entry);
      errorCount++;
      changed();
      throw e;
    }
  };

  const KEY = 'why.debug';
  // ?debug=1 turns debug mode on for this browser, ?debug=0 turns it off.
  const param = /[?&]debug=([01])\b/.exec(location.search);
  if (param) {
    try {
      if (param[1] === '1') localStorage.setItem(KEY, '1');
      else localStorage.removeItem(KEY);
    } catch (e) {
      console.warn('Could not save debug mode', e);
    }
  }
  function enabled() {
    try {
      return localStorage.getItem(KEY) === '1' || (param && param[1] === '1');
    } catch (e) {
      return !!(param && param[1] === '1');
    }
  }

  // Pages without their own Report bug button (all but the reader) get the
  // shared one from debug-ui.js, loaded only while debug mode is on.
  const uiUrl = new URL('debug-ui.js', document.currentScript.src).href;
  let uiLoading = null;
  function loadUi() {
    if (uiLoading || !enabled() || document.getElementById('bug-btn')) return;
    uiLoading = import(uiUrl).catch(e => {
      uiLoading = null;
      console.error('Debug UI failed to load', e);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loadUi);
  else loadUi();

  const contexts = new Map();
  window.WhyDebug = {
    enabled,
    setEnabled(on) {
      try {
        if (on) localStorage.setItem(KEY, '1');
        else localStorage.removeItem(KEY);
      } catch (e) {
        console.warn('Could not save debug mode', e);
      }
      if (on) loadUi();
      changed();
    },
    errorCount: () => errorCount,
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    // Pages add what they know (current lesson, block state...) under a name;
    // fn() runs when a report is made and must return plain JSON data.
    addContext(name, fn) {
      contexts.set(name, fn);
    },
    context() {
      const out = {};
      for (const [name, fn] of contexts) {
        try {
          out[name] = fn();
        } catch (e) {
          out[name] = { error: text(e) };
        }
      }
      return out;
    },
    snapshot() {
      return {
        logs: logs.slice(),
        failedRequests: requests.slice(),
        aiCalls: ai.slice(),
        errorCount,
      };
    },
  };
})();
