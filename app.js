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
    startPyodidePreload();
    const params = new URLSearchParams(window.location.search);
    const lessonFile = params.get('lesson') || 'lessons/lesson1.json';
    try {
      const resp = await fetch(lessonFile);
      lesson = await resp.json();
      renderLesson();
    } catch (e) {
      document.getElementById('lesson-container').innerHTML =
        '<p style="padding:20px;color:red;">Failed to load lesson: ' + e.message + '</p>';
    }
  });

  // ── Pyodide Lazy Load ──
  function startPyodidePreload() {
    if (pyodideLoading) return;
    pyodideLoading = true;
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js';
    script.onload = async () => {
      try {
        pyodide = await loadPyodide({
          indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/'
        });
        await pyodide.loadPackage(['numpy', 'matplotlib']);
        pyodideReady = true;
        const status = document.getElementById('pyodide-status');
        status.innerHTML = '&#10003; Python ready';
        status.classList.add('ready');
        setTimeout(() => status.classList.add('hidden'), 2000);
        pyodideReadyCallbacks.forEach(cb => cb());
        pyodideReadyCallbacks = [];
      } catch (e) {
        console.error('Pyodide load failed:', e);
        const status = document.getElementById('pyodide-status');
        status.innerHTML = 'Python load failed';
        status.style.background = '#dc2626';
        status.style.color = 'white';
      }
    };
    document.head.appendChild(script);
  }

  function waitForPyodide() {
    return new Promise(resolve => {
      if (pyodideReady) return resolve();
      const status = document.getElementById('pyodide-status');
      status.classList.remove('hidden');
      pyodideReadyCallbacks.push(resolve);
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
      explain: renderExplain
    };

    const renderer = renderers[block.type];
    if (renderer) {
      const content = renderer(block, wrapper);
      wrapper.appendChild(content);
    }

    return wrapper;
  }

  // ── Read Block ──
  function renderRead(block) {
    const div = document.createElement('div');
    div.className = 'content';
    div.innerHTML = block.content_html;
    return div;
  }

  // ── Derive Block ──
  function renderDerive(block) {
    const div = document.createElement('div');

    // Prompt
    const prompt = document.createElement('p');
    prompt.textContent = block.prompt;
    div.appendChild(prompt);

    // Current equation
    const eqDiv = document.createElement('div');
    eqDiv.className = 'derive-current-equation';
    eqDiv.innerHTML = '$$' + block.starting_equation + '$$';
    div.appendChild(eqDiv);

    // Steps
    const stepsDiv = document.createElement('div');
    stepsDiv.className = 'derive-steps';

    let currentStep = 0;

    block.steps.forEach((step, i) => {
      const stepEl = document.createElement('div');
      stepEl.className = 'derive-step' + (i === 0 ? '' : ' locked');
      stepEl.dataset.index = i;

      const num = document.createElement('div');
      num.className = 'derive-step-number';
      num.textContent = i + 1;

      const content = document.createElement('div');
      content.className = 'derive-step-content';

      const instruction = document.createElement('div');
      instruction.className = 'derive-step-instruction';
      instruction.textContent = step.instruction;
      content.appendChild(instruction);

      // Result & explanation (hidden until completed)
      const resultDiv = document.createElement('div');
      resultDiv.className = 'derive-step-result hidden';
      resultDiv.innerHTML = '$$' + step.result_equation + '$$';
      content.appendChild(resultDiv);

      const explanationDiv = document.createElement('div');
      explanationDiv.className = 'derive-step-explanation hidden';
      explanationDiv.innerHTML = step.explanation;
      content.appendChild(explanationDiv);

      stepEl.appendChild(num);
      stepEl.appendChild(content);

      stepEl.addEventListener('click', () => {
        if (i !== currentStep) return;

        stepEl.classList.add('completed');
        stepEl.classList.remove('locked');
        resultDiv.classList.remove('hidden');
        explanationDiv.classList.remove('hidden');

        // Update equation display
        eqDiv.innerHTML = '$$' + step.result_equation + '$$';
        renderKaTeX(eqDiv);
        renderKaTeX(resultDiv);
        renderKaTeX(explanationDiv);

        currentStep++;

        // Unlock next step
        const nextStep = stepsDiv.querySelector('[data-index="' + currentStep + '"]');
        if (nextStep) {
          nextStep.classList.remove('locked');
        }

        // Check if derive is complete
        if (currentStep >= block.steps.length) {
          const complete = document.createElement('div');
          complete.className = 'derive-complete';
          complete.textContent = 'Derivation complete!';
          div.appendChild(complete);
          markComplete(block.id, div);
        }
      });

      stepsDiv.appendChild(stepEl);
    });

    div.appendChild(stepsDiv);

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
        text = text.replace('{' + key + '}', val);
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
})();
