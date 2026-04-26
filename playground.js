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
    },

    // Bayesian Statistics
    {
      id: 'bayes-bayes-theorem',
      category: 'statistics',
      name: "Bayes' Theorem",
      description: 'Derive Bayes theorem from conditional probability',
      starting_equation: 'P(p \\mid \\text{data}) = \\frac{P(p \\cap \\text{data})}{P(\\text{data})}',
      target_equation: 'P(p \\mid \\text{data}) = \\frac{P(\\text{data} \\mid p) \\cdot P(p)}{P(\\text{data})}',
      vars: ['P', 'p', '\\text{data}'],
      valid_forms: [
        'P(p \\mid \\text{data}) = \\frac{P(p \\cap \\text{data})}{P(\\text{data})}',
        'P(p \\cap \\text{data}) = P(\\text{data} \\mid p) \\cdot P(p)',
        'P(p \\mid \\text{data}) = \\frac{P(\\text{data} \\mid p) \\cdot P(p)}{P(\\text{data})}',
        'P(p \\mid \\text{data}) \\propto P(\\text{data} \\mid p) \\cdot P(p)'
      ],
      hints: [
        'Start with the definition of conditional probability.',
        'Write P(p ∩ data) using the OTHER conditional: P(data|p).',
        'Substitute into the original equation.'
      ]
    },
    {
      id: 'bayes-log-likelihood',
      category: 'statistics',
      name: 'Log-Likelihood for Binomial',
      description: 'Take the log of the binomial likelihood',
      starting_equation: 'P(\\text{data} \\mid p) = p^k (1-p)^{n-k}',
      target_equation: '\\ell(p) = k \\log p + (n-k) \\log(1-p)',
      vars: ['P', 'p', 'k', 'n', '\\ell', '\\log'],
      valid_forms: [
        'P(\\text{data} \\mid p) = p^k (1-p)^{n-k}',
        '\\ell(p) = \\log(p^k (1-p)^{n-k})',
        '\\ell(p) = \\log(p^k) + \\log((1-p)^{n-k})',
        '\\ell(p) = k \\log p + (n-k) \\log(1-p)'
      ],
      hints: [
        'Take the natural log of both sides.',
        'Use log(a × b) = log a + log b.',
        'Use log(a^n) = n log a.'
      ]
    },
    {
      id: 'bayes-mle',
      category: 'statistics',
      name: 'Maximum Likelihood Estimate',
      description: 'Find the peak of the likelihood function',
      starting_equation: '\\ell(p) = k \\log p + (n-k) \\log(1-p)',
      target_equation: '\\hat{p} = \\frac{k}{n}',
      vars: ['p', 'k', 'n', '\\ell', '\\log', '\\hat'],
      valid_forms: [
        '\\ell(p) = k \\log p + (n-k) \\log(1-p)',
        '\\frac{d\\ell}{dp} = \\frac{k}{p} - \\frac{n-k}{1-p}',
        '\\frac{k}{p} = \\frac{n-k}{1-p}',
        'k(1-p) = p(n-k)',
        'k = pn',
        '\\hat{p} = \\frac{k}{n}'
      ],
      hints: [
        'Differentiate: d/dp of log p is 1/p.',
        'Set the derivative equal to zero.',
        'Cross-multiply and solve for p.'
      ]
    },
    {
      id: 'bayes-width',
      category: 'statistics',
      name: 'Posterior Width (1/√N Law)',
      description: 'Derive why uncertainty shrinks as 1/√N',
      starting_equation: '\\frac{d^2\\ell}{dp^2}\\bigg|_{p=\\hat{p}} = -\\frac{n}{\\hat{p}(1-\\hat{p})}',
      target_equation: '\\text{SD} = \\sqrt{\\frac{\\hat{p}(1-\\hat{p})}{n}}',
      vars: ['p', 'n', '\\ell', '\\hat', '\\text{SD}'],
      valid_forms: [
        '\\frac{d^2\\ell}{dp^2} = -\\frac{n}{\\hat{p}(1-\\hat{p})}',
        '\\sigma^2 = \\frac{1}{\\left|\\frac{d^2\\ell}{dp^2}\\right|}',
        '\\sigma^2 = \\frac{\\hat{p}(1-\\hat{p})}{n}',
        '\\text{SD} = \\sqrt{\\frac{\\hat{p}(1-\\hat{p})}{n}}',
        '\\text{SD} \\propto \\frac{1}{\\sqrt{n}}'
      ],
      hints: [
        'Variance equals 1 divided by the curvature.',
        'Substitute the second derivative at the peak.',
        'SD is the square root of variance.'
      ]
    },
    {
      id: 'bayes-beta-mean',
      category: 'statistics',
      name: 'Beta Distribution Mean',
      description: 'Mean of Beta(α, β) distribution',
      starting_equation: 'f(p) \\propto p^{\\alpha-1}(1-p)^{\\beta-1}',
      target_equation: '\\mathbb{E}[p] = \\frac{\\alpha}{\\alpha + \\beta}',
      vars: ['f', 'p', '\\alpha', '\\beta', '\\mathbb'],
      valid_forms: [
        'f(p) \\propto p^{\\alpha-1}(1-p)^{\\beta-1}',
        '\\mathbb{E}[p] = \\int_0^1 p \\cdot f(p) \\, dp',
        '\\mathbb{E}[p] = \\frac{\\alpha}{\\alpha + \\beta}'
      ],
      hints: [
        'The mean is the integral of p times the density.',
        'Use the Beta function B(α, β) = Γ(α)Γ(β)/Γ(α+β).',
        'The integral of p^α (1-p)^(β-1) is B(α+1, β).'
      ]
    }
  ];

  // ── Shared module ──
  const C = window.WhyCommon;
  const waitForPyodide = C.waitForPyodide;
  const canonicalizeLatex = C.canonicalizeLatex;
  const transcribeMultiLine = C.transcribeMultiLine;
  const getStrokeWidth = C.getStrokeWidth;
  const findStrokeHitByPoint = C.findStrokeHitByPoint;
  const isEraserPointerEvent = C.isEraserPointerEvent;
  const makeEraserToggle = C.makeEraserToggle;
  const makeStrokeWidthSlider = C.makeStrokeWidthSlider;
  const esc = C.esc;

  // ── State ──
  let currentEquation = null;
  const STORAGE_KEY = 'why-academy-playground-progress';
  let progress = loadProgress();

  // ── Boot ──
  document.addEventListener('DOMContentLoaded', async () => {
    if (window.WhyAuth) WhyAuth.init();
    C.initSettingsModal();
    initPlayground();
    // Playground always needs SymPy for verification.
    C.startPyodidePreload(function () {
      C.ensureSympy().catch(function (e) { console.warn('sympy preload failed:', e); });
      return true;
    });
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
            C.pyodide.globals.set('_s', canon);
            C.pyodide.globals.set('_forms', C.pyodide.toPy(validForms));
            matchIdx = await C.pyodide.runPythonAsync('find_matching_form(_s, _forms)');
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

})();
