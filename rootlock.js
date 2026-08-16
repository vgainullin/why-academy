import {
  checkClassification,
  checkRootAnswer,
  formatFactorization,
  formatQuadratic,
  generatePuzzle,
  phaseForRound,
} from './lib/rootlock-engine.js';

const STORAGE_KEY = 'why-academy.rootlock.progress.v1';
const DEMO_KEY = 'why-academy.rootlock.demo-seen.v1';

const elements = {
  machine: document.getElementById('machine'),
  stage: document.getElementById('puzzle-stage'),
  feedback: document.getElementById('feedback'),
  mode: document.getElementById('mode-chip'),
  family: document.getElementById('family-label'),
  phase: document.getElementById('phase-label'),
  run: document.getElementById('run-label'),
  streak: document.getElementById('streak-value'),
  solved: document.getElementById('solved-value'),
  time: document.getElementById('time-value'),
  progress: document.getElementById('track-progress'),
  keyboardHint: document.getElementById('keyboard-hint'),
  sound: document.getElementById('sound-toggle'),
  restart: document.getElementById('restart-button'),
};

const state = {
  round: 0,
  solved: 0,
  streak: 0,
  bestStreak: 0,
  mistakes: 0,
  startedAt: performance.now(),
  puzzle: null,
  locked: false,
  muted: false,
  demoTimers: [],
};

function readProgress() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved && Number.isInteger(saved.bestStreak)) state.bestStreak = saved.bestStreak;
  } catch {
    // Corrupt progress should never block play.
  }
}

function saveProgress() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ bestStreak: state.bestStreak }));
}

function setFeedback(message, tone = '') {
  elements.feedback.textContent = message;
  elements.feedback.dataset.tone = tone;
}

function updateStats(elapsed = null) {
  elements.run.textContent = `RUN ${String(state.round + 1).padStart(2, '0')}`;
  elements.streak.textContent = String(state.streak);
  elements.solved.textContent = String(state.solved);
  if (elapsed !== null) elements.time.textContent = `${elapsed.toFixed(1)}s`;

  const phase = phaseForRound(state.round);
  elements.phase.textContent = phase.label;
  const phaseIndex = ['pair-positive', 'quadratic-positive', 'signed-roots', 'repeated-roots', 'flow'].indexOf(phase.id);
  elements.progress.style.width = `${Math.max(4, (phaseIndex / 4) * 100)}%`;
  document.querySelectorAll('.track-labels span').forEach((label) => {
    label.classList.toggle('is-active', label.dataset.phase === phase.id);
  });
}

function modeCopy(puzzle) {
  if (puzzle.kind === 'pair') return ['PAIR LOCK', 'Find the two hidden numbers.'];
  if (puzzle.kind === 'quadratic') return ['QUADRATIC', 'Release the roots hidden inside.'];
  return ['D SCANNER', 'Predict the number of real roots.'];
}

function renderPuzzle(puzzle) {
  state.puzzle = puzzle;
  state.mistakes = 0;
  state.locked = false;
  state.startedAt = performance.now();
  elements.machine.className = 'machine';
  elements.stage.innerHTML = '';

  const [mode, prompt] = modeCopy(puzzle);
  elements.mode.textContent = mode;
  elements.family.textContent = puzzle.family.toUpperCase();
  elements.keyboardHint.innerHTML = puzzle.kind === 'discriminant'
    ? '<kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd> choose a channel'
    : '<kbd>ENTER</kbd> moves and checks';
  setFeedback(prompt);
  updateStats();

  if (puzzle.kind === 'discriminant') renderScannerPuzzle(puzzle);
  else renderRootPuzzle(puzzle);
}

function renderRootPuzzle(puzzle) {
  const fragment = document.getElementById('root-puzzle-template').content.cloneNode(true);
  const prompt = fragment.querySelector('.puzzle-prompt');
  const equation = fragment.querySelector('.equation-display');
  const constraints = fragment.querySelector('.pair-constraints');
  const form = fragment.querySelector('.root-entry');
  const inputs = [...fragment.querySelectorAll('.root-input')];

  if (puzzle.kind === 'pair') {
    prompt.textContent = 'Two numbers. One sum. One product.';
    equation.hidden = true;
    constraints.hidden = false;
    constraints.querySelector('.target-sum').textContent = puzzle.sum;
    constraints.querySelector('.target-product').textContent = puzzle.product;
  } else {
    prompt.textContent = 'Which two roots open this equation?';
    equation.textContent = formatQuadratic(puzzle.coefficients);
  }

  inputs.forEach((input, index) => {
    input.addEventListener('input', () => updateLiveReadout(inputs, puzzle));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && index === 0 && input.value.trim() !== '') {
        event.preventDefault();
        inputs[1].focus();
      }
    });
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submitRoots(inputs);
  });

  elements.stage.appendChild(fragment);
  requestAnimationFrame(() => inputs[0].focus());
}

function updateLiveReadout(inputs, puzzle) {
  const values = inputs.map((input) => input.value.trim());
  const parsed = values.map(Number);
  const complete = values.every((value) => value !== '') && parsed.every(Number.isFinite);
  const sum = complete ? parsed[0] + parsed[1] : null;
  const product = complete ? parsed[0] * parsed[1] : null;
  updateReadout('sum', sum, puzzle.sum, complete);
  updateReadout('product', product, puzzle.product, complete);
}

function updateReadout(name, value, target, complete) {
  const readout = elements.stage.querySelector(`[data-readout="${name}"]`);
  readout.querySelector('strong').textContent = complete ? value : '—';
  readout.classList.toggle('is-match', complete && value === target);
}

function submitRoots(inputs) {
  if (state.locked) return;
  const values = inputs.map((input) => input.value);
  if (values.some((value) => value.trim() === '')) {
    failAttempt('Both sockets need a number.', inputs);
    return;
  }
  if (!checkRootAnswer(state.puzzle, values)) {
    failAttempt('The sum or product is still locked.', inputs);
    return;
  }
  const factorization = formatFactorization(state.puzzle.roots);
  completePuzzle(`OPEN · ${factorization}`);
}

function renderScannerPuzzle(puzzle) {
  const fragment = document.getElementById('scanner-template').content.cloneNode(true);
  fragment.querySelector('.equation-display').textContent = formatQuadratic(puzzle.coefficients);
  Object.entries(puzzle.coefficients).forEach(([key, value]) => {
    const tile = fragment.querySelector(`[data-coefficient="${key}"]`);
    if (tile) tile.textContent = value < 0 ? `(${value})` : value;
  });
  fragment.querySelectorAll('[data-classification]').forEach((button) => {
    button.addEventListener('click', () => submitClassification(button.dataset.classification));
  });
  elements.stage.appendChild(fragment);
}

function submitClassification(classification) {
  if (state.locked) return;
  if (!checkClassification(state.puzzle, classification)) {
    state.mistakes += 1;
    state.streak = 0;
    updateStats();
    elements.machine.classList.remove('is-error');
    void elements.machine.offsetWidth;
    elements.machine.classList.add('is-error');
    setFeedback('That channel stays closed. Read the sign of D.', 'error');
    playTone('error');
    return;
  }
  const labels = { two: 'TWO REAL CHANNELS', one: 'ONE REPEATED CHANNEL', none: 'NO REAL CHANNEL' };
  completePuzzle(`SCAN COMPLETE · D = ${state.puzzle.discriminant} · ${labels[classification]}`);
}

function failAttempt(message, inputs) {
  state.mistakes += 1;
  state.streak = 0;
  elements.machine.classList.remove('is-error');
  void elements.machine.offsetWidth;
  elements.machine.classList.add('is-error');
  inputs.forEach((input) => input.classList.add('is-error'));
  setTimeout(() => inputs.forEach((input) => input.classList.remove('is-error')), 420);
  setFeedback(message, 'error');
  updateStats();
  inputs[0].focus();
  playTone('error');
}

function completePuzzle(message) {
  state.locked = true;
  const elapsed = (performance.now() - state.startedAt) / 1000;
  state.solved += 1;
  if (state.mistakes === 0) state.streak += 1;
  state.bestStreak = Math.max(state.bestStreak, state.streak);
  saveProgress();
  updateStats(elapsed);
  elements.machine.classList.add('is-open');
  setFeedback(message, 'success');
  playTone('success');
  setTimeout(() => {
    state.round += 1;
    renderPuzzle(generatePuzzle({ round: state.round }));
  }, 1050);
}

function playTone(kind) {
  if (state.muted) return;
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) return;
  const context = new AudioContext();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = kind === 'success' ? 'sine' : 'square';
  oscillator.frequency.setValueAtTime(kind === 'success' ? 330 : 110, context.currentTime);
  if (kind === 'success') oscillator.frequency.exponentialRampToValueAtTime(660, context.currentTime + 0.12);
  gain.gain.setValueAtTime(0.05, context.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.18);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start();
  oscillator.stop(context.currentTime + 0.18);
  oscillator.addEventListener('ended', () => context.close());
}

function handleGlobalKey(event) {
  if (state.locked || state.puzzle?.kind !== 'discriminant') return;
  const map = { 1: 'two', 2: 'one', 3: 'none' };
  if (map[event.key]) submitClassification(map[event.key]);
}

function clearDemoTimers() {
  state.demoTimers.forEach(clearTimeout);
  state.demoTimers = [];
}

function scheduleDemo(callback, delay) {
  const timer = setTimeout(callback, delay);
  state.demoTimers.push(timer);
}

function runSilentDemo() {
  const demoPuzzle = {
    id: 'demo', kind: 'pair', family: 'demonstration', phase: 'Pair locks', round: 0,
    roots: [2, 3], sum: 5, product: 6, coefficients: { a: 1, b: -5, c: 6 }, discriminant: 1,
  };
  renderPuzzle(demoPuzzle);
  state.locked = true;
  elements.machine.classList.add('is-demo');
  setFeedback('WATCH THE LOCK', 'demo');
  const inputs = [...elements.stage.querySelectorAll('.root-input')];
  inputs.forEach((input) => { input.disabled = true; });
  scheduleDemo(() => { inputs[0].value = '2'; updateLiveReadout(inputs, demoPuzzle); }, 450);
  scheduleDemo(() => { inputs[1].value = '3'; updateLiveReadout(inputs, demoPuzzle); }, 900);
  scheduleDemo(() => {
    elements.machine.classList.add('is-open');
    setFeedback('OPEN · (x − 2)(x − 3) = 0', 'success');
  }, 1350);
  scheduleDemo(() => {
    localStorage.setItem(DEMO_KEY, 'true');
    clearDemoTimers();
    state.locked = false;
    renderPuzzle(generatePuzzle({ round: state.round }));
  }, 2200);
}

function restartRun() {
  clearDemoTimers();
  state.round = 0;
  state.solved = 0;
  state.streak = 0;
  state.mistakes = 0;
  elements.time.textContent = '—';
  renderPuzzle(generatePuzzle({ round: 0 }));
}

elements.sound.addEventListener('click', () => {
  state.muted = !state.muted;
  elements.sound.textContent = state.muted ? 'SOUND OFF' : 'SOUND ON';
  elements.sound.setAttribute('aria-pressed', String(state.muted));
});
elements.restart.addEventListener('click', restartRun);
document.addEventListener('keydown', handleGlobalKey);

readProgress();
if (localStorage.getItem(DEMO_KEY)) restartRun();
else runSilentDemo();
