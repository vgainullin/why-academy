import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import '../lib/sync.js';
import { SettingsSchema } from '../worker/settings.js';

const { readLocal, writeLocal, merge, emptyDoc } = globalThis.WhySync._internal;

const PLAYGROUND_KEY = 'why-academy-playground-progress';
const ROOTLOCK_KEY = 'why-academy.rootlock.progress.v1';
const TIMES_KEY = 'why-academy.sync.pref-times';

function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: k => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: k => map.delete(k),
    dump: () => Object.fromEntries(map),
  };
}

describe('settings sync', () => {
  test('readLocal produces a document the worker schema accepts', () => {
    const storage = memoryStorage({
      handwriteBackend: 'openrouter',
      handwriteStrokeWidth: '9',
      openrouterApiKey: 'c2VjcmV0',
      [PLAYGROUND_KEY]: JSON.stringify({
        'phy-osc-omega': { completed: true, firstCompleted: 10, lastCompleted: 20 },
        '__proto__': { completed: true },
        'bad id!': { completed: true },
      }),
      [ROOTLOCK_KEY]: JSON.stringify({ bestStreak: 7 }),
    });
    const doc = readLocal(storage);
    assert.ok(SettingsSchema.safeParse(doc).success, JSON.stringify(SettingsSchema.safeParse(doc).error));
    assert.deepEqual(Object.keys(doc.playground), ['phy-osc-omega']);
    assert.equal(doc.rootlock.bestStreak, 7);
    assert.ok(SettingsSchema.safeParse(emptyDoc()).success);
  });

  test('never includes the OpenRouter API key', () => {
    const doc = readLocal(memoryStorage({ openrouterApiKey: 'c2VjcmV0' }));
    assert.ok(!JSON.stringify(doc).includes('c2VjcmV0'));
  });

  test('prefs: newer timestamp wins; unsynced local value loses to server', () => {
    const local = readLocal(memoryStorage({ handwriteBackend: 'lmstudio', handwriteModel: 'a' }));
    const server = emptyDoc();
    server.prefs.handwriteBackend = { value: 'openrouter', t: 5 };
    const merged = merge(local, server);
    assert.equal(merged.prefs.handwriteBackend.value, 'openrouter');
    assert.equal(merged.prefs.handwriteModel.value, 'a');

    const newer = readLocal(memoryStorage({
      handwriteBackend: 'lmstudio',
      [TIMES_KEY]: JSON.stringify({ handwriteBackend: 9 }),
    }));
    assert.equal(merge(newer, server).prefs.handwriteBackend.value, 'lmstudio');
  });

  test('prefs: a newer removal propagates', () => {
    const server = emptyDoc();
    server.prefs.handwriteEndpoint = { value: null, t: 50 };
    const storage = memoryStorage({
      handwriteEndpoint: 'http://localhost:1234',
      [TIMES_KEY]: JSON.stringify({ handwriteEndpoint: 10 }),
    });
    const changed = writeLocal(storage, merge(readLocal(storage), server));
    assert.deepEqual(changed, ['handwriteEndpoint']);
    assert.equal(storage.getItem('handwriteEndpoint'), null);
  });

  test('playground progress is a union; rootlock keeps the best streak', () => {
    const a = emptyDoc();
    a.playground.x = { completed: true, firstCompleted: 5, lastCompleted: 6 };
    a.rootlock.bestStreak = 3;
    const b = emptyDoc();
    b.playground.x = { completed: false, firstCompleted: 2, lastCompleted: 9 };
    b.playground.y = { completed: true };
    b.rootlock.bestStreak = 11;
    const m = merge(a, b);
    assert.deepEqual(m.playground.x, { completed: true, firstCompleted: 2, lastCompleted: 9 });
    assert.deepEqual(m.playground.y, { completed: true });
    assert.equal(m.rootlock.bestStreak, 11);
  });

  test('writeLocal reports only changed keys and preserves extra local fields', () => {
    const storage = memoryStorage({
      [PLAYGROUND_KEY]: JSON.stringify({ x: { completed: true, firstCompleted: 1, note: 'keep' } }),
      [ROOTLOCK_KEY]: JSON.stringify({ bestStreak: 4 }),
    });
    assert.deepEqual(writeLocal(storage, readLocal(storage)), []);

    const server = emptyDoc();
    server.playground.y = { completed: true, firstCompleted: 3 };
    server.rootlock.bestStreak = 8;
    const changed = writeLocal(storage, merge(readLocal(storage), server));
    assert.deepEqual(changed.sort(), [PLAYGROUND_KEY, ROOTLOCK_KEY].sort());
    const pg = JSON.parse(storage.getItem(PLAYGROUND_KEY));
    assert.equal(pg.x.note, 'keep');
    assert.deepEqual(pg.y, { completed: true, firstCompleted: 3 });
    assert.equal(JSON.parse(storage.getItem(ROOTLOCK_KEY)).bestStreak, 8);
  });

  test('worker schema rejects unknown keys and prototype-like ids', () => {
    const doc = emptyDoc();
    assert.ok(!SettingsSchema.safeParse({ ...doc, extra: 1 }).success);
    assert.ok(!SettingsSchema.safeParse({ ...doc, prefs: { openrouterApiKey: { value: 'k', t: 1 } } }).success);
    const proto = JSON.parse('{"__proto__": {"completed": true}}');
    const parsed = SettingsSchema.safeParse({ ...doc, playground: proto });
    assert.ok(!parsed.success || Object.keys(parsed.data.playground).length === 0);
    assert.ok(!SettingsSchema.safeParse({ ...doc, playground: { constructor: 1 } }).success);
  });
});
