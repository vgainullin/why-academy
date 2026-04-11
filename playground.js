// Hand Derivation Playground — Standalone equation practice
(function () {
  'use strict';

  // ── Equation Library — All supported derivations ──
  const EQUATIONS = [
    // Physics: Oscillations
    {
      id: 'phy-osc-omega',
      category: 'physics',
      name: 'Angular Frequency of a Spring',
      description: 'Derive the angular frequency from the equation of motion',
      starting_equation: 'm\\ddot{x} = -kx',
      target_equation: '\\omega = \\sqrt{\\frac{k}{m}}',
      vars: ['x', 'k', 'm', '\\omega', 'A', 't', 'i'],
      valid_forms: [
        'm\\ddot{x} = -kx',
        'm\\ddot{x} + kx = 0',
        '\\ddot{x} = -\\frac{k}{m} x',
        '\\ddot{x} + \\frac{k}{m} x = 0',
        '-m\\omega^2 x = -kx',
        'm\\omega^2 x = kx',
        'm\\omega^2 = k',
        '-\\omega^2 x = -\\frac{k}{m} x',
        '\\omega^2 x = \\frac{k}{m} x',
        '\\omega^2 = \\frac{k}{m}',
        '\\omega = \\sqrt{\\frac{k}{m}}'
      ],
      hints: [
        'What kind of function gives back a negative of itself when differentiated twice?',
        'After substituting ẍ = -ω²x, cancel -x from both sides.',
        'Take the positive square root to solve for ω.'
      ]
    },
    {
      id: 'phy-osc-period',
      category: 'physics',
      name: 'Period of Oscillation',
      description: 'Derive the period from angular frequency',
      starting_equation: '\\omega = \\sqrt{\\frac{k}{m}}',
      target_equation: 'T = 2\\pi\\sqrt{\\frac{m}{k}}',
      vars: ['T', '\\omega', 'k', 'm', '\\pi'],
      valid_forms: [
        '\\omega = \\sqrt{\\frac{k}{m}}',
        '\\omega^2 = \\frac{k}{m}',
        'T = \\frac{2\\pi}{\\omega}',
        'T = 2\\pi\\sqrt{\\frac{m}{k}}',
        'T^2 = 4\\pi^2 \\frac{m}{k}'
      ],
      hints: [
        'Recall the relationship between period and angular frequency.',
        'T = 2π/ω — substitute your expression for ω.',
        'Rationalize the denominator.'
      ]
    },
    {
      id: 'phy-osc-frequency',
      category: 'physics',
      name: 'Frequency from Period',
      description: 'Derive frequency from the period',
      starting_equation: 'T = 2\\pi\\sqrt{\\frac{m}{k}}',
      target_equation: 'f = \\frac{1}{2\\pi}\\sqrt{\\frac{k}{m}}',
      vars: ['f', 'T', 'k', 'm', '\\pi'],
      valid_forms: [
        'T = 2\\pi\\sqrt{\\frac{m}{k}}',
        'f = \\frac{1}{T}',
        'f = \\frac{1}{2\\pi}\\sqrt{\\frac{k}{m}}',
        'f = \\frac{\\omega}{2\\pi}'
      ],
      hints: [
        'Frequency is the reciprocal of period.',
        'f = 1/T — substitute your expression for T.',
        'The square root in the denominator can be written as 1/√ in the numerator.'
      ]
    },

    // Calculus: Function Composition
    {
      id: 'calc-compose-1',
      category: 'calculus',
      name: 'Function Composition (Balloon)',
      description: 'Derive f(g(t)) for the weather balloon',
      starting_equation: 'f(h) = 20 - 0.006h, \\quad g(t) = 1000 + 5t',
      target_equation: 'f(g(t)) = -1 - 0.03t',
      vars: ['f', 'g', 'h', 't'],
      valid_forms: [
        'f(h) = 20 - 0.006h',
        'g(t) = 1000 + 5t',
        'f(g(t)) = 20 - 0.006(1000 + 5t)',
        'f(g(t)) = 20 - 6 - 0.03t',
        'f(g(t)) = 14 - 0.03t',
        'f(g(t)) = -1 - 0.03t'
      ],
      hints: [
        'Substitute g(t) into f for h.',
        'Distribute the -0.006: -0.006 × 1000 = -6, -0.006 × 5t = -0.03t.',
        'Combine constants: 20 - 6 = 14 (or 20 - 21 = -1 at t=500).'
      ]
    },
    {
      id: 'calc-compose-2',
      category: 'calculus',
      name: 'Chain Rule Setup',
      description: 'Decompose sin((0.5t)²) into inner and outer',
      starting_equation: 'T(t) = \\sin((0.5t)^2)',
      target_equation: 'T(t) = \\sin(u), \\quad u = (0.5t)^2',
      vars: ['T', 't', 'u', '\\sin'],
      valid_forms: [
        'T(t) = \\sin((0.5t)^2)',
        'u = (0.5t)^2',
        'u(t) = (0.5t)^2',
        'T(t) = \\sin(u)',
        'T(t) = \\sin(u(t))'
      ],
      hints: [
        'Identify what operation happens first (inner) and last (outer).',
        'The inner machine is the square: u = (0.5t)².',
        'The outer machine is sine: T = sin(u).'
      ]
    },
    {
      id: 'calc-inverse-linear',
      category: 'calculus',
      name: 'Inverse of Linear Function',
      description: 'Find the inverse of T = 20 - 0.006h',
      starting_equation: 'T = 20 - 0.006h',
      target_equation: 'h = \\frac{20 - T}{0.006}',
      vars: ['T', 'h'],
      valid_forms: [
        'T = 20 - 0.006h',
        'T - 20 = -0.006h',
        '20 - T = 0.006h',
        'h = \\frac{20 - T}{0.006}',
        'h = \\frac{T - 20}{-0.006}'
      ],
      hints: [
        'Solve for h in terms of T.',
        'Subtract 20 from both sides, then divide by -0.006.',
        'Or: multiply by -1 first to get 20 - T = 0.006h.'
      ]
    },

    // Algebra: Basic Manipulations
    {
      id: 'alg-quadratic-vertex',
      category: 'algebra',
      name: 'Quadratic Vertex Form',
      description: 'Complete the square for a quadratic',
      starting_equation: 'y = ax^2 + bx + c',
      target_equation: 'y = a\\left(x + \\frac{b}{2a}\\right)^2 + \\left(c - \\frac{b^2}{4a}\\right)',
      vars: ['y', 'x', 'a', 'b', 'c'],
      valid_forms: [
        'y = ax^2 + bx + c',
        'y = a\\left(x^2 + \\frac{b}{a}x\\right) + c',
        'y = a\\left(x^2 + \\frac{b}{a}x + \\frac{b^2}{4a^2}\\right) + c - \\frac{b^2}{4a}',
        'y = a\\left(x + \\frac{b}{2a}\\right)^2 + c - \\frac{b^2}{4a}',
        'y = a\\left(x + \\frac{b}{2a}\\right)^2 + \\left(c - \\frac{b^2}{4a}\\right)'
      ],
      hints: [
        'Factor out a from the first two terms.',
        'Add and subtract (b/2a)² inside the parentheses.',
        'The first three terms form a perfect square.'
      ]
    },
    {
      id: 'alg-log-exp',
      category: 'algebra',
      name: 'Logarithm Definition',
      description: 'Convert between exponential and logarithmic forms',
      starting_equation: 'a^x = b',
      target_equation: 'x = \\log_a b',
      vars: ['a', 'x', 'b'],
      valid_forms: [
        'a^x = b',
        '\\log_a(a^x) = \\log_a b',
        'x \\cdot \\log_a a = \\log_a b',
        'x = \\log_a b',
        'x = \\frac{\\ln b}{\\ln a}'
      ],
      hints: [
        'Take log base a of both sides.',
        'Use the property log(a^x) = x·log(a).',
        'Since log_a(a) = 1, you get x = log_a(b).'
      ]
    },
    {
      id: 'alg-geom-series',
      category: 'algebra',
      name: 'Geometric Series Sum',
      description: 'Derive the sum of a finite geometric series',
      starting_equation: 'S_n = 1 + r + r^2 + \\ldots + r^n',
      target_equation: 'S_n = \\frac{1 - r^{n+1}}{1 - r}',
      vars: ['S', 'r', 'n'],
      valid_forms: [
        'S_n = 1 + r + r^2 + \\ldots + r^n',
        'rS_n = r + r^2 + r^3 + \\ldots + r^{n+1}',
        'S_n - rS_n = 1 - r^{n+1}',
        'S_n(1 - r) = 1 - r^{n+1}',
        'S_n = \\frac{1 - r^{n+1}}{1 - r}'
      ],
      hints: [
        'Multiply S_n by r and subtract from original.',
        'Most terms cancel (telescoping).',
        'Factor and solve for S_n.'
      ]
    },

    // Physics: Energy
    {
      id: 'phy-energy-sho',
      category: 'physics',
      name: 'Simple Harmonic Oscillator Energy',
      description: 'Total energy of a mass on a spring',
      starting_equation: 'E = \\frac{1}{2}mv^2 + \\frac{1}{2}kx^2',
      target_equation: 'E = \\frac{1}{2}kA^2',
      vars: ['E', 'm', 'v', 'k', 'x', 'A', '\\omega'],
      valid_forms: [
        'E = \\frac{1}{2}mv^2 + \\frac{1}{2}kx^2',
        'x = A\\cos(\\omega t)',
        'v = -A\\omega\\sin(\\omega t)',
        'E = \\frac{1}{2}mA^2\\omega^2\\sin^2(\\omega t) + \\frac{1}{2}kA^2\\cos^2(\\omega t)',
        'E = \\frac{1}{2}kA^2\\sin^2(\\omega t) + \\frac{1}{2}kA^2\\cos^2(\\omega t)',
        'E = \\frac{1}{2}kA^2'
      ],
      hints: [
        'Substitute x(t) and v(t) for SHM.',
        'Use ω² = k/m to simplify the kinetic term.',
        'Factor out (1/2)kA² and use sin² + cos² = 1.'
      ]
    },

    // Calculus: Derivatives
    {
      id: 'calc-deriv-power',
      category: 'calculus',
      name: 'Power Rule Derivation',
      description: 'Derive the power rule from first principles',
      starting_equation: 'f(x) = x^n',
      target_equation: "f'(x) = nx^{n-1}",
      vars: ['f', 'x', 'n', 'h'],
      valid_forms: [
        'f(x) = x^n',
        "f'(x) = \\lim_{h \\to 0} \\frac{(x+h)^n - x^n}{h}",
        '(x+h)^n = x^n + nx^{n-1}h + \\frac{n(n-1)}{2}x^{n-2}h^2 + \\ldots',
        "f'(x) = \\lim_{h \\to 0} \\frac{nx^{n-1}h + O(h^2)}{h}",
        "f'(x) = nx^{n-1}"
      ],
      hints: [
        'Start with the limit definition of derivative.',
        'Expand (x+h)^n using the binomial theorem.',
        'The x^n terms cancel; divide by h and take limit.'
      ]
    },
    {
      id: 'calc-deriv-sin',
      category: 'calculus',
      name: 'Derivative of Sine',
      description: 'Derive d/dx sin(x) from first principles',
      starting_equation: 'f(x) = \\sin x',
      target_equation: "f'(x) = \\cos x",
      vars: ['f', 'x', 'h'],
      valid_forms: [
        'f(x) = \\sin x',
        "f'(x) = \\lim_{h \\to 0} \\frac{\\sin(x+h) - \\sin x}{h}",
        '\\sin(x+h) = \\sin x \\cos h + \\cos x \\sin h',
        "f'(x) = \\lim_{h \\to 0} \\frac{\\sin x(\\cos h - 1) + \\cos x \\sin h}{h}",
        "f'(x) = \\cos x"
      ],
      hints: [
        'Use the angle addition formula.',
        'Split into two limits.',
        'Use lim_{h→0} (cos h - 1)/h = 0 and lim_{h→0} sin h/h = 1.'
      ]
    },

    // Physics: Kinematics
    {
      id: 'phy-kinematic-v',
      category: 'physics',
      name: 'Velocity from Acceleration',
      description: 'Integrate constant acceleration to get velocity',
      starting_equation: 'a = \\frac{dv}{dt}',
      target_equation: 'v = v_0 + at',
      vars: ['a', 'v', 't', 'v_0'],
      valid_forms: [
        'a = \\frac{dv}{dt}',
        'dv = a \\, dt',
        '\\int_{v_0}^{v} dv = \\int_0^t a \\, dt',
        'v - v_0 = at',
        'v = v_0 + at'
      ],
      hints: [
        'Separate variables: dv = a dt.',
        'Integrate both sides with appropriate limits.',
        'Solve for v.'
      ]
    },
    {
      id: 'phy-kinematic-x',
      category: 'physics',
      name: 'Position from Velocity',
      description: 'Integrate velocity to get position',
      starting_equation: 'v = \\frac{dx}{dt} = v_0 + at',
      target_equation: 'x = x_0 + v_0t + \\frac{1}{2}at^2',
      vars: ['x', 'v', 't', 'x_0', 'v_0', 'a'],
      valid_forms: [
        'v = \\frac{dx}{dt} = v_0 + at',
        'dx = (v_0 + at) \\, dt',
        '\\int_{x_0}^{x} dx = \\int_0^t (v_0 + at) \\, dt',
        'x - x_0 = v_0t + \\frac{1}{2}at^2',
        'x = x_0 + v_0t + \\frac{1}{2}at^2'
      ],
      hints: [
        'Substitute v = v_0 + at.',
        'Integrate term by term.',
        'Don\'t forget the 1/2 from integrating t.'
      ]
    }
  ];

  // ── State ──
  let currentEquation = null;
  let pyodide = null;
  let pyodideLoading = false;
  let pyodideReady = false;
  let pyodideReadyCallbacks = [];
  const STORAGE_KEY = 'why-academy-playground-progress';
  let progress = loadProgress();

  // ── Boot ──
  document.addEventListener('DOMContentLoaded', async () => {
    if (window.WhyAuth) WhyAuth.init();
    initSettingsModal();
    initPlayground();
    startPyodidePreload();
  });

  function loadProgress() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch {
      return {};
    }
  }

  function saveProgress() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
  }

  function markCompleted(equationId) {
    if (!progress[equationId]) {
      progress[equationId] = { completed: true, firstCompleted: Date.now() };
    } else if (!progress[equationId].completed) {
      progress[equationId].completed = true;
      progress[equationId].firstCompleted = Date.now();
    }
    progress[equationId].lastCompleted = Date.now();
    saveProgress();
    updateStats();
    renderEquationSelector();
  }

  function updateStats() {
    const mastered = Object.values(progress).filter(p => p.completed).length;
    const total = EQUATIONS.length;
    document.getElementById('mastered-count').textContent = mastered;
    document.getElementById('total-count').textContent = total;

    // Calculate streak
    let streak = 0;
    const completedIds = Object.entries(progress)
      .filter(([_, p]) => p.completed)
      .sort((a, b) => (b[1].lastCompleted || 0) - (a[1].lastCompleted || 0))
      .map(([id, _]) => id);

    // Simple streak: consecutive unique equations completed
    for (let i = 0; i < completedIds.length; i++) {
      streak++;
    }
    document.getElementById('streak-count').textContent = streak;
  }

  // ── Playground UI ──
  function initPlayground() {
    updateStats();
    renderEquationSelector();
    initFilters();

    document.getElementById('random-pick').addEventListener('click', pickRandomEquation);
  }

  function initFilters() {
    const buttons = document.querySelectorAll('#category-filters .filter-btn');
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        buttons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        renderEquationSelector(btn.dataset.category);
      });
    });
  }

  function renderEquationSelector(filter = 'all') {
    const container = document.getElementById('equation-selector');
    container.innerHTML = '';

    const filtered = filter === 'all'
      ? EQUATIONS
      : EQUATIONS.filter(eq => eq.category === filter);

    filtered.forEach(eq => {
      const card = document.createElement('div');
      card.className = 'equation-card';
      if (currentEquation && currentEquation.id === eq.id) {
        card.classList.add('active');
      }
      if (progress[eq.id]?.completed) {
        card.classList.add('completed');
      }

      const categoryLabel = eq.category.charAt(0).toUpperCase() + eq.category.slice(1);

      card.innerHTML = `
        <div class="category">${categoryLabel}</div>
        <div class="name">${eq.name}</div>
        <div class="hint">${eq.description}</div>
        ${progress[eq.id]?.completed ? '<div class="completion-badge">✓ Mastered</div>' : ''}
      `;

      card.addEventListener('click', () => selectEquation(eq));
      container.appendChild(card);
    });
  }

  function pickRandomEquation() {
    const incomplete = EQUATIONS.filter(eq => !progress[eq.id]?.completed);
    const pool = incomplete.length > 0 ? incomplete : EQUATIONS;
    const random = pool[Math.floor(Math.random() * pool.length)];

    // Scroll to and select
    selectEquation(random);

    // Update UI to show selection
    renderEquationSelector(document.querySelector('#category-filters .filter-btn.active')?.dataset.category || 'all');
  }

  function selectEquation(eq) {
    currentEquation = eq;

    // Update target display
    document.querySelector('.target-display .label').textContent =
      `Derive: ${eq.description}`;
    document.getElementById('target-equation').innerHTML =
      `$$${eq.starting_equation} \\Rightarrow ${eq.target_equation}$$`;

    if (typeof renderMathInElement === 'function') {
      renderMathInElement(document.getElementById('target-equation'), {
        delimiters: [{ left: '$$', right: '$$', display: true }],
        throwOnError: false
      });
    }

    // Render the canvas
    renderCanvas(eq);

    // Update selector highlighting
    renderEquationSelector(document.querySelector('#category-filters .filter-btn.active')?.dataset.category || 'all');
  }

  // ── Loading bar driver ──
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

      // Load SymPy for verification
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
      setLoadDone();
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

  // ── Handwriting Backend ──
  const OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions';
  const DEFAULT_LMSTUDIO_ENDPOINT = 'http://localhost:1234/v1/chat/completions';
  const DEFAULT_LMSTUDIO_MODEL = 'qwen2-vl-7b-instruct';
  const OPENROUTER_MODEL_PRESETS = [
    { id: 'google/gemma-4-31b-it', label: 'Gemma 4 31B (dense, default)' },
    { id: 'google/gemma-4-26b-a4b-it', label: 'Gemma 4 26B MoE (cheaper)' },
    { id: 'google/gemma-4-31b-it:free', label: 'Gemma 4 31B — Free tier (rate-limited)' },
    { id: 'google/gemini-2.0-flash-001', label: 'Gemini 2.0 Flash (cheapest)' },
    { id: 'anthropic/claude-sonnet-4-5', label: 'Claude Sonnet 4.5 (most reliable)' },
    { id: 'qwen/qwen2-vl-72b-instruct', label: 'Qwen2-VL 72B (matches local 7B)' }
  ];
  const DEFAULT_OPENROUTER_MODEL = OPENROUTER_MODEL_PRESETS[0].id;

  function handwriteBackend() {
    const stored = localStorage.getItem('handwriteBackend');
    if (stored) return stored;
    const host = window.location.hostname;
    const isLocal = host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
    return isLocal ? 'lmstudio' : 'openrouter';
  }
  function lmstudioEndpoint() {
    return localStorage.getItem('handwriteEndpoint') || DEFAULT_LMSTUDIO_ENDPOINT;
  }
  function lmstudioModel() {
    return localStorage.getItem('handwriteModel') || DEFAULT_LMSTUDIO_MODEL;
  }
  function openrouterApiKey() {
    return localStorage.getItem('openrouterApiKey') || '';
  }
  function openrouterModel() {
    return localStorage.getItem('openrouterModel') || DEFAULT_OPENROUTER_MODEL;
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
      'Use standard LaTeX commands: \\frac, \\sqrt, \\ddot, \\dot, \\omega, \\alpha, \\pi, etc.' +
      varsLine
    );
  }

  function parseMultiLineLatex(raw) {
    if (!raw) return [];
    let s = raw.trim();
    s = s.replace(/^```(?:latex|tex)?\s*/i, '').replace(/\s*```$/, '');
    s = s.replace(/\\begin\{(aligned|align\*?|gathered|equation\*?)\}/g, '');
    s = s.replace(/\\end\{(aligned|align\*?|gathered|equation\*?)\}/g, '');
    const parts = s.split(/\r?\n|\\\\/);
    return parts
      .map(p => cleanLatex(p))
      .filter(p => p.length > 0);
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

  function canonicalizeLatex(s) {
    if (!s) return '';
    s = s.replace(/\\left\s*([(\[|])/g, '$1').replace(/\\right\s*([)\]|])/g, '$1');
    s = s.replace(/\\,|\\!|\\;|\\:|\\>/g, '');
    s = s.replace(/\\frac\s*\{\s*d\s*\^\s*\{?2\}?\s*([a-zA-Z]|\\[a-zA-Z]+)\s*\}\s*\{\s*dt\s*\^\s*\{?2\}?\s*\}/g, '\\ddot{$1}');
    s = s.replace(/\\frac\s*\{\s*d\s*([a-zA-Z]|\\[a-zA-Z]+)\s*\}\s*\{\s*dt\s*\}/g, '\\dot{$1}');
    return s.trim();
  }

  // ── Canvas Rendering ──
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
      for (const pp of s.points) {
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

  function renderCanvas(eq) {
    const container = document.getElementById('canvas-container');
    container.innerHTML = '';

    const layout = document.createElement('div');
    layout.className = 'cderive-layout';
    container.appendChild(layout);

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

    // Controls
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
    doneBtn.textContent = 'I\'m done';
    doneBtn.disabled = true;
    doneBtn.title = 'Enabled once you reach the target equation';
    doneBtn.addEventListener('click', () => {
      if (!targetReached) return;
      markCompleted(eq.id);
      doneBtn.textContent = '✓ Mastered!';
      doneBtn.disabled = true;
      const banner = document.createElement('div');
      banner.className = 'derive-complete';
      banner.textContent = 'Nice work! Equation mastered.';
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

    // Side panel
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
    panelStatus.textContent = 'Draw your derivation on the canvas. I\'ll read it after you pause.';
    panel.appendChild(panelStatus);

    // Hints section
    if (eq.hints && eq.hints.length > 0) {
      const hintsDiv = document.createElement('div');
      hintsDiv.className = 'mt-12';

      const btn = document.createElement('button');
      btn.className = 'hint-btn';
      btn.textContent = 'Need a hint?';
      hintsDiv.appendChild(btn);

      const hintContainer = document.createElement('div');
      hintsDiv.appendChild(hintContainer);

      let shown = 0;
      btn.addEventListener('click', () => {
        if (shown < eq.hints.length) {
          const hintEl = document.createElement('div');
          hintEl.className = 'hint-text mt-8';
          hintEl.textContent = eq.hints[shown];
          hintContainer.appendChild(hintEl);
          shown++;
          if (shown >= eq.hints.length) {
            btn.style.display = 'none';
          }
        }
      });

      canvasCol.appendChild(hintsDiv);
    }

    let recognizedLines = [];
    let targetReached = false;

    const validForms = (eq.valid_forms || []).map(canonicalizeLatex);
    const targetCanon = canonicalizeLatex(eq.target_equation || '');
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
        else dot.title = 'Couldn\'t parse this line';
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
      if (typeof renderMathInElement === 'function') {
        renderMathInElement(linesEl, {
          delimiters: [{ left: '$$', right: '$$', display: true }],
          throwOnError: false
        });
      }
    }
    renderLinesPanel();

    function scheduleRecognition() {
      if (busy) return;
      if (recognitionTimer) clearTimeout(recognitionTimer);
      if (strokes.length === 0) return;
      recognitionTimer = setTimeout(runRecognition, RECOGNITION_DEBOUNCE_MS);
    }

    function rasterizeCanvas() {
      const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
      let minX = canvas.width, minY = canvas.height, maxX = 0, maxY = 0;
      let found = false;
      for (let y = 0; y < canvas.height; y++) {
        for (let x = 0; x < canvas.width; x++) {
          const i = (y * canvas.width + x) * 4;
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
        const { lines } = await transcribeMultiLine(dataUrl, eq.vars || []);
        if (lines.length === 0) {
          panelStatus.textContent = 'Couldn\'t read anything yet. Try writing more clearly.';
          recognizedLines = [];
          renderLinesPanel();
          return;
        }
        recognizedLines = lines.map(l => ({ latex: l, status: 'pending', matchedFormIdx: -1 }));
        renderLinesPanel();

        await waitForPyodide();
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
          panelStatus.innerHTML = '<span class="cderive-target-hit">You reached the target! Click <strong>I\'m done</strong> to mark this equation mastered.</span>';
        } else if (okCount > 0) {
          panelStatus.textContent = okCount + ' valid line' + (okCount === 1 ? '' : 's') +
            ' so far. Keep going until you reach ' + eq.target_equation + '.';
        } else {
          panelStatus.textContent = 'No valid lines yet. The dots show what passed. Keep trying!';
        }
      } catch (e) {
        panelStatus.innerHTML =
          '<span class="handwrite-error">Read failed: ' + esc(e.message) + '</span><br>' +
          '<span class="handwrite-status-detail">Open Settings to switch backend. LM Studio: needs to be running on localhost:1234 with a vision model loaded and CORS enabled. OpenRouter: needs an API key.</span>';
        lastRecognizedStrokeCount = 0;
      } finally {
        busy = false;
      }
    }
  }

  // ── Settings Modal ──
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
      if (orKey) localStorage.setItem('openrouterApiKey', orKey);
      else localStorage.removeItem('openrouterApiKey');

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

  function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
})();
