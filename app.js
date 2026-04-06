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
    if (window.WhyAuth) WhyAuth.init();

    // Re-render feedback toolbars when auth state changes
    document.addEventListener('whyauth:change', () => {
      document.querySelectorAll('.feedback-toolbar').forEach(updateFeedbackToolbarVisibility);
      updateSendButton();
    });

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
