// Why Academy — Shared Core Utilities
// Extracted from app.js and playground.js to eliminate code duplication.
// Exposes window.WhyCommon — a single namespace for Pyodide loading, handwrite
// backend config, LaTeX utilities, stroke helpers, UI widgets, and HTML helpers.
(function () {
  'use strict';

  // ── Pyodide State ──
  let pyodide = null;
  let pyodideLoading = false;
  let pyodideReady = false;
  let pyodideReadyCallbacks = [];

  // ── Loader Bar Driver ──
  function loaderEl() { return document.getElementById('pyodide-status'); }

  function setLoadProgress(pct, label) {
    const el = loaderEl();
    if (!el) return;
    el.classList.remove('hidden');
    const fill = el.querySelector('.loader-bar-fill');
    const labelEl = el.querySelector('.loader-label');
    const pctEl = el.querySelector('.loader-pct');
    if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
    if (labelEl && label) labelEl.textContent = label;
    if (pctEl) pctEl.textContent = Math.round(pct) + '%';
  }

  function setLoadSub(msg) {
    const el = loaderEl();
    if (!el) return;
    const sub = el.querySelector('.loader-sub');
    if (sub) sub.textContent = msg || '';
  }

  function setLoadDone() {
    const el = loaderEl();
    if (!el) return;
    setLoadProgress(100, 'Ready');
    setLoadSub('');
    el.classList.add('ready');
    setTimeout(function () { el.classList.add('hidden'); }, 1500);
  }

  function setLoadError(msg) {
    const el = loaderEl();
    if (!el) return;
    el.classList.remove('hidden');
    el.classList.add('error');
    const labelEl = el.querySelector('.loader-label');
    if (labelEl) labelEl.textContent = 'Failed: ' + msg;
    const pctEl = el.querySelector('.loader-pct');
    if (pctEl) pctEl.textContent = '';
  }

  function yieldToUI() { return new Promise(function (r) { setTimeout(r, 0); }); }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error('failed to load ' + src)); };
      document.head.appendChild(s);
    });
  }

  function waitForPyodide() {
    return new Promise(function (resolve) {
      if (pyodideReady) return resolve();
      const el = loaderEl();
      if (el) el.classList.remove('hidden');
      pyodideReadyCallbacks.push(resolve);
    });
  }

  // ── Pyodide Load ──
  async function startPyodidePreload(onReady) {
    if (pyodideLoading) return;
    pyodideLoading = true;
    setLoadProgress(2, 'Fetching Python runtime...');
    try {
      await loadScript('https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js');
      setLoadProgress(12, 'Initializing Python runtime...');
      await yieldToUI();

      pyodide = await loadPyodide({
        indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/',
        stdout: function () {},
        stderr: function () {}
      });
      setLoadProgress(35, 'Loading NumPy...');
      await yieldToUI();

      await pyodide.loadPackage('numpy', { messageCallback: setLoadSub });
      setLoadProgress(50, 'Loading Matplotlib...');
      await yieldToUI();

      await pyodide.loadPackage('matplotlib', { messageCallback: setLoadSub });
      setLoadProgress(60, 'Python ready');
      setLoadSub('');

      pyodideReady = true;
      pyodideReadyCallbacks.forEach(function (cb) { cb(); });
      pyodideReadyCallbacks = [];

      if (typeof onReady === 'function' && onReady()) return;
      setLoadDone();
    } catch (e) {
      console.error('Pyodide load failed:', e);
      setLoadError(e.message || String(e));
    }
  }

  // ── SymPy Lazy Load ──
  let sympyReady = false;
  let sympyLoadingPromise = null;

  async function ensureSympy() {
    if (sympyReady) return;
    if (sympyLoadingPromise) return sympyLoadingPromise;
    sympyLoadingPromise = (async function () {
      await waitForPyodide();
      setLoadProgress(62, 'Loading SymPy (~10MB)...');
      await yieldToUI();
      await pyodide.loadPackage(['sympy', 'micropip'], { messageCallback: setLoadSub });
      setLoadProgress(85, 'Installing LaTeX parser...');
      setLoadSub('');
      await yieldToUI();
      await pyodide.runPythonAsync(
        'import micropip\n' +
        'try:\n' +
        '    await micropip.install("antlr4-python3-runtime==4.11")\n' +
        'except Exception as e:\n' +
        '    print("antlr install warning:", e)\n'
      );
      setLoadProgress(95, 'Configuring symbolic engine...');
      await yieldToUI();
      await pyodide.runPythonAsync(
        'from sympy import simplify, Eq\n' +
        'from sympy.parsing.latex import parse_latex\n' +
        '\n' +
        'def _eq(a, b):\n' +
        '    if isinstance(a, Eq) and isinstance(b, Eq):\n' +
        '        d1 = simplify((a.lhs - a.rhs) - (b.lhs - b.rhs))\n' +
        '        d2 = simplify((a.lhs - a.rhs) + (b.lhs - b.rhs))\n' +
        '        return (d1 == 0) or (d2 == 0)\n' +
        '    if isinstance(a, Eq) or isinstance(b, Eq):\n' +
        '        return False\n' +
        '    return simplify(a - b) == 0\n' +
        '\n' +
        'def equiv(student_latex, target_latex):\n' +
        '    try:\n' +
        '        a = parse_latex(student_latex)\n' +
        '        b = parse_latex(target_latex)\n' +
        '    except Exception as e:\n' +
        '        return ("parse_error", str(e))\n' +
        '    try:\n' +
        '        return ("ok" if _eq(a, b) else "mismatch", "")\n' +
        '    except Exception as e:\n' +
        '        return ("simplify_error", str(e))\n' +
        '\n' +
        'def find_matching_form(student_latex, target_latexes):\n' +
        '    """Return index of first equivalent target, or -1 if no match."""\n' +
        '    try:\n' +
        '        a = parse_latex(student_latex)\n' +
        '    except Exception:\n' +
        '        return -1\n' +
        '    for i, t in enumerate(target_latexes):\n' +
        '        try:\n' +
        '            b = parse_latex(t)\n' +
        '            if _eq(a, b):\n' +
        '                return i\n' +
        '        except Exception:\n' +
        '            continue\n' +
        '    return -1\n'
      );
      sympyReady = true;
      setLoadDone();
    })().catch(function (e) {
      console.error('SymPy load failed:', e);
      setLoadError(e.message || String(e));
      throw e;
    });
    return sympyLoadingPromise;
  }

  // ── OpenRouter / LM Studio Backend Config ──
  const OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions';
  const DEFAULT_LMSTUDIO_ENDPOINT = 'http://localhost:1234/v1/chat/completions';
  const DEFAULT_LMSTUDIO_MODEL = 'qwen2-vl-7b-instruct';
  const OPENROUTER_MODEL_PRESETS = [
    { id: 'google/gemma-4-31b-it',           label: 'Gemma 4 31B (dense, default)' },
    { id: 'google/gemma-4-26b-a4b-it',       label: 'Gemma 4 26B MoE (cheaper)' },
    { id: 'google/gemma-4-31b-it:free',      label: 'Gemma 4 31B -- Free tier (rate-limited)' },
    { id: 'google/gemini-2.0-flash-001',     label: 'Gemini 2.0 Flash (cheapest)' },
    { id: 'anthropic/claude-sonnet-4-5',     label: 'Claude Sonnet 4.5 (most reliable)' },
    { id: 'qwen/qwen2-vl-72b-instruct',      label: 'Qwen2-VL 72B (matches local 7B)' }
  ];
  const DEFAULT_OPENROUTER_MODEL = OPENROUTER_MODEL_PRESETS[0].id;

  function handwriteBackend() {
    return localStorage.getItem('handwriteBackend') || 'openrouter';
  }
  function lmstudioEndpoint() {
    return localStorage.getItem('handwriteEndpoint') || DEFAULT_LMSTUDIO_ENDPOINT;
  }
  function lmstudioModel() {
    return localStorage.getItem('handwriteModel') || DEFAULT_LMSTUDIO_MODEL;
  }

  const _OBF_SALT = 'why-academy-obf';
  function _obfuscate(plain) {
    const out = [];
    for (let i = 0; i < plain.length; i++)
      out.push(plain.charCodeAt(i) ^ _OBF_SALT.charCodeAt(i % _OBF_SALT.length));
    return btoa(String.fromCharCode.apply(null, out));
  }
  function _deobfuscate(encoded) {
    const raw = atob(encoded);
    const out = [];
    for (let i = 0; i < raw.length; i++)
      out.push(raw.charCodeAt(i) ^ _OBF_SALT.charCodeAt(i % _OBF_SALT.length));
    return String.fromCharCode.apply(null, out);
  }
  function openrouterApiKey() {
    const stored = localStorage.getItem('openrouterApiKey') || '';
    if (!stored) return '';
    if (stored.startsWith('sk-or-')) {
      localStorage.setItem('openrouterApiKey', _obfuscate(stored));
      return stored;
    }
    try { return _deobfuscate(stored); }
    catch (e) { return ''; }
  }
  function setOpenrouterApiKey(key) {
    if (key) localStorage.setItem('openrouterApiKey', _obfuscate(key));
    else localStorage.removeItem('openrouterApiKey');
  }
  function openrouterModel() {
    return localStorage.getItem('openrouterModel') || DEFAULT_OPENROUTER_MODEL;
  }

  // ── LaTeX Utilities ──
  function cleanLatex(s) {
    if (!s) return '';
    s = s.trim();
    s = s.replace(/^```(?:latex|tex)?\s*/i, '').replace(/\s*```$/, '');
    s = s.replace(/^\$+/, '').replace(/\$+$/, '');
    s = s.replace(/^\\\[\s*/, '').replace(/\s*\\\]$/, '');
    s = s.replace(/^\\\(\s*/, '').replace(/\s*\\\)$/, '');
    return s.trim();
  }

  function canonicalizeLatex(s) {
    if (!s) return '';
    s = s.replace(/\\left\s*([(\[|])/g, '$1').replace(/\\right\s*([)\]|])/g, '$1');
    s = s.replace(/\\,|\\!|\\;|\\:|\\>/g, '');
    // \text{...} -> bare word (sympy parse_latex doesn't handle \text)
    s = s.replace(/\\text\s*\{([^}]*)\}/g, '$1');
    // \hat{x} -> x_hat (sympy-friendly symbol)
    s = s.replace(/\\hat\s*\{([^}]*)\}/g, '$1_hat');
    // \ell -> ell (plain symbol)
    s = s.replace(/\\ell\b/g, 'ell');
    // \propto -> = (treat proportionality as equality for symbolic check)
    s = s.replace(/\\propto/g, '=');
    // \cap -> * (joint probability as product for symbolic check)
    s = s.replace(/\\cap/g, '*');
    s = s.replace(/\\frac\s*\{\s*d\s*\^\s*\{?2\}?\s*([a-zA-Z]|\\[a-zA-Z]+)\s*\}\s*\{\s*dt\s*\^\s*\{?2\}?\s*\}/g, '\\ddot{$1}');
    s = s.replace(/\\frac\s*\{\s*d\s*([a-zA-Z]|\\[a-zA-Z]+)\s*\}\s*\{\s*dt\s*\}/g, '\\dot{$1}');
    return s.trim();
  }

  function buildTranscribePrompt(vars) {
    const varsLine = vars && vars.length
      ? '\nThe ONLY variables that may appear in this equation are: ' + vars.join(', ') +
        '. If you see a character that looks like an ASCII letter but a Greek letter is in the allowed list ' +
        '(e.g. w vs \\omega, a vs \\alpha), prefer the Greek letter. ' +
        'Do not introduce any variables outside this list.'
      : '';
    return (
      'Transcribe the handwritten mathematical equation in this image to LaTeX. ' +
      'Output ONLY the raw LaTeX expression. ' +
      'Absolutely NO dollar signs ($, $$). ' +
      'No \\[ \\] or \\( \\) delimiters. ' +
      'No prose. No code fences. No explanation. ' +
      'Use standard LaTeX commands: \\frac, \\sqrt, \\ddot, \\dot, \\omega, \\alpha, \\pi, etc.' +
      varsLine
    );
  }

  function buildMultiLinePrompt(vars) {
    const varsLine = vars && vars.length
      ? '\nThe ONLY variables that may appear are: ' + vars.join(', ') +
        '. Prefer Greek letters from this list over ASCII look-alikes ' +
        '(e.g. \\omega over w). Do not introduce variables outside this list.'
      : '';
    return (
      'The image contains handwritten mathematics, possibly multiple lines stacked vertically. ' +
      'Transcribe each physical line of handwriting as ONE LaTeX expression. ' +
      'Output one LaTeX expression per line, separated by newlines. ' +
      'Output ONLY the raw LaTeX. ' +
      'NO dollar signs ($, $$). NO \\[ \\] or \\( \\) delimiters. ' +
      'NO \\begin{aligned} or other environments. ' +
      'NO prose. NO code fences. NO explanation. ' +
      'Use standard LaTeX commands: \\frac, \\sqrt, \\ddot, \\dot, \\omega, \\alpha, \\pi, etc. ' +
      'IMPORTANT: If the handwriting is unreadable, too messy to parse, or the image is blank/empty, ' +
      'output exactly the word UNREADABLE on a single line. Do NOT guess or hallucinate equations. ' +
      'Only transcribe what you can clearly see.' +
      varsLine
    );
  }

  function parseMultiLineLatex(raw) {
    if (!raw) return [];
    let s = raw.trim();
    if (/^\s*UNREADABLE\s*$/i.test(s)) return [];
    s = s.replace(/^```(?:latex|tex)?\s*/i, '').replace(/\s*```$/, '');
    s = s.replace(/\\begin\{(aligned|align\*?|gathered|equation\*?)\}/g, '');
    s = s.replace(/\\end\{(aligned|align\*?|gathered|equation\*?)\}/g, '');
    const parts = s.split(/\r?\n|\\\\/);
    return parts
      .map(function (p) { return cleanLatex(p); })
      .filter(function (p) { return p.length > 0 && !/^\s*UNREADABLE\s*$/i.test(p); });
  }

  // ── Vision Backend Caller ──
  async function callVisionBackend(promptText, pngDataUrl, maxTokens) {
    const backend = handwriteBackend();
    let url, headers, model;
    if (backend === 'openrouter') {
      const key = openrouterApiKey();
      if (!key) {
        throw new Error('OpenRouter API key not set. Open Settings to add one.');
      }
      url = OPENROUTER_URL;
      headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + key,
        'HTTP-Referer': window.location.origin,
        'X-Title': 'Why Academy'
      };
      model = openrouterModel();
    } else {
      url = lmstudioEndpoint();
      headers = { 'Content-Type': 'application/json' };
      model = lmstudioModel();
    }
    const resp = await fetch(url, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({
        model: model,
        messages: [{
          role: 'user',
          content: [
            { type: 'text', text: promptText },
            { type: 'image_url', image_url: { url: pngDataUrl } }
          ]
        }],
        temperature: 0,
        max_tokens: maxTokens
      })
    });
    if (!resp.ok) {
      throw new Error('transcription HTTP ' + resp.status + ': ' + (await resp.text()));
    }
    const json = await resp.json();
    return json.choices[0].message.content;
  }

  async function transcribeHandwriting(pngDataUrl, vars) {
    const raw = await callVisionBackend(buildTranscribePrompt(vars), pngDataUrl, 200);
    return { raw: raw, latex: cleanLatex(raw) };
  }

  async function transcribeMultiLine(pngDataUrl, vars) {
    const raw = await callVisionBackend(buildMultiLinePrompt(vars), pngDataUrl, 400);
    return { raw: raw, lines: parseMultiLineLatex(raw) };
  }

  // ── Stroke Configuration ──
  const STROKE_WIDTH_DEFAULT = 7;
  const STROKE_WIDTH_MIN = 3;
  const STROKE_WIDTH_MAX = 18;

  function getStrokeWidth() {
    const v = parseFloat(localStorage.getItem('handwriteStrokeWidth'));
    if (!Number.isFinite(v) || v <= 0) return STROKE_WIDTH_DEFAULT;
    return Math.max(STROKE_WIDTH_MIN, Math.min(STROKE_WIDTH_MAX, v));
  }
  function setStrokeWidth(v) {
    localStorage.setItem('handwriteStrokeWidth', String(v));
  }

  function findStrokeHitByPoint(strokes, point, radius) {
    for (let i = strokes.length - 1; i >= 0; i--) {
      const s = strokes[i];
      const r = Math.max(radius, (s.width || 4) + 4);
      const r2 = r * r;
      for (let j = 0; j < s.points.length; j++) {
        const pp = s.points[j];
        const dx = pp.x - point.x;
        const dy = pp.y - point.y;
        if (dx * dx + dy * dy < r2) return i;
      }
    }
    return -1;
  }

  function isEraserPointerEvent(e, eraserModeOn) {
    if (eraserModeOn) return true;
    if (e.button === 5) return true;
    if (typeof e.buttons === 'number' && (e.buttons & 32) !== 0) return true;
    return false;
  }

  // ── UI Widgets ──
  function makeEraserToggle(getMode, setMode) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-secondary stroke-eraser-btn';
    btn.type = 'button';
    btn.innerHTML = '<span class="eraser-icon" aria-hidden="true"></span>Eraser';
    btn.title = 'Tap a stroke to remove it (keyboard: E)';
    function sync() {
      btn.classList.toggle('btn-active', !!getMode());
    }
    btn.addEventListener('click', function () {
      setMode(!getMode());
      sync();
    });
    sync();
    return { btn: btn, sync: sync };
  }

  function makeStrokeWidthSlider() {
    const wrap = document.createElement('label');
    wrap.className = 'stroke-width-slider';
    const labelText = document.createElement('span');
    labelText.className = 'stroke-width-label';
    labelText.textContent = 'Thickness';
    const slider = document.createElement('input');
    slider.type = 'range';
    slider.min = String(STROKE_WIDTH_MIN);
    slider.max = String(STROKE_WIDTH_MAX);
    slider.step = '0.5';
    slider.value = String(getStrokeWidth());
    slider.setAttribute('aria-label', 'Marker thickness');
    const preview = document.createElement('span');
    preview.className = 'stroke-width-preview';
    function syncPreview() {
      const v = parseFloat(slider.value);
      preview.style.width = v + 'px';
      preview.style.height = v + 'px';
    }
    syncPreview();
    slider.addEventListener('input', function () {
      setStrokeWidth(parseFloat(slider.value));
      syncPreview();
    });
    wrap.appendChild(labelText);
    wrap.appendChild(slider);
    wrap.appendChild(preview);
    return wrap;
  }

  function initSettingsModal() {
    const modal = document.getElementById('settings-modal');
    if (!modal) return;
    const openBtn = document.getElementById('settings-btn');
    const cancelBtn = document.getElementById('settings-cancel');
    const saveBtn = document.getElementById('settings-save');
    const backdrop = modal.querySelector('.settings-modal-backdrop');
    const radios = modal.querySelectorAll('input[name="handwrite-backend"]');
    const lmGroup = document.getElementById('settings-lmstudio');
    const orGroup = document.getElementById('settings-openrouter');
    const lmEndpointEl = document.getElementById('settings-lmstudio-endpoint');
    const lmModelEl = document.getElementById('settings-lmstudio-model');
    const orKeyEl = document.getElementById('settings-openrouter-key');
    const orModelSelect = document.getElementById('settings-openrouter-model-select');
    const orModelCustomLabel = document.getElementById('settings-openrouter-model-custom-label');
    const orModelEl = document.getElementById('settings-openrouter-model');
    const CUSTOM_VALUE = '__custom__';

    function populateOrDropdown() {
      orModelSelect.innerHTML = '';
      OPENROUTER_MODEL_PRESETS.forEach(function (p) {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label;
        orModelSelect.appendChild(opt);
      });
      const customOpt = document.createElement('option');
      customOpt.value = CUSTOM_VALUE;
      customOpt.textContent = 'Custom...';
      orModelSelect.appendChild(customOpt);
    }
    populateOrDropdown();

    function syncOrCustomVisibility() {
      const isCustom = orModelSelect.value === CUSTOM_VALUE;
      orModelCustomLabel.classList.toggle('hidden', !isCustom);
    }

    function syncGroups() {
      const v = (modal.querySelector('input[name="handwrite-backend"]:checked') || {}).value;
      lmGroup.classList.toggle('hidden', v !== 'lmstudio');
      orGroup.classList.toggle('hidden', v !== 'openrouter');
    }

    function loadIntoForm() {
      const backend = handwriteBackend();
      radios.forEach(function (r) { r.checked = (r.value === backend); });
      lmEndpointEl.value = lmstudioEndpoint();
      lmModelEl.value = lmstudioModel();
      orKeyEl.value = openrouterApiKey();

      const currentOrModel = openrouterModel();
      const isPreset = OPENROUTER_MODEL_PRESETS.some(function (p) { return p.id === currentOrModel; });
      if (isPreset) {
        orModelSelect.value = currentOrModel;
        orModelEl.value = '';
      } else {
        orModelSelect.value = CUSTOM_VALUE;
        orModelEl.value = currentOrModel;
      }
      syncOrCustomVisibility();
      syncGroups();
    }

    function open() {
      loadIntoForm();
      modal.classList.remove('hidden');
    }
    function close() {
      modal.classList.add('hidden');
    }

    openBtn.addEventListener('click', open);
    cancelBtn.addEventListener('click', close);
    backdrop.addEventListener('click', close);
    radios.forEach(function (r) { r.addEventListener('change', syncGroups); });
    orModelSelect.addEventListener('change', syncOrCustomVisibility);

    saveBtn.addEventListener('click', function () {
      const backend = (modal.querySelector('input[name="handwrite-backend"]:checked') || {}).value || 'lmstudio';
      localStorage.setItem('handwriteBackend', backend);

      const lmEndpoint = lmEndpointEl.value.trim();
      if (lmEndpoint) localStorage.setItem('handwriteEndpoint', lmEndpoint);
      else localStorage.removeItem('handwriteEndpoint');
      const lmModel = lmModelEl.value.trim();
      if (lmModel) localStorage.setItem('handwriteModel', lmModel);
      else localStorage.removeItem('handwriteModel');

      const orKey = orKeyEl.value.trim();
      setOpenrouterApiKey(orKey);

      let orModel;
      if (orModelSelect.value === CUSTOM_VALUE) {
        orModel = orModelEl.value.trim();
      } else {
        orModel = orModelSelect.value;
      }
      if (orModel) localStorage.setItem('openrouterModel', orModel);
      else localStorage.removeItem('openrouterModel');

      close();
    });
  }

  function renderKaTeX(root) {
    const el = root || document.body;
    if (typeof renderMathInElement === 'function') {
      renderMathInElement(el, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false }
        ],
        throwOnError: false
      });
    }
  }

  function renderHints(hints) {
    const div = document.createElement('div');
    div.className = 'mt-12';
    let shown = 0;

    const btn = document.createElement('button');
    btn.className = 'hint-btn';
    btn.textContent = 'Need a hint?';
    div.appendChild(btn);

    const hintContainer = document.createElement('div');
    div.appendChild(hintContainer);

    btn.addEventListener('click', function () {
      if (shown < hints.length) {
        const hintEl = document.createElement('div');
        hintEl.className = 'hint-text mt-8';
        hintEl.textContent = hints[shown];
        hintContainer.appendChild(hintEl);
        shown++;
        if (shown >= hints.length) {
          btn.style.display = 'none';
        }
      }
    });

    return div;
  }

  function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function evalFormula(formula, params) {
    const keys = Object.keys(params);
    const vals = Object.values(params);
    const fn = new Function(...keys, 'return ' + formula);
    return fn(...vals);
  }

  // ── Exports ──
  window.WhyCommon = {
    // Pyodide
    get pyodide() { return pyodide; },
    set pyodide(v) { pyodide = v; },
    get pyodideReady() { return pyodideReady; },
    startPyodidePreload: startPyodidePreload,
    ensureSympy: ensureSympy,
    waitForPyodide: waitForPyodide,
    setLoadProgress: setLoadProgress,
    setLoadSub: setLoadSub,
    setLoadDone: setLoadDone,
    setLoadError: setLoadError,
    loadScript: loadScript,
    yieldToUI: yieldToUI,
    loaderEl: loaderEl,

    // Backend config
    handwriteBackend: handwriteBackend,
    lmstudioEndpoint: lmstudioEndpoint,
    lmstudioModel: lmstudioModel,
    openrouterApiKey: openrouterApiKey,
    setOpenrouterApiKey: setOpenrouterApiKey,
    openrouterModel: openrouterModel,
    OPENROUTER_URL: OPENROUTER_URL,
    OPENROUTER_MODEL_PRESETS: OPENROUTER_MODEL_PRESETS,
    DEFAULT_OPENROUTER_MODEL: DEFAULT_OPENROUTER_MODEL,
    DEFAULT_LMSTUDIO_ENDPOINT: DEFAULT_LMSTUDIO_ENDPOINT,
    DEFAULT_LMSTUDIO_MODEL: DEFAULT_LMSTUDIO_MODEL,

    // LaTeX
    cleanLatex: cleanLatex,
    canonicalizeLatex: canonicalizeLatex,
    buildTranscribePrompt: buildTranscribePrompt,
    buildMultiLinePrompt: buildMultiLinePrompt,
    parseMultiLineLatex: parseMultiLineLatex,
    callVisionBackend: callVisionBackend,
    transcribeHandwriting: transcribeHandwriting,
    transcribeMultiLine: transcribeMultiLine,

    // Strokes
    getStrokeWidth: getStrokeWidth,
    setStrokeWidth: setStrokeWidth,
    findStrokeHitByPoint: findStrokeHitByPoint,
    isEraserPointerEvent: isEraserPointerEvent,
    STROKE_WIDTH_DEFAULT: STROKE_WIDTH_DEFAULT,
    STROKE_WIDTH_MIN: STROKE_WIDTH_MIN,
    STROKE_WIDTH_MAX: STROKE_WIDTH_MAX,

    // UI widgets
    makeEraserToggle: makeEraserToggle,
    makeStrokeWidthSlider: makeStrokeWidthSlider,
    initSettingsModal: initSettingsModal,

    // Helpers
    renderKaTeX: renderKaTeX,
    renderHints: renderHints,
    esc: esc,
    evalFormula: evalFormula
  };
})();
