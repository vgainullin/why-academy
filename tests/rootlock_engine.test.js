import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ROOT_CLASSIFICATIONS,
  checkClassification,
  checkRootAnswer,
  classifyDiscriminant,
  createSeededRng,
  formatFactorization,
  formatQuadratic,
  generatePuzzle,
  phaseForRound,
} from '../lib/rootlock-engine.js';

describe('ROOTLOCK puzzle engine', () => {
  test('progresses one mechanic at a time before endless flow', () => {
    assert.equal(phaseForRound(0).id, 'pair-positive');
    assert.equal(phaseForRound(3).id, 'quadratic-positive');
    assert.equal(phaseForRound(6).id, 'signed-roots');
    assert.equal(phaseForRound(9).id, 'repeated-roots');
    assert.equal(phaseForRound(12).id, 'flow');
  });

  test('generates coefficients backward from the hidden roots', () => {
    const puzzle = generatePuzzle({ round: 4, rng: createSeededRng(42) });
    const [left, right] = puzzle.roots;
    assert.equal(puzzle.coefficients.a, 1);
    assert.equal(puzzle.coefficients.b, -(left + right));
    assert.equal(puzzle.coefficients.c, left * right);
    assert.equal(puzzle.discriminant, (left - right) ** 2);
  });

  test('accepts either root order and requires a repeated root twice', () => {
    const regular = generatePuzzle({ round: 3, rng: createSeededRng(7) });
    assert.equal(checkRootAnswer(regular, regular.roots), true);
    assert.equal(checkRootAnswer(regular, [...regular.roots].reverse()), true);
    assert.equal(checkRootAnswer(regular, ['', regular.roots[1]]), false);

    const repeated = generatePuzzle({ round: 9, rng: createSeededRng(9) });
    assert.equal(repeated.roots[0], repeated.roots[1]);
    assert.equal(checkRootAnswer(repeated, repeated.roots), true);
    assert.equal(checkRootAnswer(repeated, [repeated.roots[0], repeated.roots[0] + 1]), false);
  });

  test('introduces mixed signs, negative roots, and zero separately', () => {
    const mixed = generatePuzzle({ round: 6, rng: createSeededRng(1) });
    const negative = generatePuzzle({ round: 7, rng: createSeededRng(2) });
    const zero = generatePuzzle({ round: 8, rng: createSeededRng(3) });
    assert.ok(mixed.roots[0] < 0 && mixed.roots[1] > 0);
    assert.ok(negative.roots.every((root) => root < 0));
    assert.ok(zero.roots.includes(0));
  });

  test('scanner cycles through all three real-root classifications', () => {
    const rounds = [15, 19, 23];
    const puzzles = rounds.map((round) => generatePuzzle({ round, rng: createSeededRng(round) }));
    assert.deepEqual(
      puzzles.map((puzzle) => puzzle.classification),
      [ROOT_CLASSIFICATIONS.TWO, ROOT_CLASSIFICATIONS.ONE, ROOT_CLASSIFICATIONS.NONE],
    );
    puzzles.forEach((puzzle) => {
      assert.equal(puzzle.classification, classifyDiscriminant(puzzle.discriminant));
      assert.equal(checkClassification(puzzle, puzzle.classification), true);
    });
  });

  test('seeded generation is reproducible and formatting is readable', () => {
    const first = generatePuzzle({ round: 5, rng: createSeededRng(99) });
    const second = generatePuzzle({ round: 5, rng: createSeededRng(99) });
    assert.deepEqual(first, second);
    assert.match(formatQuadratic({ a: 1, b: -5, c: 6 }), /^x² − 5x \+ 6 = 0$/);
    assert.equal(formatFactorization([-2, 3]), '(x + 2)(x − 3) = 0');
  });
});
