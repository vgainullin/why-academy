// Why Academy — Report bug button for every page
//
// debug-recorder.js loads this while debug mode is on, on pages that have no
// Report bug button of their own (the reader has its own). It adds a floating
// button with the error count, and opens the same annotate-and-file dialog as
// the reader (vault/bugreport.js). Ctrl/Cmd+Shift+B opens it too.

import { openBugReport } from './vault/bugreport.js';

const base = new URL('.', import.meta.url);

const css = document.createElement('link');
css.rel = 'stylesheet';
css.href = new URL('debug-ui.css', base).href;
document.head.appendChild(css);

const fab = document.createElement('button');
fab.type = 'button';
fab.className = 'whydbg-ui whydbg-fab';
fab.innerHTML = 'Report bug <span class="whydbg-count"></span>';
const dialog = document.createElement('dialog');
dialog.className = 'whydbg-ui whydbg-dialog';
const toastEl = document.createElement('div');
toastEl.className = 'whydbg-ui whydbg-toast';
toastEl.setAttribute('role', 'status');
toastEl.hidden = true;
document.body.append(fab, dialog, toastEl);

function render() {
  const on = window.WhyDebug.enabled();
  fab.hidden = !on;
  const n = window.WhyDebug.errorCount();
  const badge = fab.querySelector('.whydbg-count');
  badge.textContent = String(n);
  badge.hidden = !n;
  fab.title = n ? `Report a bug: ${n} error(s) recorded on this page (Ctrl+Shift+B)` : 'Report a bug (Ctrl+Shift+B)';
}
render();
window.WhyDebug.onChange(render);

let toastTimer = null;
function toast(msg, isError, action) {
  toastEl.textContent = msg;
  if (action) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = action.label;
    b.addEventListener('click', () => {
      toastEl.hidden = true;
      action.run();
    });
    toastEl.append(' ', b);
  }
  toastEl.classList.toggle('error', !!isError);
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toastEl.hidden = true; }, action ? 8000 : isError ? 7000 : 3500);
}

// The GitHub label for the page.
function area() {
  const name = location.pathname.split('/').pop().replace(/\.html$/, '');
  return name === '' || name === 'index' ? 'home' : name;
}

let buildInfo = null;
async function loadBuildInfo() {
  if (buildInfo) return buildInfo;
  try {
    const resp = await fetch(new URL('../build.json', base), { cache: 'no-store' });
    buildInfo = resp.ok ? await resp.json() : { error: 'HTTP ' + resp.status };
  } catch (e) {
    buildInfo = { error: e.message };
  }
  return buildInfo;
}

// Signed-in user from WhyAuth when the page has it, else from the server.
async function account() {
  if (window.WhyAuth && window.WhyAuth.getUser()) {
    return { id: window.WhyAuth.getUser().id, allowlisted: window.WhyAuth.isAllowlisted() };
  }
  try {
    const resp = await fetch('/api/me', { credentials: 'same-origin' });
    if (resp.status === 401) return { id: null, allowlisted: false };
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    return { id: data.user ? data.user.id : null, allowlisted: !!data.isAllowlisted };
  } catch (e) {
    console.error('Could not look up the account for the bug report', e);
    return { id: null, allowlisted: false };
  }
}

// AI settings without the key itself. They sync across devices, so a backend
// picked on one device applies on all of them.
function aiSettings() {
  const C = window.WhyCommon;
  if (!C) return null;
  const backend = C.handwriteBackend();
  let endpointHost;
  try {
    endpointHost = new URL(backend === 'openrouter' ? C.OPENROUTER_URL : C.lmstudioEndpoint()).host;
  } catch (e) {
    endpointHost = 'invalid endpoint';
  }
  return {
    backend,
    model: backend === 'openrouter' ? C.openrouterModel() : C.lmstudioModel(),
    endpointHost,
    keySet: backend === 'openrouter' ? !!C.openrouterApiKey() : null,
    pythonReady: !!C.pyodideReady,
    // When each AI setting last changed, on any device (settings sync).
    changedAt: settingTimes(['handwriteBackend', 'handwriteEndpoint', 'handwriteModel', 'openrouterModel']),
  };
}

function settingTimes(keys) {
  let times = {};
  try {
    times = JSON.parse(localStorage.getItem('why-academy.sync.pref-times') || '{}');
  } catch (e) {
    return { error: e.message };
  }
  const out = {};
  for (const k of keys) if (times[k]) out[k] = new Date(times[k]).toISOString();
  return out;
}

// Query parameters that may carry private text are dropped.
function pageUrl() {
  const u = new URL(location.href);
  for (const k of [...u.searchParams.keys()]) if (/q|token|key|code/i.test(k)) u.searchParams.set(k, '...');
  return u.pathname + u.search + u.hash.replace(/([?&]q=)[^&]*/, '$1...');
}

function diagnostics() {
  return {
    build: buildInfo,
    when: new Date().toISOString(),
    page: { url: pageUrl(), title: document.title },
    device: {
      userAgent: navigator.userAgent,
      viewport: `${innerWidth}x${innerHeight}@${devicePixelRatio}`,
      touch: matchMedia('(pointer: coarse)').matches,
      online: navigator.onLine,
      standalone: matchMedia('(display-mode: standalone)').matches,
    },
    ai: aiSettings(),
    context: window.WhyDebug.context(),
    recorder: window.WhyDebug.snapshot(),
  };
}

let opening = false;
async function report() {
  if (opening || dialog.open) return;
  opening = true;
  fab.disabled = true;
  try {
    const [, acct] = await Promise.all([loadBuildInfo(), account()]);
    await openBugReport({ dialog, diagnostics, toast, accountId: acct.id, allowlisted: acct.allowlisted, area: area() });
  } catch (e) {
    console.error('Bug report failed', e);
    toast('Bug report failed: ' + e.message, true);
  } finally {
    opening = false;
    fab.disabled = false;
  }
}

fab.addEventListener('click', report);
addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'B' || e.key === 'b') && window.WhyDebug.enabled()) {
    e.preventDefault();
    report();
  }
});
