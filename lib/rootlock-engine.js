export const ROOT_CLASSIFICATIONS = Object.freeze({
  TWO: 'two',
  ONE: 'one',
  NONE: 'none',
});

const PHASES = Object.freeze([
  { id: 'pair-positive', label: 'Pair locks', start: 0, end: 2 },
  { id: 'quadratic-positive', label: 'Encoded pairs', start: 3, end: 5 },
  { id: 'signed-roots', label: 'Signed roots', start: 6, end: 8 },
  { id: 'repeated-roots', label: 'Double roots', start: 9, end: 11 },
  { id: 'flow', label: 'Endless flow', start: 12, end: Infinity },
]);

function randomInt(rng, min, max) {
  return Math.floor(rng() * (max - min + 1)) + min;
}

function distinctPair(rng, min, max) {
  const first = randomInt(rng, min, max);
  let second = randomInt(rng, min, max);
  if (first === second) second = second === max ? min : second + 1;
  return [first, second];
}

function normalizedRound(round) {
  return Number.isInteger(round) && round >= 0 ? round : 0;
}

function rootData(roots) {
  const ordered = [...roots].sort((left, right) => left - right);
  const sum = ordered[0] + ordered[1];
  const product = ordered[0] * ordered[1];
  return {
    roots: ordered,
    sum,
    product,
    coefficients: { a: 1, b: -sum, c: product },
  };
}

export function phaseForRound(round) {
  const value = normalizedRound(round);
  return PHASES.find((phase) => value >= phase.start && value <= phase.end);
}

function createRootPuzzle(round, phase, rng) {
  let roots;
  let family;

  if (phase.id === 'pair-positive' && round < 3) {
    roots = [[3, 4], [3, 5], [2, 7]][round];
    family = 'positive';
  } else if (phase.id === 'quadratic-positive') {
    roots = distinctPair(rng, 1, phase.id === 'pair-positive' ? 7 : 10);
    family = 'positive';
  } else if (phase.id === 'signed-roots') {
    const signedStep = round - phase.start;
    if (signedStep === 0) {
      roots = [-randomInt(rng, 1, 7), randomInt(rng, 1, 8)];
      family = 'mixed signs';
    } else if (signedStep === 1) {
      roots = distinctPair(rng, 1, 7).map((value) => -value);
      family = 'negative';
    } else {
      roots = [0, randomInt(rng, 1, 2) === 1 ? randomInt(rng, 1, 8) : -randomInt(rng, 1, 8)];
      family = 'zero root';
    }
  } else if (phase.id === 'repeated-roots') {
    let root = randomInt(rng, -6, 7);
    if (root === 0) root = 3;
    roots = [root, root];
    family = 'repeated';
  } else {
    const familyStep = round % 3;
    if (familyStep === 0) {
      roots = distinctPair(rng, 1, 12);
      family = 'positive';
    } else if (familyStep === 1) {
      roots = [-randomInt(rng, 1, 9), randomInt(rng, 1, 10)];
      family = 'mixed signs';
    } else {
      const root = randomInt(rng, -8, 8) || 2;
      roots = [root, root];
      family = 'repeated';
    }
  }

  const data = rootData(roots);
  return {
    id: `root-${round}-${data.roots.join('-')}`,
    kind: phase.id === 'pair-positive' ? 'pair' : 'quadratic',
    family,
    phase: phase.label,
    round,
    ...data,
    discriminant: data.coefficients.b ** 2 - 4 * data.coefficients.a * data.coefficients.c,
  };
}

function createScannerPuzzle(round, rng) {
  const scannerIndex = Math.floor((round - 12) / 4);
  const target = [ROOT_CLASSIFICATIONS.TWO, ROOT_CLASSIFICATIONS.ONE, ROOT_CLASSIFICATIONS.NONE][scannerIndex % 3];
  let data;

  if (target === ROOT_CLASSIFICATIONS.TWO) {
    data = rootData(distinctPair(rng, -7, 8));
  } else if (target === ROOT_CLASSIFICATIONS.ONE) {
    const root = randomInt(rng, -6, 7);
    data = rootData([root, root]);
  } else {
    const b = randomInt(rng, -6, 6);
    const c = Math.floor((b * b) / 4) + randomInt(rng, 1, 5);
    data = {
      roots: [],
      sum: null,
      product: null,
      coefficients: { a: 1, b, c },
    };
  }

  const discriminant = data.coefficients.b ** 2 - 4 * data.coefficients.a * data.coefficients.c;
  return {
    id: `scan-${round}-${data.coefficients.b}-${data.coefficients.c}`,
    kind: 'discriminant',
    family: 'scanner',
    phase: 'Discriminant scanner',
    round,
    ...data,
    discriminant,
    classification: classifyDiscriminant(discriminant),
  };
}

export function generatePuzzle({ round = 0, rng = Math.random } = {}) {
  const value = normalizedRound(round);
  const phase = phaseForRound(value);
  const scannerRound = phase.id === 'flow' && (value - phase.start) % 4 === 3;
  return scannerRound ? createScannerPuzzle(value, rng) : createRootPuzzle(value, phase, rng);
}

export function classifyDiscriminant(discriminant) {
  if (discriminant > 0) return ROOT_CLASSIFICATIONS.TWO;
  if (discriminant === 0) return ROOT_CLASSIFICATIONS.ONE;
  return ROOT_CLASSIFICATIONS.NONE;
}

export function checkRootAnswer(puzzle, values) {
  if (!puzzle || !Array.isArray(puzzle.roots) || !Array.isArray(values) || values.length !== 2) return false;
  const normalized = values.map((value) => String(value).trim());
  if (normalized.some((value) => value === '')) return false;
  const parsed = normalized.map(Number);
  if (parsed.some((value) => !Number.isFinite(value))) return false;
  parsed.sort((left, right) => left - right);
  return parsed[0] === puzzle.roots[0] && parsed[1] === puzzle.roots[1];
}

export function evaluateRootPair(puzzle, values) {
  const empty = {
    complete: false,
    sum: null,
    product: null,
    sumMatches: false,
    productMatches: false,
  };
  if (!puzzle || !Array.isArray(values) || values.length !== 2) return empty;
  const normalized = values.map((value) => String(value).trim());
  if (normalized.some((value) => value === '')) return empty;
  const parsed = normalized.map(Number);
  if (parsed.some((value) => !Number.isFinite(value))) return empty;
  const sum = parsed[0] + parsed[1];
  const product = parsed[0] * parsed[1];
  return {
    complete: true,
    sum,
    product,
    sumMatches: sum === puzzle.sum,
    productMatches: product === puzzle.product,
  };
}

export function checkClassification(puzzle, classification) {
  return Boolean(puzzle && puzzle.kind === 'discriminant' && puzzle.classification === classification);
}

export function formatQuadratic({ a, b, c }) {
  const terms = [];
  const lead = a === 1 ? 'x²' : a === -1 ? '−x²' : `${a}x²`;
  terms.push(lead);

  if (b !== 0) {
    const magnitude = Math.abs(b);
    terms.push(`${b < 0 ? '−' : '+'} ${magnitude === 1 ? '' : magnitude}x`);
  }
  if (c !== 0) terms.push(`${c < 0 ? '−' : '+'} ${Math.abs(c)}`);

  return `${terms.join(' ')} = 0`;
}

function factorForRoot(root) {
  if (root === 0) return 'x';
  return root < 0 ? `(x + ${Math.abs(root)})` : `(x − ${root})`;
}

export function formatFactorization(roots) {
  return `${factorForRoot(roots[0])}${factorForRoot(roots[1])} = 0`;
}

export function createSeededRng(seed) {
  let value = seed >>> 0;
  return function seededRandom() {
    value += 0x6D2B79F5;
    let result = value;
    result = Math.imul(result ^ (result >>> 15), result | 1);
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}
