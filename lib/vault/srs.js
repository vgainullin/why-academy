// Why Academy — spaced repetition for vault cards (FSRS via ts-fsrs)
//
// Cards store their FSRS state with dates as unix ms so the item stays plain
// JSON; worker/vault.js only requires srs.due and srs.state.

import { fsrs, createEmptyCard, Rating } from 'https://cdn.jsdelivr.net/npm/ts-fsrs@5.2.3/dist/index.mjs';

const scheduler = fsrs({ enable_fuzz: true });

export const GRADES = [
  { rating: Rating.Again, label: 'Again', key: '1' },
  { rating: Rating.Hard, label: 'Hard', key: '2' },
  { rating: Rating.Good, label: 'Good', key: '3' },
  { rating: Rating.Easy, label: 'Easy', key: '4' },
];

function toStored(card) {
  return {
    due: card.due.getTime(),
    stability: card.stability,
    difficulty: card.difficulty,
    elapsed_days: card.elapsed_days,
    scheduled_days: card.scheduled_days,
    learning_steps: card.learning_steps,
    reps: card.reps,
    lapses: card.lapses,
    state: card.state,
    last_review: card.last_review ? card.last_review.getTime() : null,
  };
}

function fromStored(s) {
  return {
    ...s,
    due: new Date(s.due),
    last_review: s.last_review ? new Date(s.last_review) : undefined,
  };
}

export function newSrs(now = Date.now()) {
  return toStored(createEmptyCard(new Date(now)));
}

// The outcome of each grade for one review. Fuzz makes every call random,
// so the buttons and the saved schedule must come from the same preview.
// Returns [{ label, interval, srs }] in GRADES order.
export function previewReview(srs, now = Date.now()) {
  const preview = scheduler.repeat(fromStored(srs), new Date(now));
  return GRADES.map(g => {
    const card = preview[g.rating].card;
    return { label: g.label, interval: formatInterval(card.due.getTime() - now), srs: toStored(card) };
  });
}

function formatInterval(ms) {
  const min = ms / 60000;
  if (min < 60) return Math.max(1, Math.round(min)) + 'm';
  const h = min / 60;
  if (h < 24) return Math.round(h) + 'h';
  const d = h / 24;
  if (d < 30) return Math.round(d) + 'd';
  if (d < 365) return Math.round(d / 30) + 'mo';
  return (d / 365).toFixed(1) + 'y';
}
