// Why Academy — Phase 1 App

(function () {
  'use strict';

  // ── State ──
  let lesson = null;
  let pyodide = null;
  let pyodideLoading = false;
  let pyodideReady = false;
  let pyodideReadyCallbacks = [];
  const blockState = {}; // blockId -> { completed, ... }

  // ── Boot ──
  document.addEventListener('DOMContentLoaded', async () => {
    if (window.WhyAuth) WhyAuth.init();
    initSettingsModal();

    // The landing page (index.html) has no #blocks-container; only the lesson
    // view does. Skip Pyodide preload and lesson fetch on the landing so it
    // stays lightweight and loads instantly.
    const blocksContainer = document.getElementById('blocks-container');
    if (!blocksContainer) return;

    startPyodidePreload();

    // Re-render feedback toolbars when auth state changes
    document.addEventListener('whyauth:change', () => {
      document.querySelectorAll('.feedback-toolbar').forEach(updateFeedbackToolbarVisibility);
      updateSendButton();
    });

    const params = new URLSearchParams(window.location.search);
    const lessonFile = params.get('lesson') || 'lessons/physics/oscillations/01-single-spring.json';
    try {
      const resp = await fetch(lessonFile);
      lesson = await resp.json();
      renderLesson();
    } catch (e) {
      document.getElementById('lesson-container').innerHTML =
        '<p style="padding:20px;color:red;">Failed to load lesson: ' + e.message + '</p>';
    }
  });

  // ── Loading bar driver ──
  // Visible top sticky bar showing phase + determinate progress + streamed
  // sub-messages from Pyodide's messageCallback. The bar is the *only* thing
  // that fights perceived freeze — the actual main-thread jank during wasm
  // decode is intrinsic to running CPython on the main thread; only a Web
  // Worker can fix that, and that's a separate refactor.
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
    setTimeout(() => el.classList.add('hidden'), 1500);
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

  // Yield to the event loop so the DOM can repaint between heavy phases.
  // Won't unjank the wasm decode itself, but flushes our progress updates.
  function yieldToUI() { return new Promise(r => setTimeout(r, 0)); }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error('failed to load ' + src));
      document.head.appendChild(s);
    });
  }

  // ── Pyodide Lazy Load ──
  // Phase weights (must sum to <= 60 so SymPy install gets the remaining 40):
  //   inject pyodide.js   :  2 -> 12   (10pt)
  //   init runtime        : 12 -> 35   (23pt)
  //   numpy               : 35 -> 50   (15pt)
  //   matplotlib          : 50 -> 60   (10pt)
  // ensureSympy() picks up at 60% and runs to 100%.
  async function startPyodidePreload() {
    if (pyodideLoading) return;
    pyodideLoading = true;
    setLoadProgress(2, 'Fetching Python runtime…');
    try {
      await loadScript('https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js');
      setLoadProgress(12, 'Initializing Python runtime…');
      await yieldToUI();

      pyodide = await loadPyodide({
        indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/',
        stdout: () => {},
        stderr: () => {}
      });
      setLoadProgress(35, 'Loading NumPy…');
      await yieldToUI();

      await pyodide.loadPackage('numpy', { messageCallback: setLoadSub });
      setLoadProgress(50, 'Loading Matplotlib…');
      await yieldToUI();

      await pyodide.loadPackage('matplotlib', { messageCallback: setLoadSub });
      setLoadProgress(60, 'Python ready');
      setLoadSub('');

      pyodideReady = true;
      pyodideReadyCallbacks.forEach(cb => cb());
      pyodideReadyCallbacks = [];

      // If no handwrite/canvas-derive blocks need SymPy, we're done.
      // ensureSympy() drives the bar from 60% to 100% if it gets called.
      if (!sympyNeeded()) {
        setLoadDone();
      }
    } catch (e) {
      console.error('Pyodide load failed:', e);
      setLoadError(e.message || String(e));
    }
  }

  function waitForPyodide() {
    return new Promise(resolve => {
      if (pyodideReady) return resolve();
      const el = loaderEl();
      if (el) el.classList.remove('hidden');
      pyodideReadyCallbacks.push(resolve);
    });
  }

  // True if the loaded lesson has at least one block that needs SymPy.
  function sympyNeeded() {
    if (!lesson || !lesson.blocks) return false;
    return lesson.blocks.some(b => b.type === 'handwrite' || b.type === 'canvas-derive');
  }

  // ── SymPy lazy load (for handwrite verification) ──
  // Sympy + antlr4 add ~10MB so we only load them if a handwrite block exists.
  // Resolves to the same shared `pyodide` instance with parse_latex available.
  let sympyReady = false;
  let sympyLoadingPromise = null;
  async function ensureSympy() {
    if (sympyReady) return;
    if (sympyLoadingPromise) return sympyLoadingPromise;
    sympyLoadingPromise = (async () => {
      await waitForPyodide();
      // Phase weights for the SymPy half of the bar:
      //   sympy + micropip  : 60 -> 85   (25pt) — biggest single download
      //   antlr4 install    : 85 -> 95   (10pt)
      //   helper definitions: 95 -> 100  (5pt)
      setLoadProgress(62, 'Loading SymPy (~10MB)…');
      await yieldToUI();
      await pyodide.loadPackage(['sympy', 'micropip'], { messageCallback: setLoadSub });
      setLoadProgress(85, 'Installing LaTeX parser…');
      setLoadSub('');
      await yieldToUI();
      await pyodide.runPythonAsync(
        'import micropip\n' +
        'try:\n' +
        '    await micropip.install("antlr4-python3-runtime==4.11")\n' +
        'except Exception as e:\n' +
        '    print("antlr install warning:", e)\n'
      );
      setLoadProgress(95, 'Configuring symbolic engine…');
      await yieldToUI();
      // Define a single equiv() helper reused for every check.
      // parse_latex doesn't understand \ddot/\dot — it parses them as opaque
      // symbols (ddot, dot). That's fine as long as we apply the same parse to
      // both sides; the canonicalizer below also rewrites \frac{d^2 X}{dt^2}
      // and \frac{dX}{dt} into \ddot{X} / \dot{X} so students who use Leibniz
      // notation get matched against textbook Newton notation.
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
    })().catch(e => {
      console.error('SymPy load failed:', e);
      setLoadError(e.message || String(e));
      throw e;
    });
    return sympyLoadingPromise;
  }

  // Rewrite \frac{d^2 X}{dt^2} -> \ddot{X} and \frac{dX}{dt} -> \dot{X}
  // so Leibniz notation matches Newton notation. Also strips Mathpix-style
  // \left/\right and thin spaces \, \! that aren't meaningful for parsing.
  function canonicalizeLatex(s) {
    if (!s) return '';
    s = s.replace(/\\left\s*([(\[|])/g, '$1').replace(/\\right\s*([)\]|])/g, '$1');
    s = s.replace(/\\,|\\!|\\;|\\:|\\>/g, '');
    // \frac{d^2 x}{dt^2}  -> \ddot{x}     (variable must be a single letter or \greek)
    s = s.replace(/\\frac\s*\{\s*d\s*\^\s*\{?2\}?\s*([a-zA-Z]|\\[a-zA-Z]+)\s*\}\s*\{\s*dt\s*\^\s*\{?2\}?\s*\}/g, '\\ddot{$1}');
    // \frac{dx}{dt}       -> \dot{x}
    s = s.replace(/\\frac\s*\{\s*d\s*([a-zA-Z]|\\[a-zA-Z]+)\s*\}\s*\{\s*dt\s*\}/g, '\\dot{$1}');
    return s.trim();
  }

  // ── Handwrite transcription backend ──
  // Two backends are supported, selectable via the Settings modal:
  //   - 'lmstudio'   : POST directly to LM Studio's OpenAI-compatible endpoint
  //                    (local dev, no key required, default).
  //   - 'openrouter' : POST to OpenRouter's OpenAI-compatible endpoint with the
  //                    user's own API key. Key is stored in localStorage and
  //                    sent directly from the browser to openrouter.ai.
  // Backwards-compat: legacy localStorage keys handwriteEndpoint /
  // handwriteModel still override the LM Studio defaults.
  const OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions';
  const DEFAULT_LMSTUDIO_ENDPOINT = 'http://localhost:1234/v1/chat/completions';
  const DEFAULT_LMSTUDIO_MODEL = 'qwen2-vl-7b-instruct';
  // Curated OpenRouter vision models for handwritten math OCR. The first entry
  // is the default. The Settings dropdown is populated from this list (plus a
  // "Custom…" escape hatch for anything not in here).
  const OPENROUTER_MODEL_PRESETS = [
    { id: 'google/gemma-4-31b-it',           label: 'Gemma 4 31B (dense, default)' },
    { id: 'google/gemma-4-26b-a4b-it',       label: 'Gemma 4 26B MoE (cheaper)' },
    { id: 'google/gemma-4-31b-it:free',      label: 'Gemma 4 31B — Free tier (rate-limited)' },
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
  // Obfuscate the API key in localStorage so it's not plaintext in DevTools.
  // This is NOT real encryption — the obfuscation key is in the source — but
  // it prevents casual exposure when someone browses localStorage.
  const _OBF_SALT = 'why-academy-obf';
  function _obfuscate(plain) {
    const out = [];
    for (let i = 0; i < plain.length; i++)
      out.push(plain.charCodeAt(i) ^ _OBF_SALT.charCodeAt(i % _OBF_SALT.length));
    return btoa(String.fromCharCode(...out));
  }
  function _deobfuscate(encoded) {
    const raw = atob(encoded);
    const out = [];
    for (let i = 0; i < raw.length; i++)
      out.push(raw.charCodeAt(i) ^ _OBF_SALT.charCodeAt(i % _OBF_SALT.length));
    return String.fromCharCode(...out);
  }
  function openrouterApiKey() {
    const stored = localStorage.getItem('openrouterApiKey') || '';
    if (!stored) return '';
    // Migrate plaintext keys (start with sk-or-) to obfuscated form
    if (stored.startsWith('sk-or-')) {
      localStorage.setItem('openrouterApiKey', _obfuscate(stored));
      return stored;
    }
    try { return _deobfuscate(stored); }
    catch { return ''; }
  }
  function setOpenrouterApiKey(key) {
    if (key) localStorage.setItem('openrouterApiKey', _obfuscate(key));
    else localStorage.removeItem('openrouterApiKey');
  }
  function openrouterModel() {
    return localStorage.getItem('openrouterModel') || DEFAULT_OPENROUTER_MODEL;
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

  function cleanLatex(s) {
    if (!s) return '';
    s = s.trim();
    s = s.replace(/^```(?:latex|tex)?\s*/i, '').replace(/\s*```$/, '');
    s = s.replace(/^\$+/, '').replace(/\$+$/, '');
    s = s.replace(/^\\\[\s*/, '').replace(/\s*\\\]$/, '');
    s = s.replace(/^\\\(\s*/, '').replace(/\s*\\\)$/, '');
    return s.trim();
  }

  // Multi-line variant for the freeform canvas: ask the model to return one
  // LaTeX expression per line of handwriting, separated by newlines. Returns
  // an array of cleaned LaTeX strings (one per detected line).
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
    // Vision model says it can't read the handwriting
    if (/^\s*UNREADABLE\s*$/i.test(s)) return [];
    // Strip code fences
    s = s.replace(/^```(?:latex|tex)?\s*/i, '').replace(/\s*```$/, '');
    // Strip aligned wrapper if model added one despite the prompt
    s = s.replace(/\\begin\{(aligned|align\*?|gathered|equation\*?)\}/g, '');
    s = s.replace(/\\end\{(aligned|align\*?|gathered|equation\*?)\}/g, '');
    // Split on actual newlines OR LaTeX line breaks (\\)
    const parts = s.split(/\r?\n|\\\\/);
    return parts
      .map(p => cleanLatex(p))
      .filter(p => p.length > 0 && !/^\s*UNREADABLE\s*$/i.test(p));
  }

  // Shared backend caller for any vision-LM transcription request. Handles the
  // LM Studio vs OpenRouter switch in one place so single-line, multi-line, and
  // any future variants automatically support both backends.
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

  async function transcribeMultiLine(pngDataUrl, vars) {
    const raw = await callVisionBackend(buildMultiLinePrompt(vars), pngDataUrl, 400);
    return { raw: raw, lines: parseMultiLineLatex(raw) };
  }

  // Stroke thickness preference (shared between canvas-derive and handwrite).
  // Persisted in localStorage so the student picks it once and it sticks.
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

  // Hit-test: find the topmost (newest) stroke whose path passes within
  // `radius` of `point`. Returns the index in the strokes array, or -1.
  // The effective radius scales with stroke width so thicker strokes are
  // easier to hit. Brute force; fine for tens-to-hundreds of strokes.
  function findStrokeHitByPoint(strokes, point, radius) {
    for (let i = strokes.length - 1; i >= 0; i--) {
      const s = strokes[i];
      const r = Math.max(radius, (s.width || 4) + 4);
      const r2 = r * r;
      for (const pp of s.points) {
        const dx = pp.x - point.x;
        const dy = pp.y - point.y;
        if (dx * dx + dy * dy < r2) return i;
      }
    }
    return -1;
  }

  // True if the pointer event represents an eraser interaction either via
  // a stylus hardware eraser end (W3C button 5 / buttons bit 32) or because
  // the explicit eraser-mode toggle is on. Apple Pencil 2 / Pro do NOT fire
  // these — Apple keeps double-tap and squeeze gestures inside native APIs.
  function isEraserPointerEvent(e, eraserModeOn) {
    if (eraserModeOn) return true;
    if (e.button === 5) return true;
    if (typeof e.buttons === 'number' && (e.buttons & 32) !== 0) return true;
    return false;
  }

  // Build an Eraser toggle button. Caller passes get/set/onChange so the
  // button stays in sync with the surrounding closure's state.
  function makeEraserToggle(getMode, setMode) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-secondary stroke-eraser-btn';
    btn.type = 'button';
    btn.innerHTML = '<span class="eraser-icon" aria-hidden="true"></span>Eraser';
    btn.title = 'Tap a stroke to remove it (keyboard: E)';
    function sync() {
      btn.classList.toggle('btn-active', !!getMode());
    }
    btn.addEventListener('click', () => {
      setMode(!getMode());
      sync();
    });
    sync();
    return { btn: btn, sync: sync };
  }

  // Build a thickness slider widget. Each canvas reads getStrokeWidth() at
  // pointerdown time, so a single shared localStorage value drives all open
  // canvases live without explicit cross-block wiring.
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
    slider.addEventListener('input', () => {
      setStrokeWidth(parseFloat(slider.value));
      syncPreview();
    });
    wrap.appendChild(labelText);
    wrap.appendChild(slider);
    wrap.appendChild(preview);
    return wrap;
  }

  async function transcribeHandwriting(pngDataUrl, vars) {
    const raw = await callVisionBackend(buildTranscribePrompt(vars), pngDataUrl, 200);
    return { raw: raw, latex: cleanLatex(raw) };
  }

  // ── Settings modal ──
  function initSettingsModal() {
    const modal = document.getElementById('settings-modal');
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

    // Populate the OpenRouter dropdown from the preset list (plus Custom…).
    function populateOrDropdown() {
      orModelSelect.innerHTML = '';
      OPENROUTER_MODEL_PRESETS.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.label;
        orModelSelect.appendChild(opt);
      });
      const customOpt = document.createElement('option');
      customOpt.value = CUSTOM_VALUE;
      customOpt.textContent = 'Custom…';
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
      radios.forEach(r => { r.checked = (r.value === backend); });
      lmEndpointEl.value = lmstudioEndpoint();
      lmModelEl.value = lmstudioModel();
      orKeyEl.value = openrouterApiKey();

      const currentOrModel = openrouterModel();
      const isPreset = OPENROUTER_MODEL_PRESETS.some(p => p.id === currentOrModel);
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
    radios.forEach(r => r.addEventListener('change', syncGroups));
    orModelSelect.addEventListener('change', syncOrCustomVisibility);

    saveBtn.addEventListener('click', () => {
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

      // Resolve model: if dropdown is on "Custom…" use the text field, else
      // use the dropdown value directly.
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

  // ── Render Lesson ──
  function renderLesson() {
    const header = document.getElementById('lesson-header');
    header.innerHTML = '<h2>' + esc(lesson.title) + '</h2><p>' + esc(lesson.description) + '</p>';

    const container = document.getElementById('blocks-container');
    container.innerHTML = '';
    lesson.blocks.forEach(block => {
      const el = renderBlock(block);
      container.appendChild(el);
    });

    // Wait for KaTeX auto-render to be available (loaded with defer)
    function tryRenderKaTeX() {
      if (typeof renderMathInElement === 'function') {
        renderKaTeX();
      } else {
        setTimeout(tryRenderKaTeX, 50);
      }
    }
    tryRenderKaTeX();
  }

  function renderBlock(block) {
    const wrapper = document.createElement('div');
    wrapper.className = 'block block-' + block.type;
    wrapper.id = 'block-' + block.id;
    blockState[block.id] = { completed: false };

    const label = document.createElement('span');
    label.className = 'block-label block-label-' + block.type;
    label.textContent = block.type;
    wrapper.appendChild(label);

    if (block.title) {
      const title = document.createElement('h3');
      title.className = 'block-title';
      title.textContent = block.title;
      wrapper.appendChild(title);
    }

    const renderers = {
      read: renderRead,
      derive: renderDerive,
      calculate: renderCalculate,
      code: renderCode,
      practice: renderPractice,
      explain: renderExplain,
      explore: renderExplore,
      predict: renderPredict,
      discover: renderDiscover,
      compare: renderCompare,
      reconcile: renderReconcile,
      vary: renderVary,
      connect: renderConnect,
      handwrite: renderHandwrite,
      'canvas-derive': renderCanvasDerive
    };

    const renderer = renderers[block.type];
    const content = renderer ? renderer(block, wrapper) : renderUnsupportedBlock(block);
    wrapper.appendChild(content);

    // Feedback toolbar on every block
    wrapper.appendChild(renderFeedbackToolbar(block.id, wrapper));

    return wrapper;
  }

  // ── Read Block ──
  function renderRead(block) {
    const div = document.createElement('div');
    div.className = 'content';
    div.innerHTML = block.content_html;

    // Initialize interactive elements after DOM insertion
    setTimeout(() => {
      div.querySelectorAll('[data-interactive="spring"]').forEach(el => {
        initSpringAnimation(el);
      });
    }, 0);

    return div;
  }

  function makeScientificNotationInput(placeholderMantissa, placeholderExponent) {
    const wrap = document.createElement('div');
    wrap.className = 'sci-notation-input';

    const mantissa = document.createElement('input');
    mantissa.type = 'number';
    mantissa.step = '0.01';
    mantissa.placeholder = placeholderMantissa || '1.00';
    mantissa.setAttribute('aria-label', 'Mantissa');

    const timesTen = document.createElement('span');
    timesTen.className = 'times-ten';
    timesTen.innerHTML = '&times; 10';

    const exponent = document.createElement('input');
    exponent.type = 'number';
    exponent.step = '1';
    exponent.placeholder = placeholderExponent || '0';
    exponent.style.width = '50px';
    exponent.setAttribute('aria-label', 'Exponent');

    wrap.appendChild(mantissa);
    wrap.appendChild(timesTen);
    wrap.appendChild(exponent);

    return { wrap, mantissa, exponent };
  }

  function parseScientificNotation(mantissaEl, exponentEl) {
    const m = parseFloat(mantissaEl.value);
    const e = parseInt(exponentEl.value, 10);
    if (!Number.isFinite(m) || !Number.isFinite(e)) return null;
    return m * Math.pow(10, e);
  }

  function renderFunctionMachineSimulation(block) {
    const cfg = block.simulation_config || {};
    const root = document.createElement('div');
    root.className = 'function-machine mt-12';

    const header = document.createElement('div');
    header.className = 'function-machine-header';
    header.innerHTML = '<strong>Interactive Function Machine</strong><span>Change machines and observe outputs instantly.</span>';
    root.appendChild(header);

    const controls = document.createElement('div');
    controls.className = 'function-machine-controls';
    root.appendChild(controls);

    function makeLabeledControl(labelText, inputEl) {
      const item = document.createElement('label');
      item.className = 'fm-control';
      const text = document.createElement('span');
      text.className = 'fm-label';
      text.textContent = labelText;
      item.appendChild(text);
      item.appendChild(inputEl);
      return item;
    }

    const functionOptions = Array.isArray(cfg.function_options) && cfg.function_options.length
      ? cfg.function_options
      : ['square', 'add_3', 'multiply_by_2', 'inverse'];

    const inputX = document.createElement('input');
    inputX.type = 'number';
    inputX.step = '0.1';
    inputX.value = '5';
    inputX.className = 'fm-input';
    controls.appendChild(makeLabeledControl(cfg.input_slot || 'x', inputX));

    function makeFnSelect(defaultValue) {
      const select = document.createElement('select');
      select.className = 'fm-select';
      functionOptions.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
      });
      if (defaultValue && functionOptions.includes(defaultValue)) select.value = defaultValue;
      return select;
    }

    const fSelect = makeFnSelect(functionOptions[0]);
    const gSelect = makeFnSelect(functionOptions[1] || functionOptions[0]);
    controls.appendChild(makeLabeledControl('f machine', fSelect));
    controls.appendChild(makeLabeledControl('g machine', gSelect));

    const stretchInput = document.createElement('input');
    stretchInput.type = 'range';
    stretchInput.min = '0.5';
    stretchInput.max = '3';
    stretchInput.step = '0.1';
    stretchInput.value = '1';
    stretchInput.className = 'fm-range';
    const stretchWrap = makeLabeledControl('stretch', stretchInput);
    controls.appendChild(stretchWrap);

    const shiftInput = document.createElement('input');
    shiftInput.type = 'range';
    shiftInput.min = '-10';
    shiftInput.max = '10';
    shiftInput.step = '0.5';
    shiftInput.value = '0';
    shiftInput.className = 'fm-range';
    const shiftWrap = makeLabeledControl('shift', shiftInput);
    controls.appendChild(shiftWrap);

    const outputGrid = document.createElement('div');
    outputGrid.className = 'function-machine-output-grid';
    root.appendChild(outputGrid);

    function makeOutputTile(label) {
      const tile = document.createElement('div');
      tile.className = 'fm-output-tile';
      const k = document.createElement('div');
      k.className = 'fm-output-key';
      k.textContent = label;
      const v = document.createElement('div');
      v.className = 'fm-output-value';
      v.textContent = '-';
      tile.appendChild(k);
      tile.appendChild(v);
      outputGrid.appendChild(tile);
      return v;
    }

    const outFx = makeOutputTile('f(x)');
    const outGx = makeOutputTile('g(x)');
    const outFog = makeOutputTile('f(g(x))');
    const outGof = makeOutputTile('g(f(x))');

    const formula = document.createElement('div');
    formula.className = 'fm-formula';
    root.appendChild(formula);

    const dataTable = document.createElement('table');
    dataTable.className = 'data-table mt-12';
    root.appendChild(dataTable);

    function applyMachine(kind, x) {
      if (!Number.isFinite(x)) return NaN;
      let y;
      if (kind === 'square') y = x * x;
      else if (kind === 'add_3') y = x + 3;
      else if (kind === 'multiply_by_2') y = 2 * x;
      else if (kind === 'inverse') y = Math.abs(x) < 1e-9 ? NaN : 1 / x;
      else y = x;

      const stretch = parseFloat(stretchInput.value) || 1;
      const shift = parseFloat(shiftInput.value) || 0;
      return stretch * y + shift;
    }

    function fmt(n) {
      if (!Number.isFinite(n)) return 'undefined';
      const rounded = Math.round(n * 10000) / 10000;
      return String(rounded);
    }

    function renderDataRows(baseX) {
      const columns = ['x', 'f(x)', 'g(x)', 'f(g(x))', 'g(f(x))'];
      const head = document.createElement('thead');
      const headRow = document.createElement('tr');
      columns.forEach(c => {
        const th = document.createElement('th');
        th.textContent = c;
        headRow.appendChild(th);
      });
      head.appendChild(headRow);

      const body = document.createElement('tbody');
      const rows = [];
      for (let delta = -2; delta <= 2; delta++) {
        const x = baseX + delta;
        const fx = applyMachine(fSelect.value, x);
        const gx = applyMachine(gSelect.value, x);
        const fog = applyMachine(fSelect.value, gx);
        const gof = applyMachine(gSelect.value, fx);
        rows.push({ x, 'f(x)': fx, 'g(x)': gx, 'f(g(x))': fog, 'g(f(x))': gof });

        const tr = document.createElement('tr');
        columns.forEach(c => {
          const td = document.createElement('td');
          td.textContent = fmt(rows[rows.length - 1][c]);
          tr.appendChild(td);
        });
        body.appendChild(tr);
      }

      dataTable.innerHTML = '';
      dataTable.appendChild(head);
      dataTable.appendChild(body);
      blockState[block.id].exploration_data = rows;
    }

    function refresh() {
      const x = parseFloat(inputX.value);
      const fx = applyMachine(fSelect.value, x);
      const gx = applyMachine(gSelect.value, x);
      const fog = applyMachine(fSelect.value, gx);
      const gof = applyMachine(gSelect.value, fx);

      outFx.textContent = fmt(fx);
      outGx.textContent = fmt(gx);
      outFog.textContent = fmt(fog);
      outGof.textContent = fmt(gof);

      formula.textContent = 'Current chain: f=' + fSelect.value + ', g=' + gSelect.value +
        ' | stretch=' + (parseFloat(stretchInput.value) || 1).toFixed(1) +
        ', shift=' + (parseFloat(shiftInput.value) || 0).toFixed(1);

      if (Number.isFinite(x)) renderDataRows(x);
    }

    [inputX, fSelect, gSelect, stretchInput, shiftInput].forEach(el => {
      el.addEventListener('input', refresh);
      el.addEventListener('change', refresh);
    });

    refresh();
    return root;
  }

  function renderExplore(block) {
    const div = document.createElement('div');

    if (block.content_html) {
      const content = document.createElement('div');
      content.className = 'content';
      content.innerHTML = block.content_html;
      div.appendChild(content);
    }

    if (block.instructions) {
      const instructions = document.createElement('div');
      instructions.className = 'mt-12';
      instructions.innerHTML = '<strong>Try this:</strong><br>' + block.instructions;
      div.appendChild(instructions);
    }

    if (block.simulation_config && block.simulation_config.type === 'physical_function_machine') {
      div.appendChild(renderPhysicalFunctionMachineSimulation(block));
    } else if (block.simulation_config && block.simulation_config.type === 'function_machine') {
      div.appendChild(renderFunctionMachineSimulation(block));
    } else if (block.simulation_config && block.simulation_config.type === 'globe_tossing') {
      div.appendChild(renderGlobeTossingSimulation(block));
    } else if (block.simulation_config && block.simulation_config.type === 'track_simulation') {
      div.appendChild(renderTrackSimulation(block));
    } else if (block.simulation_config) {
      const sim = document.createElement('div');
      sim.className = 'mt-12';
      const simType = block.simulation_config.type ? 'Simulation: ' + esc(block.simulation_config.type) : 'Simulation configured';
      sim.innerHTML = '<strong>' + simType + '</strong>';
      div.appendChild(sim);
    }

    const doneBtn = document.createElement('button');
    doneBtn.className = 'btn btn-primary mt-12';
    doneBtn.textContent = 'I explored this';
    doneBtn.addEventListener('click', () => {
      doneBtn.disabled = true;
      markComplete(block.id, div);
    });
    div.appendChild(doneBtn);

    return div;
  }

  
  function renderPhysicalFunctionMachineSimulation(block) {
    const cfg = block.simulation_config || {};
    const root = document.createElement('div');
    root.className = 'function-machine mt-12 bg-white p-6 rounded-xl shadow-lg border border-blue-100';

    const header = document.createElement('div');
    header.className = 'mb-6 text-center';
    header.innerHTML = '<h3 class="text-2xl font-extrabold text-gray-800 mb-2">Physical Function Machine</h3><p class="text-gray-500">Chain altitude and temperature transformations to see how they interact.</p>';
    root.appendChild(header);

    // --- CANVAS VISUALIZATION ---
    const canvasContainer = document.createElement('div');
    canvasContainer.className = 'flex justify-center my-6 relative rounded-xl overflow-hidden shadow-inner border border-gray-200';
    const canvas = document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 400;
    canvas.className = 'block max-w-full';
    canvasContainer.appendChild(canvas);
    root.appendChild(canvasContainer);
    const ctx = canvas.getContext('2d');

    const controls = document.createElement('div');
    controls.className = 'function-machine-controls grid grid-cols-1 md:grid-cols-2 gap-6 mt-8';
    root.appendChild(controls);

    function makeLabeledControl(labelText, inputEl, colorClass) {
      const item = document.createElement('div');
      item.className = `flex flex-col bg-gray-50 p-4 rounded-lg border-l-4 ${colorClass}`;
      const text = document.createElement('span');
      text.className = 'font-bold text-gray-700 mb-3';
      text.textContent = labelText;
      item.appendChild(text);
      
      const row = document.createElement('div');
      row.className = 'flex items-center w-full';
      inputEl.className = 'flex-1 cursor-pointer accent-blue-600';
      row.appendChild(inputEl);
      item.appendChild(row);
      
      return { item, row };
    }

    // Time input for machine g
    const inputT = document.createElement('input');
    inputT.type = 'range';
    inputT.min = '0';
    inputT.max = '1000';
    inputT.step = '10';
    inputT.value = '0';
    
    const valT = document.createElement('span');
    valT.className = 'ml-4 min-w-[60px] text-right font-mono font-bold text-blue-600 bg-blue-100 py-1 px-2 rounded';
    valT.textContent = '0 s';
    
    const wrapT = makeLabeledControl('Machine g: Time (t)', inputT, 'border-blue-500');
    wrapT.row.appendChild(valT);
    controls.appendChild(wrapT.item);

    // Altitude input for machine f
    const inputH = document.createElement('input');
    inputH.type = 'range';
    inputH.min = '0';
    inputH.max = '10000';
    inputH.step = '100';
    inputH.value = '1000';

    const valH = document.createElement('span');
    valH.className = 'ml-4 min-w-[80px] text-right font-mono font-bold text-red-600 bg-red-100 py-1 px-2 rounded';
    valH.textContent = '1000 m';

    const wrapH = makeLabeledControl('Machine f: Altitude (h)', inputH, 'border-red-500');
    wrapH.row.appendChild(valH);
    controls.appendChild(wrapH.item);

    // Compose toggle
    const toggleContainer = document.createElement('div');
    toggleContainer.className = 'col-span-1 md:col-span-2 flex justify-center mt-2 mb-4';
    
    const wrapLink = document.createElement('label');
    wrapLink.className = 'flex items-center p-4 bg-gradient-to-r from-blue-50 to-red-50 border-2 border-dashed border-gray-300 rounded-xl cursor-pointer hover:border-blue-400 transition-colors shadow-sm';
    
    const checkLink = document.createElement('input');
    checkLink.type = 'checkbox';
    checkLink.className = 'hidden'; // Hide default checkbox
    
    const customToggle = document.createElement('div');
    customToggle.className = 'w-12 h-6 bg-gray-300 rounded-full mr-4 relative transition-colors duration-300';
    const customToggleDot = document.createElement('div');
    customToggleDot.className = 'w-4 h-4 bg-white rounded-full absolute top-1 left-1 transition-transform duration-300 shadow';
    customToggle.appendChild(customToggleDot);

    const toggleText = document.createElement('span');
    toggleText.className = 'font-extrabold text-gray-700 text-lg tracking-wide';
    toggleText.innerHTML = 'COMPOSE MACHINES <span class="text-sm font-normal text-gray-500 ml-2">(Link Altitude to Balloon: h = g(t))</span>';

    wrapLink.appendChild(checkLink);
    wrapLink.appendChild(customToggle);
    wrapLink.appendChild(toggleText);
    toggleContainer.appendChild(wrapLink);
    
    // Insert toggle between header/canvas and controls
    root.insertBefore(toggleContainer, controls);

    // Update toggle visual state
    checkLink.addEventListener('change', (e) => {
      if (e.target.checked) {
        customToggle.classList.replace('bg-gray-300', 'bg-purple-600');
        customToggleDot.classList.add('translate-x-6');
        wrapLink.classList.replace('border-gray-300', 'border-purple-400');
      } else {
        customToggle.classList.replace('bg-purple-600', 'bg-gray-300');
        customToggleDot.classList.remove('translate-x-6');
        wrapLink.classList.replace('border-purple-400', 'border-gray-300');
      }
    });

    // Output Grid
    const outputGrid = document.createElement('div');
    outputGrid.className = 'mt-6 grid grid-cols-1 md:grid-cols-2 gap-4';
    root.appendChild(outputGrid);

    function makeOutputTile(label, initialValue, colorTheme) {
      const tile = document.createElement('div');
      tile.className = `bg-white p-4 rounded-xl shadow-sm border border-${colorTheme}-200 flex flex-col items-center justify-center`;
      const k = document.createElement('div');
      k.className = `text-xs font-bold text-${colorTheme}-600 uppercase tracking-wider mb-2 text-center`;
      k.innerHTML = label;
      const v = document.createElement('div');
      v.className = 'text-3xl font-mono text-gray-800 font-black';
      v.textContent = initialValue;
      tile.appendChild(k);
      tile.appendChild(v);
      outputGrid.appendChild(tile);
      return { container: tile, label: k, value: v };
    }

    const outGt = makeOutputTile('g(t)<br><span class="text-gray-400 text-[10px]">Balloon Alt</span>', '1000 m', 'blue');
    const outFh = makeOutputTile('f(h)<br><span class="text-gray-400 text-[10px]">Sensor Temp</span>', '14.0 °C', 'red');

    // Drawing helper functions
    function drawBalloon(x, y, scale = 1) {
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(scale, scale);
      
      // Basket lines
      ctx.beginPath();
      ctx.moveTo(-8, 20); ctx.lineTo(-12, 35);
      ctx.moveTo(8, 20); ctx.lineTo(12, 35);
      ctx.strokeStyle = '#8B4513';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Basket
      ctx.fillStyle = '#D2691E';
      ctx.fillRect(-15, 35, 30, 15);
      
      // Envelope (balloon)
      ctx.beginPath();
      ctx.moveTo(0, 25);
      ctx.bezierCurveTo(30, 25, 40, -10, 0, -40);
      ctx.bezierCurveTo(-40, -10, -30, 25, 0, 25);
      
      // Stripes
      const gradient = ctx.createLinearGradient(-30, 0, 30, 0);
      gradient.addColorStop(0, '#FF4500');
      gradient.addColorStop(0.3, '#FFD700');
      gradient.addColorStop(0.7, '#FF4500');
      gradient.addColorStop(1, '#FF8C00');
      ctx.fillStyle = gradient;
      ctx.fill();
      
      // Envelope outline
      ctx.strokeStyle = '#B22222';
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.restore();
    }

    function drawThermometer(x, y, height, tempPercent) {
      ctx.save();
      ctx.translate(x, y);

      const bulbRadius = 16;
      const tubeWidth = 14;
      const tubeHeight = height;

      // Glass tube background
      ctx.fillStyle = 'rgba(255,255,255,0.8)';
      ctx.beginPath();
      ctx.arc(0, -tubeHeight, tubeWidth/2, Math.PI, 0); // top curve
      ctx.lineTo(tubeWidth/2, 0);
      ctx.arc(0, 0, bulbRadius, Math.asin(tubeWidth/2/bulbRadius), Math.PI - Math.asin(tubeWidth/2/bulbRadius)); // bulb
      ctx.lineTo(-tubeWidth/2, -tubeHeight);
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#ccc';
      ctx.stroke();

      // Fluid (Red)
      const fluidHeight = 10 + (tubeHeight - 20) * tempPercent;
      ctx.fillStyle = '#E53935';
      ctx.beginPath();
      ctx.arc(0, 0, bulbRadius - 3, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillRect(-tubeWidth/2 + 3, -fluidHeight, tubeWidth - 6, fluidHeight);

      // Highlight/Gloss
      ctx.fillStyle = 'rgba(255,255,255,0.4)';
      ctx.fillRect(-tubeWidth/2 + 2, -tubeHeight, tubeWidth/3, tubeHeight + 10);

      // Tick marks
      ctx.fillStyle = '#666';
      ctx.font = '12px font-mono font-bold';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      for(let i=0; i<=4; i++) {
        const tickY = -tubeHeight + 10 + (tubeHeight - 20) * (i/4);
        ctx.fillRect(tubeWidth/2, tickY, 6, 2);
        
        // Map ticks to labels (from 20 to -40)
        const labelTemp = 20 - (i * 15); 
        ctx.fillText(labelTemp + '°', tubeWidth/2 + 10, tickY);
      }

      ctx.restore();
    }

    function drawClouds(time) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      const drift = (time * 0.5) % 800;
      
      function cloud(cx, cy, scale) {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.scale(scale, scale);
        ctx.beginPath();
        ctx.arc(0, 0, 20, 0, Math.PI*2);
        ctx.arc(25, -10, 25, 0, Math.PI*2);
        ctx.arc(50, 0, 20, 0, Math.PI*2);
        ctx.fill();
        ctx.restore();
      }

      cloud(drift - 200, 250, 1.5);
      cloud(drift + 300, 180, 1);
      cloud(drift + 700, 220, 1.2);
    }

    function draw(t, h, isComposed) {
      // Clear
      ctx.clearRect(0, 0, 800, 400);

      // Sky Gradient
      const grad = ctx.createLinearGradient(0, 0, 0, 400);
      grad.addColorStop(0, '#0f172a'); // Very high altitude (space)
      grad.addColorStop(0.3, '#1e3a8a');
      grad.addColorStop(0.6, '#3b82f6');
      grad.addColorStop(1, '#93c5fd'); // Surface sky
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, 800, 400);

      // Stars at top
      ctx.fillStyle = 'rgba(255,255,255,0.8)';
      for(let i=0; i<30; i++) {
        const sx = (Math.sin(i * 123) * 400) + 400;
        const sy = (Math.cos(i * 321) * 100) + 100;
        ctx.beginPath();
        ctx.arc(sx, sy, Math.random() * 1.5, 0, Math.PI*2);
        ctx.fill();
      }

      // Ground
      const groundGrad = ctx.createLinearGradient(0, 370, 0, 400);
      groundGrad.addColorStop(0, '#4ade80');
      groundGrad.addColorStop(1, '#166534');
      ctx.fillStyle = groundGrad;
      ctx.beginPath();
      ctx.moveTo(0, 400);
      ctx.lineTo(0, 370);
      ctx.quadraticCurveTo(400, 360, 800, 380);
      ctx.lineTo(800, 400);
      ctx.fill();

      drawClouds(t);

      // Helpers
      // Altitude 0 to 10000 -> Y maps from 360 to 40
      const mapY = (alt) => 360 - (alt / 10000) * 320;
      const gt = 1000 + 5 * t;
      const tempH = isComposed ? gt : h;
      const fh = 20 - 0.006 * tempH;

      // Draw Balloon at g(t)
      const by = mapY(gt);
      ctx.globalAlpha = isComposed ? 1.0 : 0.6;
      drawBalloon(250, by);
      ctx.globalAlpha = 1.0;

      // Altitude indicator lines for balloon
      ctx.strokeStyle = 'rgba(255,255,255,0.3)';
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(250, by);
      ctx.lineTo(100, by);
      ctx.stroke();
      ctx.setLineDash([]);
      
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 12px sans-serif';
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(gt.toFixed(0) + ' m', 90, by);

      // Draw Sensor at h (if not composed, it's separate)
      let sensorY;
      if (!isComposed) {
        sensorY = mapY(h);
        
        // Draw standalone sensor probe
        ctx.fillStyle = '#E53935'; // Red
        ctx.beginPath();
        ctx.roundRect(350, sensorY - 8, 24, 16, 4);
        ctx.fill();
        ctx.fillStyle = 'white';
        ctx.fillRect(354, sensorY - 2, 4, 4);
        ctx.fillRect(362, sensorY - 2, 4, 4);
        ctx.fillRect(370, sensorY - 2, 4, 4);

        ctx.font = '10px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Temp Sensor', 380, sensorY);
        
        // Draw dotted line showing separation
        ctx.strokeStyle = 'rgba(255,100,100,0.5)';
        ctx.setLineDash([5, 5]);
        ctx.beginPath();
        ctx.moveTo(250, by);
        ctx.lineTo(350, sensorY);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // Altitude indicator for sensor
        ctx.fillStyle = '#fca5a5';
        ctx.textAlign = 'right';
        ctx.fillText(h.toFixed(0) + ' m', 340, sensorY);

      } else {
        // Sensor is attached to balloon basket
        sensorY = by + 40;
        ctx.fillStyle = '#E53935';
        ctx.beginPath();
        ctx.arc(260, sensorY, 6, 0, Math.PI*2);
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.stroke();
      }

      // Draw beautiful Thermometer on the right
      // Map temp: 20 to -40 -> Percent 1.0 to 0.0
      let tempPercent = (fh - (-40)) / 60;
      tempPercent = Math.max(0, Math.min(1, tempPercent)); // clamp
      
      drawThermometer(650, 320, 240, tempPercent);

      // Connecting line from sensor to thermometer
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.beginPath();
      ctx.moveTo(isComposed ? 260 : 374, sensorY);
      ctx.lineTo(620, sensorY); // Lead it roughly towards thermometer side
      
      // We also draw an arrow pointing to the fluid level
      const fluidLevelY = 320 - 10 - (240 - 20) * tempPercent;
      ctx.lineTo(630, fluidLevelY);
      ctx.stroke();

      // Overlay text HUD
      ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
      ctx.beginPath();
      ctx.roundRect(20, 20, 220, isComposed ? 90 : 70, 8);
      ctx.fill();

      ctx.fillStyle = '#fff';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      if (isComposed) {
        ctx.font = 'bold 14px sans-serif';
        ctx.fillStyle = '#c084fc'; // Purple indicating composition
        ctx.fillText('Composed: f(g(t))', 35, 30);
        ctx.fillStyle = '#fff';
        ctx.font = '13px monospace';
        ctx.fillText(`Time  (t) = ${t}s`, 35, 55);
        ctx.fillText(`Alt   (h) = ${gt}m`, 35, 70);
        ctx.fillText(`Temp f(h) = ${fh.toFixed(1)}°C`, 35, 85);
      } else {
        ctx.font = 'bold 14px sans-serif';
        ctx.fillText('Independent Machines', 35, 30);
        ctx.font = '13px monospace';
        ctx.fillText(`g(${t}) = ${gt}m`, 35, 55);
        ctx.fillText(`f(${h}) = ${fh.toFixed(1)}°C`, 35, 70);
      }
    }

    function update() {
      const isComposed = checkLink.checked;
      
      if (isComposed) {
        inputH.disabled = true;
        wrapH.item.classList.add('opacity-50', 'grayscale');
        wrapH.item.classList.replace('border-red-500', 'border-gray-300');
        // Force h to be g(t)
        const t = parseFloat(inputT.value);
        const gt = 1000 + 5 * t;
        inputH.value = gt;
      } else {
        inputH.disabled = false;
        wrapH.item.classList.remove('opacity-50', 'grayscale');
        wrapH.item.classList.replace('border-gray-300', 'border-red-500');
      }

      const t = parseFloat(inputT.value);
      const h = parseFloat(inputH.value);

      valT.textContent = t + ' s';
      valH.textContent = h + ' m';

      const gt = 1000 + 5 * t;
      const fh = 20 - 0.006 * h;

      outGt.value.textContent = gt.toFixed(0) + ' m';
      outFh.value.textContent = fh.toFixed(1) + ' °C';

      if (isComposed) {
        outFh.container.classList.replace('border-red-200', 'border-purple-300');
        outFh.container.classList.add('bg-purple-50');
        outFh.label.classList.replace('text-red-600', 'text-purple-700');
        outFh.label.innerHTML = 'f(g(t))<br><span class="text-purple-400 text-[10px]">Composed Temp</span>';
        
        outGt.container.classList.add('bg-purple-50');
        outGt.container.classList.replace('border-blue-200', 'border-purple-300');
      } else {
        outFh.container.classList.replace('border-purple-300', 'border-red-200');
        outFh.container.classList.remove('bg-purple-50');
        outFh.label.classList.replace('text-purple-700', 'text-red-600');
        outFh.label.innerHTML = 'f(h)<br><span class="text-gray-400 text-[10px]">Sensor Temp</span>';

        outGt.container.classList.remove('bg-purple-50');
        outGt.container.classList.replace('border-purple-300', 'border-blue-200');
      }

      draw(t, h, isComposed);
    }

    // Initialize HTML5 canvas polyfills for rounded rect if missing
    if (!CanvasRenderingContext2D.prototype.roundRect) {
      CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h, r) {
        if (w < 2 * r) r = w / 2;
        if (h < 2 * r) r = h / 2;
        this.beginPath();
        this.moveTo(x + r, y);
        this.arcTo(x + w, y, x + w, y + h, r);
        this.arcTo(x + w, y + h, x, y + h, r);
        this.arcTo(x, y + h, x, y, r);
        this.arcTo(x, y, x + w, y, r);
        this.closePath();
        return this;
      }
    }

    checkLink.addEventListener('change', update);
    inputT.addEventListener('input', update);
    inputH.addEventListener('input', update);

    // Initial draw
    // Using a tiny timeout to ensure fonts load before drawing, though mostly native fonts are used
    setTimeout(update, 10);

    return root;
  }


  function renderPredict(block) {
    const div = document.createElement('div');

    const prompt = document.createElement('p');
    prompt.textContent = block.prompt || 'Make your prediction.';
    div.appendChild(prompt);

    const components = block.components || {};
    const values = {};

    if (components.direction) {
      const row = document.createElement('div');
      row.className = 'mt-12';
      const label = document.createElement('div');
      label.textContent = 'Direction';
      row.appendChild(label);

      const select = document.createElement('select');
      select.className = 'form-select';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Select...';
      select.appendChild(placeholder);

      (components.direction.options || []).forEach(opt => {
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = opt;
        select.appendChild(option);
      });

      row.appendChild(select);
      div.appendChild(row);
      values.direction = select;
    }

    const magnitudeFields = Object.entries(components).filter(([key, cfg]) => {
      return key.startsWith('magnitude') && cfg && cfg.format === 'scientific_notation';
    });

    const sciInputs = [];
    magnitudeFields.forEach(([key, cfg]) => {
      const row = document.createElement('div');
      row.className = 'calculate-input-row mt-12';

      const label = document.createElement('label');
      label.textContent = cfg.label || key;
      row.appendChild(label);

      const sci = makeScientificNotationInput('1.00', '0');
      row.appendChild(sci.wrap);
      div.appendChild(row);

      sciInputs.push({ key, mantissa: sci.mantissa, exponent: sci.exponent, required: !!cfg.required });
    });

    if (components.confidence) {
      const row = document.createElement('div');
      row.className = 'mt-12';
      const label = document.createElement('div');
      label.textContent = 'Confidence';
      row.appendChild(label);

      const select = document.createElement('select');
      select.className = 'form-select';
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = 'Select...';
      select.appendChild(placeholder);

      (components.confidence.options || []).forEach(opt => {
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = opt;
        select.appendChild(option);
      });

      row.appendChild(select);
      div.appendChild(row);
      values.confidence = select;
    }

    const feedback = document.createElement('div');
    feedback.className = 'mt-12';
    div.appendChild(feedback);

    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn btn-primary mt-12';
    submitBtn.textContent = block.locked ? 'Submit (Locked)' : 'Submit';
    submitBtn.addEventListener('click', () => {
      if (values.direction && components.direction.required && !values.direction.value) {
        feedback.innerHTML = '<div class="feedback feedback-incorrect">Choose a direction.</div>';
        return;
      }
      if (values.confidence && components.confidence.required && !values.confidence.value) {
        feedback.innerHTML = '<div class="feedback feedback-incorrect">Choose a confidence level.</div>';
        return;
      }

      const predictions = {};
      for (const field of sciInputs) {
        const value = parseScientificNotation(field.mantissa, field.exponent);
        if (field.required && value === null) {
          feedback.innerHTML = '<div class="feedback feedback-incorrect">Enter mantissa and exponent for all required magnitudes.</div>';
          return;
        }
        predictions[field.key] = value;
      }

      blockState[block.id].prediction = {
        direction: values.direction ? values.direction.value : null,
        confidence: values.confidence ? values.confidence.value : null,
        magnitudes: predictions,
        submitted_at: Date.now()
      };

      if (block.locked) {
        if (values.direction) values.direction.disabled = true;
        if (values.confidence) values.confidence.disabled = true;
        sciInputs.forEach(field => {
          field.mantissa.disabled = true;
          field.exponent.disabled = true;
        });
      }

      submitBtn.disabled = true;
      feedback.innerHTML = '<div class="feedback feedback-correct">Prediction saved.</div>';
      markComplete(block.id, div);
    });
    div.appendChild(submitBtn);

    return div;
  }

  function renderDiscover(block) {
    const div = document.createElement('div');

    const prompt = document.createElement('p');
    prompt.textContent = block.prompt || 'Discover patterns from the data.';
    div.appendChild(prompt);

    if (block.data_table && Array.isArray(block.data_table.columns)) {
      let rows = Array.isArray(block.data_table.sample_values) ? block.data_table.sample_values : [];
      if ((!rows || rows.length === 0) && block.data_table.source === 'exploration_data' && Array.isArray(lesson.blocks)) {
        const currentIdx = lesson.blocks.findIndex(b => b.id === block.id);
        for (let i = currentIdx - 1; i >= 0; i--) {
          const candidate = lesson.blocks[i];
          const state = blockState[candidate.id];
          if (state && Array.isArray(state.exploration_data) && state.exploration_data.length > 0) {
            rows = state.exploration_data;
            break;
          }
        }
      }

      const tableWrap = document.createElement('div');
      tableWrap.className = 'mt-12';
      const table = document.createElement('table');
      table.className = 'data-table';

      const thead = document.createElement('thead');
      const headerRow = document.createElement('tr');
      block.data_table.columns.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col;
        headerRow.appendChild(th);
      });
      thead.appendChild(headerRow);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
      rows.forEach(rowData => {
        const tr = document.createElement('tr');
        block.data_table.columns.forEach(col => {
          const td = document.createElement('td');
          td.textContent = rowData[col] !== undefined ? String(rowData[col]) : '';
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      tableWrap.appendChild(table);
      div.appendChild(tableWrap);
    }

    if (Array.isArray(block.questions) && block.questions.length) {
      const q = document.createElement('ul');
      q.className = 'mt-12';
      block.questions.forEach(text => {
        const li = document.createElement('li');
        li.textContent = text;
        q.appendChild(li);
      });
      div.appendChild(q);
    }

    const response = document.createElement('textarea');
    response.className = 'input-textarea mt-12';
    response.rows = 5;
    response.placeholder = 'Write your pattern observations here...';
    div.appendChild(response);

    const feedback = document.createElement('div');
    feedback.className = 'mt-12';
    div.appendChild(feedback);

    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn btn-primary mt-12';
    submitBtn.textContent = 'Save observations';
    submitBtn.addEventListener('click', () => {
      const text = response.value.trim();
      if (text.length < 20) {
        feedback.innerHTML = '<div class="feedback feedback-incorrect">Add a little more detail before submitting.</div>';
        return;
      }
      blockState[block.id].observation = text;
      response.disabled = true;
      submitBtn.disabled = true;
      feedback.innerHTML = '<div class="feedback feedback-correct">Observations saved.</div>';
      markComplete(block.id, div);
    });
    div.appendChild(submitBtn);

    return div;
  }

  function renderCompare(block) {
    const div = document.createElement('div');
    const summary = document.createElement('div');
    summary.className = 'content';

    function renderSummary() {
      const predictionState = block.prediction_source ? blockState[block.prediction_source] : null;
      const prediction = predictionState && predictionState.prediction ? predictionState.prediction : null;

      const lines = [];
      if (block.comparison_prompt) {
        const safePrompt = block.comparison_prompt
          .replaceAll('[student_prediction]', prediction ? 'submitted' : 'not submitted');
        lines.push('<p>' + safePrompt + '</p>');
      }

      if (prediction) {
        const mags = prediction.magnitudes || {};
        lines.push('<p><strong>Your prediction:</strong> direction=' + esc(String(prediction.direction || 'n/a')) +
          ', f(g(5))=' + esc(String(mags.magnitude_f_g ?? 'n/a')) +
          ', g(f(5))=' + esc(String(mags.magnitude_g_f ?? 'n/a')) + '</p>');
      } else {
        lines.push('<p><strong>Prediction status:</strong> no saved prediction found.</p>');
      }

      if (block.gap_analysis && block.gap_analysis.feedback) {
        lines.push('<p>' + block.gap_analysis.feedback + '</p>');
      }
      summary.innerHTML = lines.join('');
    }

    renderSummary();
    div.appendChild(summary);

    const actions = document.createElement('div');
    actions.className = 'mt-12';

    const refreshBtn = document.createElement('button');
    refreshBtn.className = 'btn btn-secondary';
    refreshBtn.textContent = 'Refresh comparison';
    refreshBtn.addEventListener('click', renderSummary);

    const doneBtn = document.createElement('button');
    doneBtn.className = 'btn btn-primary';
    doneBtn.textContent = 'Continue';
    doneBtn.addEventListener('click', () => {
      doneBtn.disabled = true;
      markComplete(block.id, div);
    });

    actions.appendChild(refreshBtn);
    actions.appendChild(doneBtn);
    div.appendChild(actions);

    return div;
  }

  function renderReconcile(block) {
    const div = document.createElement('div');

    const prompt = document.createElement('p');
    prompt.textContent = block.prompt || 'Reflect in your own words.';
    div.appendChild(prompt);

    const textarea = document.createElement('textarea');
    textarea.className = 'input-textarea mt-12';
    textarea.rows = 6;
    textarea.placeholder = 'Write your explanation...';
    div.appendChild(textarea);

    const feedback = document.createElement('div');
    feedback.className = 'mt-12';
    div.appendChild(feedback);

    const minLength = block.min_length || 30;
    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn btn-primary mt-12';
    submitBtn.textContent = 'Submit reflection';
    submitBtn.addEventListener('click', () => {
      const text = textarea.value.trim();
      if (text.length < minLength) {
        feedback.innerHTML = '<div class="feedback feedback-incorrect">Write at least ' + minLength + ' characters.</div>';
        return;
      }
      blockState[block.id].reflection = text;
      textarea.disabled = true;
      submitBtn.disabled = true;
      feedback.innerHTML = '<div class="feedback feedback-correct">Reflection saved.</div>';
      markComplete(block.id, div);
    });
    div.appendChild(submitBtn);

    return div;
  }

  function renderVary(block) {
    return renderPractice(block);
  }

  function renderConnect(block) {
    const div = document.createElement('div');

    if (block.content_html) {
      const content = document.createElement('div');
      content.className = 'content';
      content.innerHTML = block.content_html;
      div.appendChild(content);
      renderKaTeX(content);
    }

    const doneBtn = document.createElement('button');
    doneBtn.className = 'btn btn-primary mt-12';
    doneBtn.textContent = 'Finish lesson';
    doneBtn.addEventListener('click', () => {
      doneBtn.disabled = true;
      markComplete(block.id, div);
    });
    div.appendChild(doneBtn);

    return div;
  }

  function renderUnsupportedBlock(block) {
    const div = document.createElement('div');
    div.className = 'content';
    div.innerHTML = '<p>Unsupported block type: <strong>' + esc(block.type) + '</strong></p>';

    const doneBtn = document.createElement('button');
    doneBtn.className = 'btn btn-secondary mt-12';
    doneBtn.textContent = 'Mark done';
    doneBtn.addEventListener('click', () => {
      doneBtn.disabled = true;
      markComplete(block.id, div);
    });
    div.appendChild(doneBtn);
    return div;
  }

  // ── Track Simulation (canvas-physics) ──
  function renderTrackSimulation(block) {
    const cfg = block.simulation_config || {};
    const root = document.createElement('div');
    root.className = 'track-simulation mt-12';

    const canvas = document.createElement('canvas');
    canvas.width = 800;
    canvas.height = 400;
    canvas.style.cssText = 'display:block;max-width:100%;height:auto;margin:0 auto;border:1px solid #e2e8f0;border-radius:12px;background:#fafafa;cursor:crosshair;';
    root.appendChild(canvas);

    const sim = createTrackSimulation(canvas, {
      gravity: cfg.gravity || 500,
      friction: cfg.friction || 0.3,
      ballRadius: cfg.ball_radius || 10,
      showSpeed: cfg.show_speed !== false,
      showTangent: cfg.show_tangent || false,
      onUpdate: function(state) {
        blockState[block.id] = blockState[block.id] || {};
        blockState[block.id].speed = state.speed;
        blockState[block.id].slopeAngle = state.slopeAngle;
        blockState[block.id].position = state.position;
      }
    });

    // Controls
    const controls = document.createElement('div');
    controls.style.cssText = 'display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin:12px 0;';

    const drawBtn = document.createElement('button');
    drawBtn.className = 'btn btn-secondary';
    drawBtn.textContent = 'Draw';
    drawBtn.addEventListener('click', () => {
      sim.reset();
      canvas.style.cursor = 'crosshair';
      drawBtn.classList.add('active');
      rollBtn.classList.remove('active');
    });

    const rollBtn = document.createElement('button');
    rollBtn.className = 'btn btn-primary';
    rollBtn.textContent = 'Roll';
    rollBtn.addEventListener('click', () => {
      if (!sim.hasTrack()) return;
      sim.setMode('simulate');
      canvas.style.cursor = 'default';
      rollBtn.classList.add('active');
      drawBtn.classList.remove('active');
    });

    const resetBtn = document.createElement('button');
    resetBtn.className = 'btn btn-secondary';
    resetBtn.textContent = 'Reset';
    resetBtn.addEventListener('click', () => {
      sim.reset();
      canvas.style.cursor = 'crosshair';
      drawBtn.classList.add('active');
      rollBtn.classList.remove('active');
    });

    controls.appendChild(drawBtn);
    controls.appendChild(rollBtn);
    controls.appendChild(resetBtn);
    root.appendChild(controls);

    return root;
  }

  // ── Globe Tossing Simulation ──
  function renderGlobeTossingSimulation(block) {
    const cfg = block.simulation_config || {};
    const hasPreset = !!cfg.preset;
    const hasPriorControls = !!(cfg.controls && cfg.controls.prior_controls);
    const hasTossButton = !hasPreset && cfg.controls && cfg.controls.toss_button;
    const tossOptions = (cfg.controls && cfg.controls.tosses_per_click) || [1];
    const gridPoints = (cfg.belief_curve && cfg.belief_curve.grid_points) || 1000;

    // ── State ──
    const st = {
      tosses: 0, water: 0, land: 0,
      dots: [],
      trueWaterFraction: 0.7,
      priorAlpha: 1, priorBeta: 1
    };
    blockState[block.id] = blockState[block.id] || {};
    Object.assign(blockState[block.id], st);

    // ── Math ──
    function computePosterior(alpha, beta, k, n) {
      const grid = new Float64Array(gridPoints);
      const a = alpha + k - 1;
      const b = beta + (n - k) - 1;
      let maxLog = -Infinity;
      for (let i = 1; i < gridPoints - 1; i++) {
        const p = i / (gridPoints - 1);
        const logVal = a * Math.log(p) + b * Math.log(1 - p);
        grid[i] = logVal;
        if (logVal > maxLog) maxLog = logVal;
      }
      grid[0] = 0; grid[gridPoints - 1] = 0;
      let sum = 0;
      for (let i = 1; i < gridPoints - 1; i++) {
        grid[i] = Math.exp(grid[i] - maxLog);
        sum += grid[i];
      }
      const dp = 1 / (gridPoints - 1);
      const norm = sum * dp;
      if (norm > 0) for (let i = 0; i < gridPoints; i++) grid[i] /= norm;
      return grid;
    }

    function computeInterval89(posterior) {
      const dp = 1 / (gridPoints - 1);
      let cumSum = 0;
      let lo = 0, hi = 1;
      for (let i = 0; i < gridPoints; i++) {
        cumSum += posterior[i] * dp;
        if (lo === 0 && cumSum >= 0.055) lo = i / (gridPoints - 1);
        if (cumSum >= 0.945) { hi = i / (gridPoints - 1); break; }
      }
      return { lo, hi, width: hi - lo };
    }

    // ── DOM ──
    const root = document.createElement('div');
    root.className = 'globe-tossing mt-12';

    // Planet canvas
    const planetW = 400, planetH = 400;
    const planetCanvas = document.createElement('canvas');
    planetCanvas.width = planetW; planetCanvas.height = planetH;
    planetCanvas.style.cssText = 'display:block;max-width:100%;height:auto;margin:0 auto;border-radius:12px;';
    const pctx = planetCanvas.getContext('2d');
    root.appendChild(planetCanvas);

    // Controls row
    const controlsRow = document.createElement('div');
    controlsRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:10px;justify-content:center;align-items:center;margin:16px 0;';

    if (hasTossButton) {
      tossOptions.forEach(count => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-primary';
        btn.textContent = 'Toss ' + count;
        btn.addEventListener('click', () => performToss(count));
        controlsRow.appendChild(btn);
      });
    }

    // Prior sliders (B1-B2)
    let centerSlider, strengthSlider, centerVal, strengthVal;
    if (hasPriorControls) {
      const pc = cfg.controls.prior_controls;

      const centerGroup = document.createElement('div');
      centerGroup.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:2px;';
      const centerLabel = document.createElement('label');
      centerLabel.style.cssText = 'font-size:0.78rem;text-transform:uppercase;color:#475569;font-weight:700;';
      centerLabel.textContent = pc.starting_center.label;
      centerSlider = document.createElement('input');
      centerSlider.type = 'range'; centerSlider.min = '0.01'; centerSlider.max = '0.99';
      centerSlider.step = '0.01'; centerSlider.value = String(pc.starting_center.default);
      centerSlider.style.cssText = 'width:120px;accent-color:#6366f1;';
      centerVal = document.createElement('span');
      centerVal.style.cssText = 'font-size:0.85rem;font-weight:600;color:#1e293b;';
      centerVal.textContent = pc.starting_center.default;
      centerGroup.appendChild(centerLabel);
      centerGroup.appendChild(centerSlider);
      centerGroup.appendChild(centerVal);
      controlsRow.appendChild(centerGroup);

      const strGroup = document.createElement('div');
      strGroup.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:2px;';
      const strLabel = document.createElement('label');
      strLabel.style.cssText = 'font-size:0.78rem;text-transform:uppercase;color:#475569;font-weight:700;';
      strLabel.textContent = pc.starting_strength.label;
      strengthSlider = document.createElement('input');
      strengthSlider.type = 'range'; strengthSlider.min = String(pc.starting_strength.range[0]);
      strengthSlider.max = String(pc.starting_strength.range[1]);
      strengthSlider.step = '1'; strengthSlider.value = String(pc.starting_strength.default);
      strengthSlider.style.cssText = 'width:120px;accent-color:#6366f1;';
      strengthVal = document.createElement('span');
      strengthVal.style.cssText = 'font-size:0.85rem;font-weight:600;color:#1e293b;';
      strengthVal.textContent = pc.starting_strength.default;
      strGroup.appendChild(strLabel);
      strGroup.appendChild(strengthSlider);
      strGroup.appendChild(strengthVal);
      controlsRow.appendChild(strGroup);

      function onPriorChange() {
        const c = parseFloat(centerSlider.value);
        const s = parseFloat(strengthSlider.value);
        centerVal.textContent = c.toFixed(2);
        strengthVal.textContent = s;
        const bs = blockState[block.id];
        bs.priorAlpha = Math.max(0.01, c * s);
        bs.priorBeta = Math.max(0.01, (1 - c) * s);
        bs.tosses = 0; bs.water = 0; bs.land = 0; bs.dots = [];
        redraw();
      }
      centerSlider.addEventListener('input', onPriorChange);
      strengthSlider.addEventListener('input', onPriorChange);
    }

    root.appendChild(controlsRow);

    // Belief curve canvas
    const curveW = 600, curveH = 220;
    const curveCanvas = document.createElement('canvas');
    curveCanvas.width = curveW; curveCanvas.height = curveH;
    curveCanvas.style.cssText = 'display:block;max-width:100%;height:auto;margin:0 auto;border:1px solid #e2e8f0;border-radius:8px;background:#fafafa;';
    const cctx = curveCanvas.getContext('2d');
    root.appendChild(curveCanvas);

    // Stats row
    const statsRow = document.createElement('div');
    statsRow.style.cssText = 'display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px;';
    function makeStat(label, color) {
      const tile = document.createElement('div');
      tile.style.cssText = 'border:1px solid #cbd5e1;border-radius:6px;padding:8px 10px;background:#fff;text-align:center;';
      const k = document.createElement('div');
      k.style.cssText = 'font-size:0.75rem;color:#64748b;text-transform:uppercase;letter-spacing:0.05em;';
      k.textContent = label;
      const v = document.createElement('div');
      v.style.cssText = 'font-size:1.1rem;font-weight:700;color:' + (color || '#0f172a') + ';';
      v.textContent = '0';
      tile.appendChild(k); tile.appendChild(v);
      return { tile, v };
    }
    const statTosses = makeStat('Tosses');
    const statWater = makeStat('Water', '#2563eb');
    const statLand = makeStat('Land', '#92400e');
    const statWidth = makeStat('89% Width', '#6366f1');
    [statTosses, statWater, statLand, statWidth].forEach(s => statsRow.appendChild(s.tile));
    root.appendChild(statsRow);

    // ── Planet drawing ──
    const planetCX = planetW / 2, planetCY = planetH / 2, planetR = 150;

    function drawPlanet() {
      pctx.clearRect(0, 0, planetW, planetH);
      // Space background
      pctx.fillStyle = '#0f172a';
      pctx.fillRect(0, 0, planetW, planetH);
      // Planet
      const grad = pctx.createRadialGradient(planetCX - 30, planetCY - 30, 10, planetCX, planetCY, planetR);
      grad.addColorStop(0, '#94a3b8');
      grad.addColorStop(0.7, '#64748b');
      grad.addColorStop(1, '#334155');
      pctx.beginPath();
      pctx.arc(planetCX, planetCY, planetR, 0, Math.PI * 2);
      pctx.fillStyle = grad;
      pctx.fill();
      // Dots
      const bs = blockState[block.id];
      const dotR = Math.max(1.5, 4 - Math.log10(Math.max(1, bs.dots.length)) * 0.8);
      bs.dots.forEach(d => {
        const x = planetCX + d.dx;
        const y = planetCY + d.dy;
        pctx.beginPath();
        pctx.arc(x, y, dotR, 0, Math.PI * 2);
        pctx.fillStyle = d.isWater ? '#3b82f6' : '#a16207';
        pctx.fill();
      });
      // Atmosphere rim
      pctx.beginPath();
      pctx.arc(planetCX, planetCY, planetR + 2, 0, Math.PI * 2);
      pctx.strokeStyle = 'rgba(148,163,184,0.3)';
      pctx.lineWidth = 4;
      pctx.stroke();
    }

    // ── Curve drawing ──
    const plotL = 55, plotR = curveW - 20, plotT = 15, plotB = curveH - 35;
    const plotW = plotR - plotL, plotH = plotB - plotT;

    function drawCurve(posterior, interval) {
      cctx.clearRect(0, 0, curveW, curveH);
      cctx.fillStyle = '#fafafa';
      cctx.fillRect(0, 0, curveW, curveH);

      // Find max for scaling
      let maxVal = 0;
      for (let i = 0; i < gridPoints; i++) if (posterior[i] > maxVal) maxVal = posterior[i];
      if (maxVal === 0) maxVal = 1;

      // Shaded 89% interval
      const iLoX = plotL + interval.lo * plotW;
      const iHiX = plotL + interval.hi * plotW;
      cctx.beginPath();
      cctx.moveTo(iLoX, plotB);
      for (let px = Math.floor(iLoX); px <= Math.ceil(iHiX); px++) {
        const p = (px - plotL) / plotW;
        const idx = Math.min(gridPoints - 1, Math.max(0, Math.round(p * (gridPoints - 1))));
        const y = plotB - (posterior[idx] / maxVal) * plotH;
        cctx.lineTo(px, y);
      }
      cctx.lineTo(iHiX, plotB);
      cctx.closePath();
      cctx.fillStyle = 'rgba(99,102,241,0.18)';
      cctx.fill();

      // Curve line
      cctx.beginPath();
      for (let i = 0; i < gridPoints; i++) {
        const x = plotL + (i / (gridPoints - 1)) * plotW;
        const y = plotB - (posterior[i] / maxVal) * plotH;
        if (i === 0) cctx.moveTo(x, y); else cctx.lineTo(x, y);
      }
      cctx.strokeStyle = '#4338ca';
      cctx.lineWidth = 2;
      cctx.stroke();

      // Axes
      cctx.strokeStyle = '#94a3b8';
      cctx.lineWidth = 1;
      cctx.beginPath();
      cctx.moveTo(plotL, plotT); cctx.lineTo(plotL, plotB); cctx.lineTo(plotR, plotB);
      cctx.stroke();

      // X ticks
      cctx.fillStyle = '#64748b';
      cctx.font = '11px system-ui, sans-serif';
      cctx.textAlign = 'center';
      for (let v = 0; v <= 1; v += 0.2) {
        const x = plotL + v * plotW;
        cctx.beginPath(); cctx.moveTo(x, plotB); cctx.lineTo(x, plotB + 5); cctx.stroke();
        cctx.fillText(v.toFixed(1), x, plotB + 17);
      }
      cctx.textAlign = 'center';
      cctx.fillText('Water fraction p', plotL + plotW / 2, curveH - 2);

      // Y label
      cctx.save();
      cctx.translate(12, plotT + plotH / 2);
      cctx.rotate(-Math.PI / 2);
      cctx.textAlign = 'center';
      cctx.fillText('Belief density', 0, 0);
      cctx.restore();

      // Width annotation
      if (interval.width > 0 && interval.width < 1) {
        const bracketY = plotT + plotH * 0.15;
        cctx.strokeStyle = '#6366f1';
        cctx.lineWidth = 1.5;
        cctx.beginPath();
        cctx.moveTo(iLoX, bracketY - 4); cctx.lineTo(iLoX, bracketY);
        cctx.lineTo(iHiX, bracketY);
        cctx.lineTo(iHiX, bracketY - 4);
        cctx.stroke();
        cctx.fillStyle = '#6366f1';
        cctx.font = 'bold 12px system-ui, sans-serif';
        cctx.textAlign = 'center';
        cctx.fillText('Width: ' + interval.width.toFixed(3), (iLoX + iHiX) / 2, bracketY - 8);
      }
    }

    // ── Toss logic ──
    function performToss(count) {
      const bs = blockState[block.id];
      for (let i = 0; i < count; i++) {
        const angle = Math.random() * 2 * Math.PI;
        const r = Math.sqrt(Math.random()) * planetR;
        const isWater = Math.random() < bs.trueWaterFraction;
        bs.dots.push({ dx: Math.cos(angle) * r, dy: Math.sin(angle) * r, isWater });
        bs.tosses++;
        if (isWater) bs.water++; else bs.land++;
      }
      redraw();
    }

    // ── Redraw ──
    function redraw() {
      const bs = blockState[block.id];
      const posterior = computePosterior(bs.priorAlpha, bs.priorBeta, bs.water, bs.tosses);
      const interval = bs.tosses > 0 ? computeInterval89(posterior) : { lo: 0, hi: 1, width: 1 };

      drawPlanet();
      drawCurve(posterior, interval);

      statTosses.v.textContent = bs.tosses;
      statWater.v.textContent = bs.water;
      statLand.v.textContent = bs.land;
      statWidth.v.textContent = bs.tosses > 0 ? interval.width.toFixed(3) : '--';

      bs.belief_curve_width = interval.width;
      bs.exploration_data = {
        tosses: bs.tosses, water: bs.water, land: bs.land,
        belief_curve_width: interval.width
      };
    }

    // ── Preset init (B1-B3) ──
    if (hasPreset) {
      const bs = blockState[block.id];
      bs.tosses = cfg.preset.tosses;
      bs.water = cfg.preset.water;
      bs.land = cfg.preset.land;
      if (cfg.preset.prior === 'uniform') { bs.priorAlpha = 1; bs.priorBeta = 1; }
      for (let i = 0; i < bs.tosses; i++) {
        const angle = Math.random() * 2 * Math.PI;
        const r = Math.sqrt(Math.random()) * planetR;
        const isWater = i < bs.water;
        bs.dots.push({ dx: Math.cos(angle) * r, dy: Math.sin(angle) * r, isWater });
      }
    }

    setTimeout(redraw, 10);
    return root;
  }

  // ── Spring Animation ──
  function initSpringAnimation(container) {
    const canvas = document.createElement('canvas');
    canvas.className = 'spring-canvas';
    canvas.width = 600;
    canvas.height = 200;
    container.appendChild(canvas);

    // Controls bar
    const controls = document.createElement('div');
    controls.className = 'spring-controls';

    // Play/pause
    const playBtn = document.createElement('button');
    playBtn.className = 'btn btn-secondary spring-ctrl-btn';
    playBtn.textContent = '\u23f8 Pause';
    controls.appendChild(playBtn);

    // Restart
    const restartBtn = document.createElement('button');
    restartBtn.className = 'btn btn-secondary spring-ctrl-btn';
    restartBtn.textContent = '\u21bb Reset';
    controls.appendChild(restartBtn);

    // k slider
    const kGroup = document.createElement('div');
    kGroup.className = 'spring-ctrl-group';
    kGroup.innerHTML = '<label>k (N/m)</label>';
    const kSlider = document.createElement('input');
    kSlider.type = 'range';
    kSlider.min = '2';
    kSlider.max = '60';
    kSlider.step = '1';
    kSlider.value = '15';
    const kVal = document.createElement('span');
    kVal.className = 'spring-ctrl-val';
    kVal.textContent = '15';
    kGroup.appendChild(kSlider);
    kGroup.appendChild(kVal);
    controls.appendChild(kGroup);

    // m slider
    const mGroup = document.createElement('div');
    mGroup.className = 'spring-ctrl-group';
    mGroup.innerHTML = '<label>m (kg)</label>';
    const mSlider = document.createElement('input');
    mSlider.type = 'range';
    mSlider.min = '0.1';
    mSlider.max = '3';
    mSlider.step = '0.1';
    mSlider.value = '0.3';
    const mVal = document.createElement('span');
    mVal.className = 'spring-ctrl-val';
    mVal.textContent = '0.3';
    mGroup.appendChild(mSlider);
    mGroup.appendChild(mVal);
    controls.appendChild(mGroup);

    // omega readout
    const omegaReadout = document.createElement('div');
    omegaReadout.className = 'spring-omega-readout';
    controls.appendChild(omegaReadout);

    container.appendChild(controls);

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    function resize() {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = 200 * dpr;
      canvas.style.height = '200px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    window.addEventListener('resize', resize);

    const W = () => canvas.width / dpr;
    const H = () => 200;
    const wallX = 40;
    const restX = () => W() * 0.5;
    const massR = 20;
    let k = 15, m = 0.3;
    let omega = Math.sqrt(k / m);
    let amplitude = 80;
    let phase = 0;
    let t = 0;
    let paused = false;
    let dragging = false;
    let dragX = 0;

    function updateOmega() {
      omega = Math.sqrt(k / m);
      omegaReadout.innerHTML = '\u03c9 = ' + omega.toFixed(2) + ' rad/s';
    }
    updateOmega();

    function onParamChange() {
      // Freeze at current visual position, restart with new params
      const currentX = restX() + amplitude * Math.cos(omega * t + phase);
      const newOmega = Math.sqrt(k / m);
      amplitude = currentX - restX();
      phase = 0;
      t = 0;
      omega = newOmega;
      omegaReadout.innerHTML = '\u03c9 = ' + omega.toFixed(2) + ' rad/s';
    }

    kSlider.addEventListener('input', () => {
      k = parseFloat(kSlider.value);
      kVal.textContent = k;
      onParamChange();
    });
    mSlider.addEventListener('input', () => {
      m = parseFloat(mSlider.value);
      mVal.textContent = m.toFixed(1);
      onParamChange();
    });
    playBtn.addEventListener('click', () => {
      paused = !paused;
      playBtn.textContent = paused ? '\u25b6 Play' : '\u23f8 Pause';
    });
    restartBtn.addEventListener('click', () => {
      amplitude = 80;
      phase = 0;
      t = 0;
      paused = false;
      playBtn.textContent = '\u23f8 Pause';
    });

    function springPath(startX, endX, y, coils) {
      ctx.beginPath();
      ctx.moveTo(startX, y);
      const dx = endX - startX;
      const coilW = dx / (coils * 2 + 2);
      let cx = startX + coilW;
      for (let i = 0; i < coils; i++) {
        ctx.lineTo(cx, y - 12);
        cx += coilW;
        ctx.lineTo(cx, y + 12);
        cx += coilW;
      }
      ctx.lineTo(endX, y);
      ctx.strokeStyle = '#6b7280';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    function draw() {
      const w = W(), h = H();
      const cy = h / 2;
      ctx.clearRect(0, 0, w, h);

      let massX;
      if (dragging) {
        massX = dragX;
      } else {
        massX = restX() + amplitude * Math.cos(omega * t + phase);
      }

      // Wall
      ctx.fillStyle = '#9ca3af';
      ctx.fillRect(0, cy - 50, wallX, 100);
      ctx.strokeStyle = '#6b7280';
      ctx.lineWidth = 1;
      for (let i = -50; i < 100; i += 8) {
        ctx.beginPath();
        ctx.moveTo(wallX, cy + i);
        ctx.lineTo(wallX - 10, cy + i + 10);
        ctx.stroke();
      }

      // Spring
      springPath(wallX, massX - massR, cy, 12);

      // Mass
      ctx.fillStyle = dragging ? '#2563eb' : '#3b82f6';
      ctx.strokeStyle = '#1d4ed8';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.roundRect(massX - massR, cy - massR, massR * 2, massR * 2, 4);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = 'white';
      ctx.font = 'bold 14px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('m', massX, cy);

      // Equilibrium line
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = '#d1d5db';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(restX(), cy - 40);
      ctx.lineTo(restX(), cy + 40);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = '#9ca3af';
      ctx.font = '12px sans-serif';
      ctx.fillText('x = 0', restX(), cy + 55);

      // Displacement arrow
      const disp = massX - restX();
      if (Math.abs(disp) > 5) {
        ctx.strokeStyle = '#dc2626';
        ctx.fillStyle = '#dc2626';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(restX(), cy + 35);
        ctx.lineTo(massX, cy + 35);
        ctx.stroke();
        const dir = disp > 0 ? 1 : -1;
        ctx.beginPath();
        ctx.moveTo(massX, cy + 35);
        ctx.lineTo(massX - dir * 8, cy + 30);
        ctx.lineTo(massX - dir * 8, cy + 40);
        ctx.closePath();
        ctx.fill();
        ctx.font = 'italic 13px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('x', (restX() + massX) / 2, cy + 48);
      }

      // Force arrow
      if (Math.abs(disp) > 5) {
        const forceScale = -0.4;
        const forceLen = disp * forceScale;
        ctx.strokeStyle = '#16a34a';
        ctx.fillStyle = '#16a34a';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(massX, cy - 30);
        ctx.lineTo(massX + forceLen, cy - 30);
        ctx.stroke();
        const fdir = forceLen > 0 ? 1 : -1;
        ctx.beginPath();
        ctx.moveTo(massX + forceLen, cy - 30);
        ctx.lineTo(massX + forceLen - fdir * 8, cy - 35);
        ctx.lineTo(massX + forceLen - fdir * 8, cy - 25);
        ctx.closePath();
        ctx.fill();
        ctx.font = 'italic 13px sans-serif';
        ctx.fillText('F', massX + forceLen / 2, cy - 40);
      }

      if (!dragging && !paused) {
        t += 0.02;
      }
      requestAnimationFrame(draw);
    }

    // Drag interaction
    function getCanvasX(e) {
      const rect = canvas.getBoundingClientRect();
      const clientX = e.touches ? e.touches[0].clientX : e.clientX;
      return clientX - rect.left;
    }

    function isOnMass(cx) {
      const massX = dragging ? dragX : restX() + amplitude * Math.cos(omega * t + phase);
      return Math.abs(cx - massX) < massR + 10;
    }

    canvas.addEventListener('mousedown', e => {
      if (isOnMass(getCanvasX(e))) {
        dragging = true;
        dragX = getCanvasX(e);
        canvas.style.cursor = 'grabbing';
      }
    });
    canvas.addEventListener('touchstart', e => {
      if (isOnMass(getCanvasX(e))) {
        dragging = true;
        dragX = getCanvasX(e);
        e.preventDefault();
      }
    }, { passive: false });

    function onMove(e) {
      if (!dragging) return;
      dragX = Math.max(wallX + massR + 20, Math.min(getCanvasX(e), W() - massR));
      e.preventDefault();
    }
    canvas.addEventListener('mousemove', onMove);
    canvas.addEventListener('touchmove', onMove, { passive: false });

    function onRelease() {
      if (!dragging) return;
      amplitude = dragX - restX();
      phase = 0;
      t = 0;
      dragging = false;
      canvas.style.cursor = 'grab';
    }
    canvas.addEventListener('mouseup', onRelease);
    canvas.addEventListener('mouseleave', onRelease);
    canvas.addEventListener('touchend', onRelease);

    canvas.style.cursor = 'grab';
    draw();
  }

  // ── Derive Block ──
  function renderDerive(block) {
    const div = document.createElement('div');

    // Prompt
    const prompt = document.createElement('p');
    prompt.textContent = block.prompt;
    div.appendChild(prompt);

    // Starting equation — always visible
    const startLabel = document.createElement('div');
    startLabel.className = 'derive-start-label';
    startLabel.textContent = 'Starting equation:';
    div.appendChild(startLabel);

    const startEqDiv = document.createElement('div');
    startEqDiv.className = 'derive-current-equation derive-start-equation';
    startEqDiv.innerHTML = '$$' + block.starting_equation + '$$';
    div.appendChild(startEqDiv);

    // Steps history container — all revealed steps shown here
    const historyDiv = document.createElement('div');
    historyDiv.className = 'derive-history';
    div.appendChild(historyDiv);

    // Navigation controls at the bottom
    const navDiv = document.createElement('div');
    navDiv.className = 'derive-nav';

    const backBtn = document.createElement('button');
    backBtn.className = 'btn btn-secondary derive-nav-btn';
    backBtn.textContent = '\u2190 Back';
    backBtn.disabled = true;

    const stepIndicator = document.createElement('span');
    stepIndicator.className = 'derive-step-indicator';
    stepIndicator.textContent = 'Step 0 of ' + block.steps.length;

    const nextBtn = document.createElement('button');
    nextBtn.className = 'btn btn-primary derive-nav-btn';
    nextBtn.textContent = 'Next Step \u2192';

    navDiv.appendChild(backBtn);
    navDiv.appendChild(stepIndicator);
    navDiv.appendChild(nextBtn);
    div.appendChild(navDiv);

    let currentStep = 0;  // next step to reveal (0 = none revealed yet)

    function updateView() {
      // Update indicator
      stepIndicator.textContent = 'Step ' + currentStep + ' of ' + block.steps.length;

      // Back is enabled if any steps are showing
      backBtn.disabled = currentStep === 0;

      // Next is enabled if there are more steps
      if (currentStep >= block.steps.length) {
        nextBtn.disabled = true;
        nextBtn.textContent = 'Done';
      } else {
        nextBtn.disabled = false;
        nextBtn.textContent = 'Next Step \u2192';
      }

      // Rebuild history: show steps 0..currentStep-1
      historyDiv.innerHTML = '';
      for (let i = 0; i < currentStep; i++) {
        const step = block.steps[i];
        const stepEl = document.createElement('div');
        stepEl.className = 'derive-step completed';

        const num = document.createElement('div');
        num.className = 'derive-step-number';
        num.textContent = i + 1;

        const content = document.createElement('div');
        content.className = 'derive-step-content';

        const instruction = document.createElement('div');
        instruction.className = 'derive-step-instruction';
        instruction.textContent = step.instruction;
        content.appendChild(instruction);

        const resultDiv = document.createElement('div');
        resultDiv.className = 'derive-step-result';
        resultDiv.innerHTML = '$$' + step.result_equation + '$$';
        content.appendChild(resultDiv);

        const explanationDiv = document.createElement('div');
        explanationDiv.className = 'derive-step-explanation';
        explanationDiv.innerHTML = step.explanation;
        content.appendChild(explanationDiv);

        stepEl.appendChild(num);
        stepEl.appendChild(content);
        historyDiv.appendChild(stepEl);
      }
      renderKaTeX(historyDiv);
    }

    nextBtn.addEventListener('click', () => {
      if (currentStep >= block.steps.length) return;
      currentStep++;
      updateView();

      // Check if derive is complete
      if (currentStep >= block.steps.length && !blockState[block.id].completed) {
        const complete = document.createElement('div');
        complete.className = 'derive-complete';
        complete.textContent = 'Derivation complete!';
        div.appendChild(complete);
        markComplete(block.id, div);
      }
    });

    backBtn.addEventListener('click', () => {
      if (currentStep > 0) {
        currentStep--;
        updateView();
      }
    });

    updateView();

    // Hints
    if (block.hints && block.hints.length > 0) {
      const hintsDiv = renderHints(block.hints);
      div.appendChild(hintsDiv);
    }

    return div;
  }

  // ── Calculate Block ──
  function renderCalculate(block) {
    const div = document.createElement('div');

    const prompt = document.createElement('p');
    prompt.textContent = block.prompt;
    div.appendChild(prompt);

    const inputRow = document.createElement('div');
    inputRow.className = 'calculate-input-row';

    const sciInput = document.createElement('div');
    sciInput.className = 'sci-notation-input';

    const mantissa = document.createElement('input');
    mantissa.type = 'number';
    mantissa.step = '0.01';
    mantissa.placeholder = '7.07';
    mantissa.setAttribute('aria-label', 'Mantissa');

    const timesTen = document.createElement('span');
    timesTen.className = 'times-ten';
    timesTen.innerHTML = '&times; 10';

    const exponent = document.createElement('input');
    exponent.type = 'number';
    exponent.step = '1';
    exponent.placeholder = '0';
    exponent.style.width = '50px';
    exponent.setAttribute('aria-label', 'Exponent');

    sciInput.appendChild(mantissa);
    sciInput.appendChild(timesTen);
    sciInput.appendChild(exponent);

    const unitsSpan = document.createElement('span');
    unitsSpan.className = 'units-label';
    unitsSpan.textContent = block.units || '';

    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = 'Check';

    inputRow.appendChild(sciInput);
    inputRow.appendChild(unitsSpan);
    inputRow.appendChild(submitBtn);
    div.appendChild(inputRow);

    const feedbackDiv = document.createElement('div');
    div.appendChild(feedbackDiv);

    // Enter key submits
    [mantissa, exponent].forEach(input => {
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') submitBtn.click();
      });
    });

    submitBtn.addEventListener('click', () => {
      const m = parseFloat(mantissa.value);
      const e = parseInt(exponent.value, 10);
      if (isNaN(m) || isNaN(e)) {
        feedbackDiv.innerHTML = '<div class="feedback feedback-incorrect">Enter both mantissa and exponent.</div>';
        return;
      }

      const userValue = m * Math.pow(10, e);
      const expected = block.expected_value;
      const relError = Math.abs(userValue - expected) / Math.abs(expected);
      const orderOfMagnitude = userValue > 0
        ? Math.abs(Math.floor(Math.log10(Math.abs(userValue))) - Math.floor(Math.log10(Math.abs(expected))))
        : Infinity;

      if (orderOfMagnitude > 1) {
        feedbackDiv.innerHTML = '<div class="feedback feedback-incorrect">Off by more than an order of magnitude. Check your units and calculation.</div>';
      } else if (relError < 0.15) {
        feedbackDiv.innerHTML = '<div class="feedback feedback-correct">Correct! ' + expected.toFixed(2) + ' ' + (block.units || '') + '</div>';
        if (block.solution_steps) {
          const sol = document.createElement('div');
          sol.className = 'solution-steps';
          sol.innerHTML = block.solution_steps.map(s => '<p>' + s + '</p>').join('');
          feedbackDiv.appendChild(sol);
          renderKaTeX(sol);
        }
        submitBtn.disabled = true;
        mantissa.disabled = true;
        exponent.disabled = true;
        markComplete(block.id, div);
      } else {
        feedbackDiv.innerHTML = '<div class="feedback feedback-incorrect">Not quite. Your answer: ' +
          userValue.toFixed(2) + '. Try again.</div>';
      }
    });

    return div;
  }

  // ── Code Block ──
  function renderCode(block) {
    const div = document.createElement('div');
    div.className = 'code-block';

    const prompt = document.createElement('p');
    prompt.textContent = block.prompt;
    div.appendChild(prompt);

    const editorContainer = document.createElement('div');
    editorContainer.className = 'mt-12';
    div.appendChild(editorContainer);

    // Create CodeMirror after DOM insertion
    setTimeout(() => {
      const cm = CodeMirror(editorContainer, {
        value: block.starter_code,
        mode: 'python',
        theme: 'monokai',
        lineNumbers: true,
        indentUnit: 4,
        viewportMargin: Infinity,
        lineWrapping: true
      });

      const controls = document.createElement('div');
      controls.className = 'code-controls';

      const runBtn = document.createElement('button');
      runBtn.className = 'btn btn-primary';
      runBtn.textContent = 'Run';

      const resetBtn = document.createElement('button');
      resetBtn.className = 'btn btn-secondary';
      resetBtn.textContent = 'Reset';

      const showSolutionBtn = document.createElement('button');
      showSolutionBtn.className = 'btn btn-secondary';
      showSolutionBtn.textContent = 'Show Solution';

      controls.appendChild(runBtn);
      controls.appendChild(resetBtn);
      if (block.solution_code) controls.appendChild(showSolutionBtn);
      div.appendChild(controls);

      const outputDiv = document.createElement('div');
      outputDiv.className = 'code-output hidden';
      div.appendChild(outputDiv);

      const plotDiv = document.createElement('div');
      plotDiv.className = 'code-plot';
      div.appendChild(plotDiv);

      const checksDiv = document.createElement('div');
      checksDiv.className = 'check-results';
      div.appendChild(checksDiv);

      runBtn.addEventListener('click', async () => {
        runBtn.disabled = true;
        runBtn.textContent = 'Running…';
        outputDiv.classList.remove('hidden');
        outputDiv.textContent = 'Waiting for Python…';
        outputDiv.style.color = '';
        plotDiv.innerHTML = '';
        checksDiv.innerHTML = '';

        await waitForPyodide();

        const code = cm.getValue();
        try {
          // Redirect stdout
          pyodide.runPython(`
import sys, io
sys.stdout = io.StringIO()
sys.stderr = io.StringIO()
          `);

          // Set up matplotlib for non-interactive backend
          pyodide.runPython(`
import matplotlib
matplotlib.use('AGG')
import matplotlib.pyplot as plt
plt.close('all')
          `);

          pyodide.runPython(code);

          // Capture stdout
          const stdout = pyodide.runPython('sys.stdout.getvalue()');
          const stderr = pyodide.runPython('sys.stderr.getvalue()');
          outputDiv.textContent = stdout + (stderr ? '\n' + stderr : '');
          if (!stdout && !stderr) outputDiv.textContent = '(no output)';

          // Capture plot if any
          const hasPlot = pyodide.runPython(`
import matplotlib.pyplot as plt
len(plt.get_fignums()) > 0
          `);
          if (hasPlot) {
            pyodide.runPython(`
import base64, io
buf = io.BytesIO()
plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
buf.seek(0)
_plot_b64 = base64.b64encode(buf.read()).decode()
plt.close('all')
            `);
            const b64 = pyodide.runPython('_plot_b64');
            const img = document.createElement('img');
            img.src = 'data:image/png;base64,' + b64;
            img.alt = 'Plot output';
            plotDiv.appendChild(img);
          }

          // Run checks
          if (block.checks) {
            let allPassed = true;
            block.checks.forEach(check => {
              const resultEl = document.createElement('div');
              resultEl.className = 'check-result';
              try {
                if (check.variable && check.expected_expr) {
                  const actual = pyodide.runPython(check.variable);
                  const expected = pyodide.runPython(check.expected_expr);
                  const diff = Math.abs(actual - expected);
                  if (diff <= (check.tolerance || 1e-6)) {
                    resultEl.className += ' check-pass';
                    resultEl.innerHTML = '&#10003; ' + esc(check.message || check.variable + ' is correct');
                  } else {
                    resultEl.className += ' check-fail';
                    resultEl.innerHTML = '&#10007; ' + esc(check.message || check.variable + ' is incorrect') +
                      ' (got ' + actual.toFixed(4) + ', expected ' + expected.toFixed(4) + ')';
                    allPassed = false;
                  }
                } else if (check.variable && check.max_value !== undefined) {
                  const actual = pyodide.runPython(check.variable);
                  if (actual <= check.max_value) {
                    resultEl.className += ' check-pass';
                    resultEl.innerHTML = '&#10003; ' + esc(check.message || 'Check passed') +
                      ' (value: ' + actual.toFixed(6) + ')';
                  } else {
                    resultEl.className += ' check-fail';
                    resultEl.innerHTML = '&#10007; ' + esc(check.message || 'Check failed') +
                      ' (value: ' + actual.toFixed(6) + ', max: ' + check.max_value + ')';
                    allPassed = false;
                  }
                }
              } catch (e) {
                resultEl.className += ' check-fail';
                resultEl.innerHTML = '&#10007; ' + esc(check.message || 'Check error') + ': ' + esc(e.message);
                allPassed = false;
              }
              checksDiv.appendChild(resultEl);
            });

            if (allPassed) {
              markComplete(block.id, div);
            }
          }
        } catch (e) {
          outputDiv.textContent = 'Error:\n' + e.message;
          outputDiv.style.color = '#ef4444';
        }

        runBtn.disabled = false;
        runBtn.textContent = 'Run';
      });

      resetBtn.addEventListener('click', () => {
        cm.setValue(block.starter_code);
        outputDiv.classList.add('hidden');
        plotDiv.innerHTML = '';
        checksDiv.innerHTML = '';
      });

      showSolutionBtn.addEventListener('click', () => {
        cm.setValue(block.solution_code);
      });
    }, 0);

    return div;
  }

  // ── Practice Block ──
  function renderPractice(block) {
    const div = document.createElement('div');

    const prompt = document.createElement('p');
    prompt.textContent = 'Get ' + block.required_consecutive_correct + ' correct in a row to complete this block.';
    div.appendChild(prompt);

    const progressDiv = document.createElement('div');
    progressDiv.className = 'practice-progress';
    div.appendChild(progressDiv);

    const problemDiv = document.createElement('div');
    problemDiv.className = 'practice-problem';
    div.appendChild(problemDiv);

    const inputRow = document.createElement('div');
    inputRow.className = 'calculate-input-row';

    const sciInput = document.createElement('div');
    sciInput.className = 'sci-notation-input';

    const mantissa = document.createElement('input');
    mantissa.type = 'number';
    mantissa.step = '0.01';
    mantissa.placeholder = 'mantissa';
    mantissa.setAttribute('aria-label', 'Mantissa');

    const timesTen = document.createElement('span');
    timesTen.className = 'times-ten';
    timesTen.innerHTML = '&times; 10';

    const exponent = document.createElement('input');
    exponent.type = 'number';
    exponent.step = '1';
    exponent.placeholder = 'exp';
    exponent.style.width = '50px';
    exponent.setAttribute('aria-label', 'Exponent');

    sciInput.appendChild(mantissa);
    sciInput.appendChild(timesTen);
    sciInput.appendChild(exponent);

    const unitsSpan = document.createElement('span');
    unitsSpan.className = 'units-label';
    unitsSpan.textContent = block.units || '';

    const submitBtn = document.createElement('button');
    submitBtn.className = 'btn btn-primary';
    submitBtn.textContent = 'Check';

    inputRow.appendChild(sciInput);
    inputRow.appendChild(unitsSpan);
    inputRow.appendChild(submitBtn);
    div.appendChild(inputRow);

    const feedbackDiv = document.createElement('div');
    div.appendChild(feedbackDiv);

    // Enter key submits
    [mantissa, exponent].forEach(input => {
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') submitBtn.click();
      });
    });

    let consecutiveCorrect = 0;
    let currentParams = {};
    const history = []; // { correct: bool }
    const required = block.required_consecutive_correct;

    function generateProblem() {
      const params = {};
      for (const [key, range] of Object.entries(block.parameter_ranges)) {
        // Round to 1 decimal
        params[key] = Math.round((range[0] + Math.random() * (range[1] - range[0])) * 10) / 10;
      }
      currentParams = params;

      let text = block.template;
      for (const [key, val] of Object.entries(params)) {
        text = text.replaceAll('{' + key + '}', val);
      }
      problemDiv.textContent = text;
      mantissa.value = '';
      exponent.value = '';
      feedbackDiv.innerHTML = '';
      mantissa.focus();
    }

    function updateProgress() {
      progressDiv.innerHTML = '';
      for (let i = 0; i < required; i++) {
        const dot = document.createElement('div');
        dot.className = 'practice-dot';
        if (i < consecutiveCorrect) dot.classList.add('correct');
        else if (i === consecutiveCorrect) dot.classList.add('current');
        progressDiv.appendChild(dot);
      }
    }

    submitBtn.addEventListener('click', () => {
      const m = parseFloat(mantissa.value);
      const e = parseInt(exponent.value, 10);
      if (isNaN(m) || isNaN(e)) {
        feedbackDiv.innerHTML = '<div class="feedback feedback-incorrect">Enter both mantissa and exponent.</div>';
        return;
      }

      const userValue = m * Math.pow(10, e);
      // Evaluate formula with current params
      const expected = evalFormula(block.answer_formula, currentParams);
      const relError = Math.abs(userValue - expected) / Math.abs(expected);

      if (relError < 0.15) {
        consecutiveCorrect++;
        history.push({ correct: true });
        feedbackDiv.innerHTML = '<div class="feedback feedback-correct">Correct! Answer: ' +
          expected.toFixed(2) + ' ' + (block.units || '') + '</div>';

        if (consecutiveCorrect >= required) {
          // Done!
          updateProgress();
          submitBtn.disabled = true;
          mantissa.disabled = true;
          exponent.disabled = true;
          markComplete(block.id, div);
          return;
        }
        updateProgress();
        setTimeout(generateProblem, 1200);
      } else {
        consecutiveCorrect = 0;
        history.push({ correct: false });
        feedbackDiv.innerHTML = '<div class="feedback feedback-incorrect">Not quite. The answer was ' +
          expected.toFixed(2) + ' ' + (block.units || '') + '. Streak reset.</div>';
        updateProgress();
        setTimeout(generateProblem, 2000);
      }
    });

    updateProgress();
    generateProblem();
    return div;
  }

  // ── Explain Block ──
  function renderExplain(block) {
    const div = document.createElement('div');

    const prompt = document.createElement('p');
    prompt.textContent = block.prompt;
    div.appendChild(prompt);

    const optionsDiv = document.createElement('div');
    optionsDiv.className = 'explain-options';

    block.options.forEach(option => {
      const optEl = document.createElement('div');
      optEl.className = 'explain-option';
      optEl.textContent = option.text;
      optEl.dataset.id = option.id;

      optEl.addEventListener('click', () => {
        // Disable all options
        optionsDiv.querySelectorAll('.explain-option').forEach(el => {
          el.classList.add('disabled');
        });

        if (option.correct) {
          optEl.classList.add('correct-answer');
          markComplete(block.id, div);
        } else {
          optEl.classList.add('wrong-answer');
          // Show misconception
          if (option.misconception) {
            const misconception = document.createElement('div');
            misconception.className = 'misconception';
            misconception.textContent = option.misconception;
            optEl.appendChild(misconception);
          }
          // Highlight correct answer
          const correctOpt = block.options.find(o => o.correct);
          if (correctOpt) {
            const correctEl = optionsDiv.querySelector('[data-id="' + correctOpt.id + '"]');
            if (correctEl) correctEl.classList.add('correct-answer');
          }
        }
      });

      optionsDiv.appendChild(optEl);
    });

    div.appendChild(optionsDiv);
    return div;
  }

  // ── Handwrite Block ──
  // Step-by-step handwritten derivation. Each step:
  //   1. Student draws on a canvas with stylus/finger.
  //   2. Submit -> rasterize -> POST image to vision model -> get LaTeX back.
  //   3. Student previews the transcription and confirms ("looks right") or
  //      rejects ("wrong, fix it"). This is critical: OCR mistakes feel like
  //      math mistakes if the student doesn't get to see what was read.
  //   4. On confirm, SymPy checks symbolic equivalence to the target.
  //   5. Pass: lock the step, reveal the next one. Fail: increment attempts,
  //      retry. After max_attempts the target is revealed and the step unlocks.
  function renderHandwrite(block) {
    const div = document.createElement('div');

    // Kick off SymPy install in the background as soon as the block renders so
    // it's ready (or close to ready) by the time the student finishes drawing.
    ensureSympy().catch(e => console.warn('sympy preload failed:', e));

    if (block.prompt) {
      const prompt = document.createElement('p');
      prompt.textContent = block.prompt;
      div.appendChild(prompt);
    }

    if (block.context_note) {
      const note = document.createElement('div');
      note.className = 'handwrite-context-note';
      note.innerHTML = block.context_note;
      div.appendChild(note);
    }

    if (block.starting_equation) {
      const startLabel = document.createElement('div');
      startLabel.className = 'derive-start-label';
      startLabel.textContent = 'Starting equation:';
      div.appendChild(startLabel);

      const startEq = document.createElement('div');
      startEq.className = 'derive-current-equation derive-start-equation';
      startEq.innerHTML = '$$' + block.starting_equation + '$$';
      div.appendChild(startEq);
    }

    const stepsContainer = document.createElement('div');
    stepsContainer.className = 'handwrite-steps';
    div.appendChild(stepsContainer);

    const maxAttempts = block.max_attempts_per_step || 5;
    let currentStepIdx = 0;

    function renderStep(stepIdx) {
      const step = block.steps[stepIdx];
      const stepEl = document.createElement('div');
      stepEl.className = 'handwrite-step';

      const num = document.createElement('div');
      num.className = 'derive-step-number';
      num.textContent = stepIdx + 1;
      stepEl.appendChild(num);

      const content = document.createElement('div');
      content.className = 'handwrite-step-content';
      stepEl.appendChild(content);

      const instr = document.createElement('div');
      instr.className = 'derive-step-instruction';
      instr.innerHTML = step.instruction;
      content.appendChild(instr);

      // Canvas
      const padWrap = document.createElement('div');
      padWrap.className = 'handwrite-pad-wrap';
      const canvas = document.createElement('canvas');
      canvas.className = 'handwrite-pad';
      canvas.width = 1200;
      canvas.height = 360;
      padWrap.appendChild(canvas);
      content.appendChild(padWrap);

      const ctx = canvas.getContext('2d');
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.strokeStyle = '#000';
      let strokes = [];
      let active = null;

      function paint() {
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        for (const s of strokes) drawStroke(s);
        if (active) drawStroke(active);
      }
      function drawStroke(stroke) {
        if (stroke.points.length < 2) {
          if (stroke.points.length === 1) {
            const p = stroke.points[0];
            ctx.beginPath();
            ctx.arc(p.x, p.y, stroke.width / 2, 0, Math.PI * 2);
            ctx.fillStyle = '#000';
            ctx.fill();
          }
          return;
        }
        ctx.lineWidth = stroke.width;
        ctx.beginPath();
        ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
        for (let i = 1; i < stroke.points.length - 1; i++) {
          const p0 = stroke.points[i];
          const p1 = stroke.points[i + 1];
          ctx.quadraticCurveTo(p0.x, p0.y, (p0.x + p1.x) / 2, (p0.y + p1.y) / 2);
        }
        const last = stroke.points[stroke.points.length - 1];
        ctx.lineTo(last.x, last.y);
        ctx.stroke();
      }
      function pointFromEvent(e) {
        const rect = canvas.getBoundingClientRect();
        return {
          x: (e.clientX - rect.left) * (canvas.width / rect.width),
          y: (e.clientY - rect.top) * (canvas.height / rect.height),
          pressure: e.pressure || 0.5
        };
      }
      // iOS Safari fix: intercept raw touch events BEFORE iOS interprets them
      // as the start of a text selection on nearby elements. Pointer events
      // alone are not enough on iPadOS — we have to grab touchstart/touchmove
      // with passive:false to call preventDefault successfully.
      canvas.addEventListener('touchstart', e => {
        e.preventDefault();
        if (window.getSelection) window.getSelection().removeAllRanges();
      }, { passive: false });
      canvas.addEventListener('touchmove', e => {
        e.preventDefault();
      }, { passive: false });

      let eraserMode = false;
      let activeErasing = false;
      function eraseAtPoint(p) {
        const idx = findStrokeHitByPoint(strokes, p, 12);
        if (idx >= 0) {
          strokes.splice(idx, 1);
          paint();
        }
      }
      canvas.addEventListener('pointerdown', e => {
        e.preventDefault();
        if (window.getSelection) window.getSelection().removeAllRanges();
        canvas.setPointerCapture(e.pointerId);
        const p = pointFromEvent(e);
        if (isEraserPointerEvent(e, eraserMode)) {
          activeErasing = true;
          eraseAtPoint(p);
          return;
        }
        const baseW = getStrokeWidth();
        const w = e.pointerType === 'pen' ? baseW * (0.65 + (p.pressure || 0.5) * 0.7) : baseW;
        active = { points: [p], width: w };
        paint();
      });
      canvas.addEventListener('pointermove', e => {
        if (activeErasing) {
          eraseAtPoint(pointFromEvent(e));
          return;
        }
        if (!active) return;
        active.points.push(pointFromEvent(e));
        paint();
      });
      canvas.addEventListener('pointerup', () => {
        if (activeErasing) {
          activeErasing = false;
          return;
        }
        if (!active) return;
        strokes.push(active);
        active = null;
        paint();
      });
      paint();

      // Controls
      const controls = document.createElement('div');
      controls.className = 'handwrite-controls';

      const undoBtn = document.createElement('button');
      undoBtn.className = 'btn btn-secondary';
      undoBtn.textContent = 'Undo';
      undoBtn.addEventListener('click', () => { strokes.pop(); paint(); });

      const clearBtn = document.createElement('button');
      clearBtn.className = 'btn btn-secondary';
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', () => { strokes = []; paint(); });

      const submitBtn = document.createElement('button');
      submitBtn.className = 'btn btn-primary';
      submitBtn.textContent = 'Transcribe';

      const widthSlider = makeStrokeWidthSlider();

      const eraserToggle = makeEraserToggle(
        () => eraserMode,
        v => {
          eraserMode = v;
          canvas.classList.toggle('eraser-active', eraserMode);
        }
      );

      controls.appendChild(undoBtn);
      controls.appendChild(clearBtn);
      controls.appendChild(eraserToggle.btn);
      controls.appendChild(widthSlider);
      const spacer = document.createElement('span');
      spacer.style.flex = '1';
      controls.appendChild(spacer);
      controls.appendChild(submitBtn);
      content.appendChild(controls);

      // Status / preview / verification area
      const statusEl = document.createElement('div');
      statusEl.className = 'handwrite-status';
      content.appendChild(statusEl);

      const previewWrap = document.createElement('div');
      previewWrap.className = 'handwrite-preview';
      previewWrap.style.display = 'none';
      content.appendChild(previewWrap);

      const feedbackEl = document.createElement('div');
      content.appendChild(feedbackEl);

      let attempts = 0;
      let busy = false;

      // Crop the canvas to a tight bbox of ink with white margin -- smaller
      // payload, dramatically better OCR than feeding a mostly-empty canvas.
      function rasterize() {
        const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
        let minX = canvas.width, minY = canvas.height, maxX = 0, maxY = 0;
        let found = false;
        for (let y = 0; y < canvas.height; y++) {
          for (let x = 0; x < canvas.width; x++) {
            const i = (y * canvas.width + x) * 4;
            if (img.data[i] < 200) {
              if (x < minX) minX = x;
              if (y < minY) minY = y;
              if (x > maxX) maxX = x;
              if (y > maxY) maxY = y;
              found = true;
            }
          }
        }
        if (!found) return null;
        const pad = 20;
        minX = Math.max(0, minX - pad);
        minY = Math.max(0, minY - pad);
        maxX = Math.min(canvas.width, maxX + pad);
        maxY = Math.min(canvas.height, maxY + pad);
        const w = maxX - minX, h = maxY - minY;
        const out = document.createElement('canvas');
        out.width = w;
        out.height = h;
        const octx = out.getContext('2d');
        octx.fillStyle = '#fff';
        octx.fillRect(0, 0, w, h);
        octx.drawImage(canvas, minX, minY, w, h, 0, 0, w, h);
        return out.toDataURL('image/png');
      }

      submitBtn.addEventListener('click', async () => {
        if (busy) return;
        if (strokes.length < 1) {
          statusEl.textContent = 'Draw something first.';
          return;
        }
        const dataUrl = rasterize();
        if (!dataUrl) {
          statusEl.textContent = 'Canvas appears empty.';
          return;
        }
        busy = true;
        submitBtn.disabled = true;
        statusEl.textContent = 'Reading your handwriting...';
        previewWrap.style.display = 'none';
        feedbackEl.innerHTML = '';
        try {
          const { latex, raw } = await transcribeHandwriting(dataUrl, step.vars || []);
          statusEl.textContent = '';
          showPreview(latex, raw);
        } catch (e) {
          const hint = handwriteBackend() === 'openrouter'
            ? 'Check your OpenRouter API key and model in Settings. The key must have credits and the model must support vision.'
            : 'Make sure LM Studio is running on localhost:1234 with a vision model loaded and CORS enabled.';
          statusEl.innerHTML =
            '<span class="handwrite-error">Transcription failed: ' + esc(e.message) + '</span>' +
            '<br><span class="handwrite-status-detail">' + hint + '</span>';
        } finally {
          busy = false;
          submitBtn.disabled = false;
        }
      });

      function showPreview(latex, raw) {
        previewWrap.innerHTML = '';
        previewWrap.style.display = 'block';

        const label = document.createElement('div');
        label.className = 'handwrite-preview-label';
        label.textContent = 'I read this. Is it right?';
        previewWrap.appendChild(label);

        const renderEl = document.createElement('div');
        renderEl.className = 'handwrite-preview-render';
        renderEl.innerHTML = '$$' + latex + '$$';
        previewWrap.appendChild(renderEl);

        const rawEl = document.createElement('div');
        rawEl.className = 'handwrite-preview-raw';
        rawEl.textContent = latex;
        previewWrap.appendChild(rawEl);

        const previewControls = document.createElement('div');
        previewControls.className = 'handwrite-controls';

        const yesBtn = document.createElement('button');
        yesBtn.className = 'btn btn-primary';
        yesBtn.textContent = 'Yes — check it';

        const noBtn = document.createElement('button');
        noBtn.className = 'btn btn-secondary';
        noBtn.textContent = 'No — let me redraw';

        previewControls.appendChild(noBtn);
        const sp = document.createElement('span');
        sp.style.flex = '1';
        previewControls.appendChild(sp);
        previewControls.appendChild(yesBtn);
        previewWrap.appendChild(previewControls);

        renderKaTeX(previewWrap);

        noBtn.addEventListener('click', () => {
          previewWrap.style.display = 'none';
          // Don't burn an attempt for an OCR fix; the math wasn't graded yet.
        });

        yesBtn.addEventListener('click', () => {
          previewWrap.style.display = 'none';
          verify(latex);
        });
      }

      async function verify(studentLatex) {
        statusEl.textContent = 'Loading math engine...';
        try {
          await ensureSympy();
        } catch (e) {
          statusEl.innerHTML =
            '<span class="handwrite-error">Math engine failed to load: ' + esc(e.message) + '</span>';
          return;
        }
        statusEl.textContent = 'Checking...';
        const studentCanon = canonicalizeLatex(studentLatex);
        const targetCanon = canonicalizeLatex(step.target_latex);
        let verdict, detail;
        try {
          pyodide.globals.set('_s', studentCanon);
          pyodide.globals.set('_t', targetCanon);
          const out = await pyodide.runPythonAsync('equiv(_s, _t)');
          [verdict, detail] = out.toJs();
        } catch (e) {
          statusEl.innerHTML =
            '<span class="handwrite-error">Verification crashed: ' + esc(e.message) + '</span>';
          return;
        }
        statusEl.textContent = '';

        if (verdict === 'ok') {
          feedbackEl.innerHTML =
            '<div class="feedback feedback-correct">Correct &mdash; matches the target symbolically.</div>';
          lockStep(stepEl, studentLatex);
          advance();
          return;
        }

        attempts++;
        const remaining = maxAttempts - attempts;
        let msg;
        if (verdict === 'parse_error') {
          msg = 'I couldn\'t parse what you wrote as a valid equation. Try writing it more clearly, or check the transcription.';
        } else if (verdict === 'simplify_error') {
          msg = 'Math engine couldn\'t simplify your answer.';
        } else {
          msg = 'Not equivalent to the target.';
        }
        if (remaining > 0) {
          feedbackEl.innerHTML =
            '<div class="feedback feedback-incorrect">' + esc(msg) +
            ' (' + remaining + ' attempt' + (remaining === 1 ? '' : 's') + ' left)</div>';
        } else {
          // Reveal target and unlock progression -- mirrors derive-block fallback.
          feedbackEl.innerHTML =
            '<div class="feedback feedback-incorrect">' + esc(msg) + '</div>' +
            '<div class="handwrite-reveal">The target was: $$' + step.target_latex + '$$' +
            (step.hint ? '<div class="handwrite-hint-text">' + step.hint + '</div>' : '') +
            '</div>';
          renderKaTeX(feedbackEl);
          lockStep(stepEl, null);
          advance();
        }
      }

      function lockStep(stepElement, studentLatex) {
        stepElement.classList.add('completed');
        canvas.style.pointerEvents = 'none';
        undoBtn.disabled = true;
        clearBtn.disabled = true;
        submitBtn.disabled = true;
        if (studentLatex) {
          const final = document.createElement('div');
          final.className = 'handwrite-final';
          final.innerHTML = 'Your answer: $$' + studentLatex + '$$';
          content.appendChild(final);
          renderKaTeX(final);
        }
      }

      // Hint
      if (step.hint) {
        const hintsDiv = renderHints([step.hint]);
        content.appendChild(hintsDiv);
      }

      stepsContainer.appendChild(stepEl);
      renderKaTeX(stepEl);
    }

    function advance() {
      currentStepIdx++;
      if (currentStepIdx < block.steps.length) {
        renderStep(currentStepIdx);
      } else if (!blockState[block.id].completed) {
        const complete = document.createElement('div');
        complete.className = 'derive-complete';
        complete.textContent = 'Handwritten derivation complete!';
        div.appendChild(complete);
        markComplete(block.id, div);
      }
    }

    renderStep(0);
    return div;
  }

  // ── Canvas-Derive Block (freeform single canvas) ──
  // Pedagogical primary: one continuous graph-paper canvas, multi-line freeform
  // derivation, debounced auto-recognition, line-level dots from operation-tree
  // matching against block.valid_forms. Productive failure is fine — wandering
  // and dead ends are not punished. The structured `handwrite` block is the
  // fallback path for students who get stuck.
  function renderCanvasDerive(block) {
    const div = document.createElement('div');

    // Trigger SymPy install in the background as soon as the block renders.
    ensureSympy().catch(e => console.warn('sympy preload failed:', e));

    if (block.prompt) {
      const prompt = document.createElement('p');
      prompt.textContent = block.prompt;
      div.appendChild(prompt);
    }

    if (block.context_note) {
      const note = document.createElement('div');
      note.className = 'handwrite-context-note';
      note.innerHTML = block.context_note;
      div.appendChild(note);
    }

    if (block.starting_equation) {
      const startLabel = document.createElement('div');
      startLabel.className = 'derive-start-label';
      startLabel.textContent = 'Starting equation:';
      div.appendChild(startLabel);

      const startEq = document.createElement('div');
      startEq.className = 'derive-current-equation derive-start-equation';
      startEq.innerHTML = '$$' + block.starting_equation + '$$';
      div.appendChild(startEq);
    }

    // Two-column layout: canvas left, recognized lines panel right.
    const layout = document.createElement('div');
    layout.className = 'cderive-layout';
    div.appendChild(layout);

    // Canvas column
    const canvasCol = document.createElement('div');
    canvasCol.className = 'cderive-canvas-col';
    layout.appendChild(canvasCol);

    const padWrap = document.createElement('div');
    padWrap.className = 'cderive-pad-wrap';
    canvasCol.appendChild(padWrap);

    const canvas = document.createElement('canvas');
    canvas.className = 'cderive-pad';
    canvas.width = 1400;
    canvas.height = 900;
    padWrap.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#1f2937';

    let strokes = [];
    let active = null;

    function paint() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const s of strokes) drawStroke(s);
      if (active) drawStroke(active);
    }
    function drawStroke(stroke) {
      if (stroke.points.length < 2) {
        if (stroke.points.length === 1) {
          const p = stroke.points[0];
          ctx.beginPath();
          ctx.arc(p.x, p.y, stroke.width / 2, 0, Math.PI * 2);
          ctx.fillStyle = '#1f2937';
          ctx.fill();
        }
        return;
      }
      ctx.lineWidth = stroke.width;
      ctx.beginPath();
      ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
      for (let i = 1; i < stroke.points.length - 1; i++) {
        const p0 = stroke.points[i];
        const p1 = stroke.points[i + 1];
        ctx.quadraticCurveTo(p0.x, p0.y, (p0.x + p1.x) / 2, (p0.y + p1.y) / 2);
      }
      const last = stroke.points[stroke.points.length - 1];
      ctx.lineTo(last.x, last.y);
      ctx.stroke();
    }
    function pointFromEvent(e) {
      const rect = canvas.getBoundingClientRect();
      return {
        x: (e.clientX - rect.left) * (canvas.width / rect.width),
        y: (e.clientY - rect.top) * (canvas.height / rect.height),
        pressure: e.pressure || 0.5
      };
    }

    let recognitionTimer = null;
    let lastRecognizedStrokeCount = 0;
    let busy = false;
    const RECOGNITION_DEBOUNCE_MS = 1200;

    // iOS Safari fix: intercept raw touch events BEFORE iOS interprets them
    // as the start of a text selection on nearby elements. Pointer events
    // alone are not enough on iPadOS — we have to grab touchstart/touchmove
    // with passive:false to call preventDefault successfully.
    canvas.addEventListener('touchstart', e => {
      e.preventDefault();
      if (window.getSelection) window.getSelection().removeAllRanges();
    }, { passive: false });
    canvas.addEventListener('touchmove', e => {
      e.preventDefault();
    }, { passive: false });

    let eraserMode = false;
    let activeErasing = false;
    let erasedSinceDown = false;

    function eraseAtPoint(p) {
      const idx = findStrokeHitByPoint(strokes, p, 12);
      if (idx >= 0) {
        strokes.splice(idx, 1);
        erasedSinceDown = true;
        paint();
      }
    }

    canvas.addEventListener('pointerdown', e => {
      e.preventDefault();
      if (window.getSelection) window.getSelection().removeAllRanges();
      canvas.setPointerCapture(e.pointerId);
      const p = pointFromEvent(e);
      // Cancel any pending recognition while the user is interacting.
      if (recognitionTimer) { clearTimeout(recognitionTimer); recognitionTimer = null; }
      if (isEraserPointerEvent(e, eraserMode)) {
        activeErasing = true;
        erasedSinceDown = false;
        eraseAtPoint(p);
        return;
      }
      const baseW = getStrokeWidth();
      const w = e.pointerType === 'pen' ? baseW * (0.65 + (p.pressure || 0.5) * 0.7) : baseW;
      active = { points: [p], width: w };
      paint();
    });
    canvas.addEventListener('pointermove', e => {
      if (activeErasing) {
        eraseAtPoint(pointFromEvent(e));
        return;
      }
      if (!active) return;
      active.points.push(pointFromEvent(e));
      paint();
    });
    canvas.addEventListener('pointerup', () => {
      if (activeErasing) {
        activeErasing = false;
        if (erasedSinceDown) {
          // Force a fresh recognition pass since the line set may have changed.
          lastRecognizedStrokeCount = -1;
          scheduleRecognition();
        }
        return;
      }
      if (!active) return;
      strokes.push(active);
      active = null;
      paint();
      scheduleRecognition();
    });
    paint();

    // Controls row beneath the canvas.
    const controls = document.createElement('div');
    controls.className = 'cderive-controls';
    canvasCol.appendChild(controls);

    const undoBtn = document.createElement('button');
    undoBtn.className = 'btn btn-secondary';
    undoBtn.textContent = 'Undo';
    undoBtn.addEventListener('click', () => {
      strokes.pop();
      paint();
      scheduleRecognition();
    });

    const clearBtn = document.createElement('button');
    clearBtn.className = 'btn btn-secondary';
    clearBtn.textContent = 'Clear';
    clearBtn.addEventListener('click', () => {
      strokes = [];
      lastRecognizedStrokeCount = 0;
      paint();
      recognizedLines = [];
      renderLinesPanel();
    });

    const recognizeNowBtn = document.createElement('button');
    recognizeNowBtn.className = 'btn btn-secondary';
    recognizeNowBtn.textContent = 'Read now';
    recognizeNowBtn.title = 'Force a re-read instead of waiting for the pause timer';
    recognizeNowBtn.addEventListener('click', () => {
      if (recognitionTimer) { clearTimeout(recognitionTimer); recognitionTimer = null; }
      runRecognition();
    });

    const doneBtn = document.createElement('button');
    doneBtn.className = 'btn btn-primary';
    doneBtn.textContent = 'I\u2019m done';
    doneBtn.disabled = true;
    doneBtn.title = 'Enabled once one of your lines reaches the target equation';
    doneBtn.addEventListener('click', () => {
      if (!targetReached || blockState[block.id].completed) return;
      markComplete(block.id, div);
      const banner = document.createElement('div');
      banner.className = 'derive-complete';
      banner.textContent = 'Derivation complete \u2014 nice work.';
      canvasCol.appendChild(banner);
    });

    const widthSlider = makeStrokeWidthSlider();

    const eraserToggle = makeEraserToggle(
      () => eraserMode,
      v => {
        eraserMode = v;
        canvas.classList.toggle('eraser-active', eraserMode);
      }
    );

    // Keyboard shortcut: E toggles eraser mode (ignored when typing in inputs).
    function onKey(e) {
      if (e.key !== 'e' && e.key !== 'E') return;
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      eraserMode = !eraserMode;
      canvas.classList.toggle('eraser-active', eraserMode);
      eraserToggle.sync();
    }
    document.addEventListener('keydown', onKey);

    controls.appendChild(undoBtn);
    controls.appendChild(clearBtn);
    controls.appendChild(eraserToggle.btn);
    controls.appendChild(recognizeNowBtn);
    controls.appendChild(widthSlider);
    const sp = document.createElement('span');
    sp.style.flex = '1';
    controls.appendChild(sp);
    controls.appendChild(doneBtn);

    // Side panel: recognized lines + status.
    const panel = document.createElement('div');
    panel.className = 'cderive-panel';
    layout.appendChild(panel);

    const panelTitle = document.createElement('div');
    panelTitle.className = 'cderive-panel-title';
    panelTitle.textContent = 'What I read';
    panel.appendChild(panelTitle);

    const linesEl = document.createElement('div');
    linesEl.className = 'cderive-lines';
    panel.appendChild(linesEl);

    const panelStatus = document.createElement('div');
    panelStatus.className = 'cderive-panel-status';
    panelStatus.textContent = 'Draw something on the canvas. I\u2019ll read it after you pause.';
    panel.appendChild(panelStatus);

    // recognizedLines: array of { latex, status, matchedFormIdx }
    //   status: 'ok'  | 'unmatched' | 'parse_error'
    let recognizedLines = [];
    let targetReached = false;

    // Pre-canonicalize valid forms once for fast SymPy lookup.
    const validForms = (block.valid_forms || []).map(canonicalizeLatex);
    const targetCanon = canonicalizeLatex(block.target_equation || '');
    // Index of the target inside validForms (or -1 if not present); used to
    // detect "the student wrote the target" purely by index match.
    const targetIdx = validForms.indexOf(targetCanon);

    function renderLinesPanel() {
      linesEl.innerHTML = '';
      if (recognizedLines.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'cderive-line-empty';
        empty.textContent = '(no lines yet)';
        linesEl.appendChild(empty);
        return;
      }
      recognizedLines.forEach((line, i) => {
        const row = document.createElement('div');
        row.className = 'cderive-line cderive-line-' + line.status;

        const dot = document.createElement('span');
        dot.className = 'cderive-dot';
        if (line.status === 'ok') dot.title = 'Matches a valid form';
        else if (line.status === 'unmatched') dot.title = 'Not equivalent to any valid form (yet)';
        else dot.title = 'Couldn\u2019t parse this line';
        row.appendChild(dot);

        const renderBox = document.createElement('div');
        renderBox.className = 'cderive-line-render';
        renderBox.innerHTML = '$$' + line.latex + '$$';
        row.appendChild(renderBox);

        const rawBox = document.createElement('div');
        rawBox.className = 'cderive-line-raw';
        rawBox.textContent = line.latex;
        row.appendChild(rawBox);

        linesEl.appendChild(row);
      });
      renderKaTeX(linesEl);
    }
    renderLinesPanel();

    function scheduleRecognition() {
      if (busy) return;
      if (recognitionTimer) clearTimeout(recognitionTimer);
      if (strokes.length === 0) {
        // Canvas was cleared; nothing to do.
        return;
      }
      recognitionTimer = setTimeout(runRecognition, RECOGNITION_DEBOUNCE_MS);
    }

    function rasterizeCanvas() {
      // Find bbox of black ink so we send a tightly cropped image.
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      let minX = canvas.width, minY = canvas.height, maxX = 0, maxY = 0;
      let found = false;
      for (let y = 0; y < canvas.height; y++) {
        for (let x = 0; x < canvas.width; x++) {
          const i = (y * canvas.width + x) * 4;
          // Ink is opaque dark; transparent grid background has alpha 0.
          if (img.data[i + 3] > 0 && img.data[i] < 200) {
            if (x < minX) minX = x;
            if (y < minY) minY = y;
            if (x > maxX) maxX = x;
            if (y > maxY) maxY = y;
            found = true;
          }
        }
      }
      if (!found) return null;
      const pad = 24;
      minX = Math.max(0, minX - pad);
      minY = Math.max(0, minY - pad);
      maxX = Math.min(canvas.width, maxX + pad);
      maxY = Math.min(canvas.height, maxY + pad);
      const w = maxX - minX, h = maxY - minY;
      const out = document.createElement('canvas');
      out.width = w;
      out.height = h;
      const octx = out.getContext('2d');
      octx.fillStyle = '#fff';
      octx.fillRect(0, 0, w, h);
      octx.drawImage(canvas, minX, minY, w, h, 0, 0, w, h);
      return out.toDataURL('image/png');
    }

    async function runRecognition() {
      if (busy) return;
      if (strokes.length === lastRecognizedStrokeCount) return;
      const dataUrl = rasterizeCanvas();
      if (!dataUrl) return;
      busy = true;
      lastRecognizedStrokeCount = strokes.length;
      panelStatus.textContent = 'Reading...';
      try {
        const { lines } = await transcribeMultiLine(dataUrl, block.vars || []);
        if (lines.length === 0) {
          panelStatus.textContent = 'Couldn\u2019t read anything yet. Try writing more clearly.';
          recognizedLines = [];
          renderLinesPanel();
          return;
        }
        recognizedLines = lines.map(l => ({ latex: l, status: 'pending', matchedFormIdx: -1 }));
        renderLinesPanel();

        await ensureSympy();
        // Verify each line against the operation tree (valid_forms).
        let anyMatchedTarget = false;
        for (const line of recognizedLines) {
          const canon = canonicalizeLatex(line.latex);
          let matchIdx = -1;
          try {
            pyodide.globals.set('_s', canon);
            pyodide.globals.set('_forms', pyodide.toPy(validForms));
            matchIdx = await pyodide.runPythonAsync('find_matching_form(_s, _forms)');
          } catch (e) {
            console.warn('find_matching_form failed:', e);
            line.status = 'parse_error';
            continue;
          }
          if (matchIdx >= 0) {
            line.status = 'ok';
            line.matchedFormIdx = matchIdx;
            if (targetIdx >= 0 && matchIdx === targetIdx) anyMatchedTarget = true;
          } else {
            line.status = 'unmatched';
          }
        }
        renderLinesPanel();

        const okCount = recognizedLines.filter(l => l.status === 'ok').length;
        if (anyMatchedTarget) {
          targetReached = true;
          doneBtn.disabled = false;
          panelStatus.innerHTML = '<span class="cderive-target-hit">You reached the target. Click <strong>I\u2019m done</strong> when you\u2019re ready.</span>';
        } else if (okCount > 0) {
          panelStatus.textContent = okCount + ' valid line' + (okCount === 1 ? '' : 's') +
            ' so far. Keep going.';
        } else {
          panelStatus.textContent = 'No valid lines yet. The dots show what passed.';
        }
      } catch (e) {
        panelStatus.innerHTML =
          '<span class="handwrite-error">Read failed: ' + esc(e.message) + '</span><br>' +
          '<span class="handwrite-status-detail">Open Settings to switch backend. LM Studio: needs to be running on localhost:1234 with a vision model loaded and CORS enabled. OpenRouter: needs an API key.</span>';
        // Reset so the next pause re-tries.
        lastRecognizedStrokeCount = 0;
      } finally {
        busy = false;
      }
    }

    // Progressive hints (question -> direction -> worked first step).
    if (block.hints && block.hints.length > 0) {
      const hintsDiv = renderHints(block.hints);
      div.appendChild(hintsDiv);
    }

    // "Stuck? Use the guided version below" — points to the structured
    // handwrite block, which is the explicit fallback. The lesson author wires
    // the relationship by ordering the blocks; we just provide the visual cue.
    if (block.fallback_block_id) {
      const fallback = document.createElement('div');
      fallback.className = 'cderive-fallback-link';
      fallback.innerHTML =
        'Stuck? <a href="#block-' + esc(block.fallback_block_id) + '">Try the step-by-step guided version below \u2192</a>';
      div.appendChild(fallback);
    }

    return div;
  }

  // ── Helpers ──
  function markComplete(blockId, containerEl) {
    blockState[blockId].completed = true;
    const wrapper = containerEl.closest('.block');
    if (wrapper) wrapper.classList.add('completed');

    const badge = document.createElement('div');
    badge.className = 'block-complete-badge';
    badge.innerHTML = '&#10003; Complete';
    containerEl.appendChild(badge);

    checkLessonComplete();
  }

  function checkLessonComplete() {
    const completable = lesson.blocks.filter(b => b.type !== 'read');
    const allDone = completable.every(b => blockState[b.id] && blockState[b.id].completed);
    if (allDone) {
      const container = document.getElementById('blocks-container');
      if (!document.getElementById('lesson-complete')) {
        const banner = document.createElement('div');
        banner.id = 'lesson-complete';
        banner.className = 'derive-complete';
        banner.style.marginTop = '24px';
        banner.style.fontSize = '1.2rem';
        banner.innerHTML = '&#127942; Lesson Complete: ' + esc(lesson.title);
        container.appendChild(banner);
        banner.scrollIntoView({ behavior: 'smooth' });
      }
    }
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

    btn.addEventListener('click', () => {
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

  function evalFormula(formula, params) {
    // Safe eval: only allow Math functions and provided params
    const keys = Object.keys(params);
    const vals = Object.values(params);
    const fn = new Function(...keys, 'return ' + formula);
    return fn(...vals);
  }

  function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Feedback System ──
  const FEEDBACK_KEY = 'why-academy-feedback';

  function loadFeedback() {
    try {
      return JSON.parse(localStorage.getItem(FEEDBACK_KEY) || '[]');
    } catch { return []; }
  }

  function saveAllFeedback(all) {
    localStorage.setItem(FEEDBACK_KEY, JSON.stringify(all));
  }

  function saveFeedbackEntry(entry) {
    const all = loadFeedback();
    entry.sent = false;
    all.push(entry);
    saveAllFeedback(all);
    updateSendButton();
  }

  // ── Send to teacher ──
  async function sendUnsentFeedback() {
    const auth = window.WhyAuth;
    if (!auth || !auth.isAuthenticated() || !auth.isAllowlisted()) return;

    const all = loadFeedback();
    const unsent = all.filter(e => !e.sent);
    if (unsent.length === 0) return;

    const sendBtn = document.getElementById('send-feedback-btn');
    if (sendBtn) {
      sendBtn.disabled = true;
      sendBtn.textContent = 'Sending…';
    }

    try {
      const resp = await fetch('https://why-academy-feedback.gainullin.workers.dev/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idToken: auth.getIdToken(),
          feedback: unsent.map(({ sent, ...e }) => e),
        }),
      });

      const data = await resp.json();

      if (resp.ok) {
        // Mark all unsent as sent
        const updated = all.map(e => e.sent ? e : { ...e, sent: true });
        saveAllFeedback(updated);
        if (sendBtn) {
          sendBtn.textContent = '\u2713 Sent (issue #' + data.issueNumber + ')';
          setTimeout(() => updateSendButton(), 3000);
        }
      } else {
        if (sendBtn) {
          sendBtn.textContent = 'Failed: ' + (data.error || resp.status);
          sendBtn.disabled = false;
          setTimeout(() => updateSendButton(), 4000);
        }
      }
    } catch (e) {
      if (sendBtn) {
        sendBtn.textContent = 'Network error';
        sendBtn.disabled = false;
        setTimeout(() => updateSendButton(), 4000);
      }
    }
  }

  function updateSendButton() {
    let sendBtn = document.getElementById('send-feedback-btn');
    const auth = window.WhyAuth;
    const unsent = loadFeedback().filter(e => !e.sent);
    const shouldShow = auth && auth.isAuthenticated() && auth.isAllowlisted() && unsent.length > 0;

    if (shouldShow) {
      if (!sendBtn) {
        sendBtn = document.createElement('button');
        sendBtn.id = 'send-feedback-btn';
        sendBtn.className = 'send-feedback-btn';
        sendBtn.addEventListener('click', sendUnsentFeedback);
        document.body.appendChild(sendBtn);
      }
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send ' + unsent.length + ' feedback ' + (unsent.length === 1 ? 'item' : 'items') + ' to teacher';
    } else if (sendBtn) {
      sendBtn.remove();
    }
  }

  function updateFeedbackToolbarVisibility(toolbar) {
    const auth = window.WhyAuth;
    const gate = toolbar.querySelector('.feedback-gate');
    const actions = toolbar.querySelector('.feedback-actions');
    if (!gate || !actions) return;

    if (!auth || !auth.isAuthenticated()) {
      gate.classList.remove('hidden');
      gate.textContent = 'Sign in to leave feedback for the teacher.';
      actions.classList.add('hidden');
    } else if (!auth.isAllowlisted()) {
      gate.classList.remove('hidden');
      gate.textContent = 'Signed in as ' + auth.getUser().email + ' — your account is not on the trusted-tester list.';
      actions.classList.add('hidden');
    } else {
      gate.classList.add('hidden');
      actions.classList.remove('hidden');
    }
  }

  function renderFeedbackToolbar(blockId, wrapper) {
    const toolbar = document.createElement('div');
    toolbar.className = 'feedback-toolbar';

    // Gate message (shown when not signed in or not allowlisted)
    const gate = document.createElement('div');
    gate.className = 'feedback-gate';
    gate.textContent = 'Sign in to leave feedback for the teacher.';
    toolbar.appendChild(gate);

    // Actions container (shown only when authenticated + allowlisted)
    const actions = document.createElement('div');
    actions.className = 'feedback-actions hidden';
    toolbar.appendChild(actions);

    // Flag button
    const flagBtn = document.createElement('button');
    flagBtn.className = 'feedback-btn feedback-flag-btn';
    flagBtn.innerHTML = '&#9873; Not clear';
    flagBtn.title = 'Flag this block as unclear';

    // Question button
    const questionBtn = document.createElement('button');
    questionBtn.className = 'feedback-btn feedback-question-btn';
    questionBtn.innerHTML = '? Ask a question';
    questionBtn.title = 'Ask a question about this block';

    // Comment on selection button
    const commentBtn = document.createElement('button');
    commentBtn.className = 'feedback-btn feedback-comment-btn';
    commentBtn.innerHTML = '&#9998; Comment on selection';
    commentBtn.title = 'Highlight text, then click to comment';
    commentBtn.disabled = true;

    actions.appendChild(flagBtn);
    actions.appendChild(questionBtn);
    actions.appendChild(commentBtn);

    // Feedback entries display (always visible — shows existing entries even when signed out)
    const entriesDiv = document.createElement('div');
    entriesDiv.className = 'feedback-entries';
    toolbar.appendChild(entriesDiv);

    // Question input (hidden by default)
    const questionForm = document.createElement('div');
    questionForm.className = 'feedback-form hidden';
    const questionInput = document.createElement('textarea');
    questionInput.className = 'feedback-input';
    questionInput.placeholder = 'What are you confused about?';
    questionInput.rows = 2;
    const questionSubmit = document.createElement('button');
    questionSubmit.className = 'btn btn-primary';
    questionSubmit.textContent = 'Submit';
    const questionCancel = document.createElement('button');
    questionCancel.className = 'btn btn-secondary';
    questionCancel.textContent = 'Cancel';
    const questionBtns = document.createElement('div');
    questionBtns.className = 'feedback-form-btns';
    questionBtns.appendChild(questionSubmit);
    questionBtns.appendChild(questionCancel);
    questionForm.appendChild(questionInput);
    questionForm.appendChild(questionBtns);
    actions.appendChild(questionForm);

    // Comment form (hidden by default)
    const commentForm = document.createElement('div');
    commentForm.className = 'feedback-form hidden';
    const commentSelection = document.createElement('div');
    commentSelection.className = 'feedback-selection';
    const commentInput = document.createElement('textarea');
    commentInput.className = 'feedback-input';
    commentInput.placeholder = 'Your comment on the selected text…';
    commentInput.rows = 2;
    const commentSubmit = document.createElement('button');
    commentSubmit.className = 'btn btn-primary';
    commentSubmit.textContent = 'Submit';
    const commentCancel = document.createElement('button');
    commentCancel.className = 'btn btn-secondary';
    commentCancel.textContent = 'Cancel';
    const commentBtns = document.createElement('div');
    commentBtns.className = 'feedback-form-btns';
    commentBtns.appendChild(commentSubmit);
    commentBtns.appendChild(commentCancel);
    commentForm.appendChild(commentSelection);
    commentForm.appendChild(commentInput);
    commentForm.appendChild(commentBtns);
    actions.appendChild(commentForm);

    let selectedText = '';

    // Enable comment button when text is selected within this block
    wrapper.addEventListener('mouseup', () => {
      const sel = window.getSelection();
      const text = sel ? sel.toString().trim() : '';
      if (text.length > 0 && wrapper.contains(sel.anchorNode)) {
        selectedText = text;
        commentBtn.disabled = false;
        commentBtn.innerHTML = '&#9998; Comment on "' +
          (text.length > 30 ? text.slice(0, 30) + '…' : text) + '"';
      } else {
        selectedText = '';
        commentBtn.disabled = true;
        commentBtn.innerHTML = '&#9998; Comment on selection';
      }
    });

    // Flag
    flagBtn.addEventListener('click', () => {
      const entry = {
        blockId: blockId,
        lessonId: lesson.lesson_id,
        type: 'flag',
        content: 'Block flagged as unclear',
        timestamp: new Date().toISOString()
      };
      saveFeedbackEntry(entry);
      flagBtn.classList.add('feedback-btn-active');
      flagBtn.innerHTML = '&#9873; Flagged';
      flagBtn.disabled = true;
      showFeedbackEntries(blockId, entriesDiv);
    });

    // Question
    questionBtn.addEventListener('click', () => {
      questionForm.classList.toggle('hidden');
      commentForm.classList.add('hidden');
      if (!questionForm.classList.contains('hidden')) questionInput.focus();
    });
    questionCancel.addEventListener('click', () => {
      questionForm.classList.add('hidden');
      questionInput.value = '';
    });
    questionSubmit.addEventListener('click', () => {
      const text = questionInput.value.trim();
      if (!text) return;
      const entry = {
        blockId: blockId,
        lessonId: lesson.lesson_id,
        type: 'question',
        content: text,
        timestamp: new Date().toISOString()
      };
      saveFeedbackEntry(entry);
      questionForm.classList.add('hidden');
      questionInput.value = '';
      showFeedbackEntries(blockId, entriesDiv);
    });
    questionInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        questionSubmit.click();
      }
    });

    // Comment on selection
    commentBtn.addEventListener('click', () => {
      if (!selectedText) return;
      commentSelection.textContent = '"' + selectedText + '"';
      commentForm.classList.toggle('hidden');
      questionForm.classList.add('hidden');
      if (!commentForm.classList.contains('hidden')) commentInput.focus();
    });
    commentCancel.addEventListener('click', () => {
      commentForm.classList.add('hidden');
      commentInput.value = '';
    });
    commentSubmit.addEventListener('click', () => {
      const text = commentInput.value.trim();
      if (!text) return;
      const entry = {
        blockId: blockId,
        lessonId: lesson.lesson_id,
        type: 'comment',
        content: text,
        selection: selectedText,
        timestamp: new Date().toISOString()
      };
      saveFeedbackEntry(entry);
      commentForm.classList.add('hidden');
      commentInput.value = '';
      selectedText = '';
      commentBtn.disabled = true;
      commentBtn.innerHTML = '&#9998; Comment on selection';
      showFeedbackEntries(blockId, entriesDiv);
    });
    commentInput.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        commentSubmit.click();
      }
    });

    // Show existing feedback for this block
    showFeedbackEntries(blockId, entriesDiv);

    // Set initial visibility based on current auth state
    updateFeedbackToolbarVisibility(toolbar);

    return toolbar;
  }

  function showFeedbackEntries(blockId, container) {
    const all = loadFeedback().filter(e => e.blockId === blockId);
    container.innerHTML = '';
    if (all.length === 0) return;

    all.forEach(entry => {
      const el = document.createElement('div');
      el.className = 'feedback-entry feedback-entry-' + entry.type;
      const icon = entry.type === 'flag' ? '&#9873;' : entry.type === 'question' ? '?' : '&#9998;';
      let html = '<span class="feedback-entry-icon">' + icon + '</span> ';
      if (entry.selection) {
        html += '<span class="feedback-entry-selection">"' + esc(entry.selection) + '"</span> — ';
      }
      html += '<span class="feedback-entry-content">' + esc(entry.content) + '</span>';
      html += '<span class="feedback-entry-time">' + timeAgo(entry.timestamp) + '</span>';
      el.innerHTML = html;
      container.appendChild(el);
    });
  }

  function timeAgo(isoStr) {
    const diff = Date.now() - new Date(isoStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return mins + 'm ago';
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    return Math.floor(hrs / 24) + 'd ago';
  }
})();
