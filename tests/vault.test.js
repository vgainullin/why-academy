import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import {
  validateItem,
  pushItems,
  pullItems,
  isPdf,
  sha256Hex,
} from '../worker/vault.js';
import {
  newId,
  inkId,
  mergeInk,
  resolveIncoming,
  parseLinks,
  buildLinkIndex,
  notesForDoc,
  selectionRects,
  studyQueue,
  nextUpdatedAt,
} from '../lib/vault/model.js';

const DOC = 'a'.repeat(64);
const ACCOUNT = 'acct1';

// Minimal D1 binding over node:sqlite: enough of prepare/bind/run/all/first
// and batch (one transaction) to exercise the real SQL.
function fakeD1() {
  const db = new DatabaseSync(':memory:');
  db.exec("CREATE TABLE accounts (id TEXT PRIMARY KEY)");
  db.exec(readFileSync(new URL('../worker/migrations/0003_vault.sql', import.meta.url), 'utf8'));
  db.prepare('INSERT INTO accounts (id) VALUES (?)').run(ACCOUNT);
  const wrap = (sql, args = []) => ({
    bind: (...a) => wrap(sql, a),
    run: async () => ({ meta: { changes: Number(db.prepare(sql).run(...args).changes) } }),
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    first: async () => db.prepare(sql).get(...args) || null,
    _exec: () => db.prepare(sql).run(...args),
  });
  return {
    raw: db,
    prepare: sql => wrap(sql),
    batch: async stmts => {
      db.exec('BEGIN');
      try {
        for (const s of stmts) s._exec();
        db.exec('COMMIT');
      } catch (e) {
        db.exec('ROLLBACK');
        throw e;
      }
    },
  };
}

function item(kind, data, extra = {}) {
  return { id: newId(), kind, updatedAt: 1000, deleted: false, data, ...extra };
}

const stroke = id => ({ id, tool: 'pen', color: '#1f2937', width: 0.003, points: [0.1, 0.1, 0.5, 0.2, 0.2, 0.5] });

describe('vault item validation', () => {
  test('accepts every kind the client creates', () => {
    const items = [
      { id: DOC, kind: 'doc', updatedAt: 1, deleted: false, data: { title: 'Attention', filename: 'a.pdf', pages: 12, size: 1000 } },
      item('note', { title: 'Softmax', blocks: [{ id: newId(), type: 'md', text: 'see [[@x]]' }, { id: newId(), type: 'ink', aspect: 0.5, strokes: [stroke(newId())] }] }),
      item('anno', { docId: DOC, page: 3, type: 'highlight', rects: [[0.1, 0.2, 0.3, 0.02]], quote: 'scaled dot-product', color: 'yellow' }),
      { id: inkId(DOC, 3), kind: 'ink', updatedAt: 1, deleted: false, data: { docId: DOC, page: 3, strokes: [stroke(newId())], erased: [] } },
      item('card', { front: 'Why scale by sqrt(d_k)?', back: 'Keeps logits O(1)', docId: DOC, srs: { due: 0, state: 0 } }),
      item('task', { text: 'Explain layer norm', type: 'explain', status: 'open', docId: DOC }),
    ];
    for (const it of items) {
      const { error } = validateItem(it);
      assert.equal(error, undefined, it.kind + ': ' + JSON.stringify(error));
    }
  });

  test('keeps unknown data fields from newer clients', () => {
    const { item: out } = validateItem(item('task', { text: 't', type: 'todo', status: 'open', priority: 2 }));
    assert.equal(out.data.priority, 2);
  });

  test('rejects bad shapes', () => {
    assert.ok(validateItem({ ...item('task', {}), kind: 'nope' }).error);
    assert.ok(validateItem(item('anno', { docId: 'short', page: 1, type: 'highlight', rects: [[0, 0, 1, 1]], quote: '', color: 'y' })).error);
    assert.ok(validateItem({ id: 'bad id!', kind: 'task', updatedAt: 1, deleted: false, data: {} }).error);
    assert.ok(validateItem({ id: 'not-a-sha', kind: 'doc', updatedAt: 1, deleted: false, data: { title: '', filename: '', pages: 0, size: 0 } }).error);
  });

  test('tombstones carry no data', () => {
    const { item: out } = validateItem({ ...item('note', { anything: true }), deleted: true });
    assert.deepEqual(out.data, {});
  });
});

describe('vault push/pull', () => {
  test('seq increases and pull returns only newer items', async () => {
    const db = fakeD1();
    const a = item('task', { text: 'a', type: 'todo', status: 'open' });
    const b = item('task', { text: 'b', type: 'todo', status: 'open' });
    await pushItems(db, ACCOUNT, [a, b]);
    const first = await pullItems(db, ACCOUNT, 0);
    assert.deepEqual(first.items.map(i => i.id), [a.id, b.id]);
    assert.equal(first.more, false);

    await pushItems(db, ACCOUNT, [{ ...a, updatedAt: 2000, data: { ...a.data, status: 'done' } }]);
    const second = await pullItems(db, ACCOUNT, first.cursor);
    assert.deepEqual(second.items.map(i => [i.id, i.data.status]), [[a.id, 'done']]);
    assert.ok(second.cursor > first.cursor);
  });

  test('an older write loses and comes back as stale', async () => {
    const db = fakeD1();
    const a = item('task', { text: 'new', type: 'todo', status: 'open' }, { updatedAt: 5000 });
    await pushItems(db, ACCOUNT, [a]);
    const { stale } = await pushItems(db, ACCOUNT, [{ ...a, updatedAt: 4000, data: { ...a.data, text: 'old' } }]);
    assert.equal(stale.length, 1);
    assert.equal(stale[0].data.text, 'new');
    const { items } = await pullItems(db, ACCOUNT, 0);
    assert.equal(items[0].data.text, 'new');
  });

  test('re-pushing the same copy is not stale', async () => {
    const db = fakeD1();
    const a = item('task', { text: 'x', type: 'todo', status: 'open' });
    await pushItems(db, ACCOUNT, [a]);
    assert.deepEqual((await pushItems(db, ACCOUNT, [a])).stale, []);
  });

  test('an id cannot change kind', async () => {
    const db = fakeD1();
    const a = item('task', { text: 'x', type: 'todo', status: 'open' });
    await pushItems(db, ACCOUNT, [a]);
    const { stale } = await pushItems(db, ACCOUNT, [{ ...a, kind: 'note', updatedAt: 9000, data: { title: 'n', blocks: [] } }]);
    assert.equal(stale[0].kind, 'task');
  });

  test('accounts are isolated', async () => {
    const db = fakeD1();
    db.raw.prepare('INSERT INTO accounts (id) VALUES (?)').run('other');
    await pushItems(db, ACCOUNT, [item('task', { text: 'mine', type: 'todo', status: 'open' })]);
    assert.equal((await pullItems(db, 'other', 0)).items.length, 0);
  });

  test('pull pages through large result sets', async () => {
    const db = fakeD1();
    const many = Array.from({ length: 250 }, (_, i) => item('task', { text: 't' + i, type: 'todo', status: 'open' }));
    await pushItems(db, ACCOUNT, many.slice(0, 200));
    await pushItems(db, ACCOUNT, many.slice(200));
    const seen = [];
    let cursor = 0;
    for (;;) {
      const page = await pullItems(db, ACCOUNT, cursor);
      seen.push(...page.items.map(i => i.id));
      cursor = page.cursor;
      if (!page.more) break;
    }
    assert.equal(new Set(seen).size, 250);
  });
});

describe('vault files', () => {
  test('recognizes PDFs and hashes like the client', async () => {
    assert.ok(isPdf(new TextEncoder().encode('%PDF-1.7\n...')));
    assert.ok(!isPdf(new TextEncoder().encode('<html>')));
    assert.equal(await sha256Hex(new TextEncoder().encode('abc')), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });
});

describe('vault model', () => {
  test('ink merge is a union minus erased strokes', () => {
    const merged = mergeInk(
      { docId: DOC, page: 1, strokes: [stroke('s1'), stroke('s2')], erased: [] },
      { docId: DOC, page: 1, strokes: [stroke('s1'), stroke('s3')], erased: ['s2'] },
    );
    assert.deepEqual(merged.strokes.map(s => s.id).sort(), ['s1', 's3']);
    assert.deepEqual(merged.erased, ['s2']);
  });

  test('incoming copy replaces clean local items', () => {
    const remote = item('task', { text: 'r', type: 'todo', status: 'open' }, { updatedAt: 1 });
    const out = resolveIncoming({ ...remote, data: { text: 'l' }, dirty: false, updatedAt: 99 }, remote, 100);
    assert.equal(out.item, remote);
    assert.equal(out.dirty, false);
  });

  test('newer local edits survive a pull', () => {
    const remote = item('task', { text: 'r', type: 'todo', status: 'open' }, { updatedAt: 1 });
    const local = { ...remote, data: { ...remote.data, text: 'l' }, updatedAt: 5, dirty: true };
    const out = resolveIncoming(local, remote, 100);
    assert.equal(out.item.data.text, 'l');
    assert.equal(out.dirty, true);
  });

  test('dirty ink merges with the incoming copy and stays dirty', () => {
    const id = inkId(DOC, 2);
    const local = { id, kind: 'ink', updatedAt: 10, deleted: false, dirty: true, data: { docId: DOC, page: 2, strokes: [stroke('a')], erased: [] } };
    const remote = { id, kind: 'ink', updatedAt: 20, deleted: false, data: { docId: DOC, page: 2, strokes: [stroke('b')], erased: [] } };
    const out = resolveIncoming(local, remote, 15);
    assert.deepEqual(out.item.data.strokes.map(s => s.id).sort(), ['a', 'b']);
    assert.equal(out.dirty, true);
    assert.ok(out.item.updatedAt > 20);
  });

  test('a losing local note is kept as a conflict copy', () => {
    const remote = item('note', { title: 'Attention', blocks: [{ id: 'b1xxxx', type: 'md', text: 'server' }] }, { updatedAt: 50 });
    const local = { ...remote, data: { ...remote.data, blocks: [{ id: 'b1xxxx', type: 'md', text: 'mine' }] }, updatedAt: 40, dirty: true };
    const out = resolveIncoming(local, remote, 60);
    assert.equal(out.item, remote);
    assert.equal(out.extra.length, 1);
    assert.equal(out.extra[0].data.title, 'Attention (conflict copy)');
    assert.equal(out.extra[0].data.blocks[0].text, 'mine');
  });

  test('nextUpdatedAt never repeats or goes back', () => {
    assert.equal(nextUpdatedAt(100, 50), 101);
    assert.equal(nextUpdatedAt(100, 500), 500);
  });

  test('wikilinks', () => {
    const links = parseLinks('See [[Transformers]] and [[@abc123|eq. 1]] or [[Layer Norm|LN]].');
    assert.deepEqual(links.map(l => [l.type, l.title || l.id, l.label]), [
      ['title', 'Transformers', null],
      ['anno', 'abc123', 'eq. 1'],
      ['title', 'Layer Norm', 'LN'],
    ]);
  });

  test('link index resolves notes, docs and passages; reports missing targets', () => {
    const anno = item('anno', { docId: DOC, page: 1, type: 'highlight', rects: [[0, 0, 1, 1]], quote: 'q', color: 'y' });
    const doc = { id: DOC, kind: 'doc', updatedAt: 1, deleted: false, data: { title: 'Attention Is All You Need' } };
    const target = item('note', { title: 'Softmax', blocks: [] });
    const source = item('note', {
      title: 'Reading log',
      blocks: [{ id: newId(), type: 'md', text: `[[softmax]] [[attention is all you need]] [[@${anno.id}]] [[Nowhere]]` }],
    });
    const idx = buildLinkIndex([anno, doc, target, source]);
    assert.deepEqual(idx.outgoing.get(source.id).map(l => l.kind), ['note', 'doc', 'anno', 'missing']);
    assert.ok(idx.backlinks.get(target.id).has(source.id));
    assert.ok(idx.unresolved.has('nowhere'));
    assert.deepEqual([...notesForDoc(idx, [anno, doc, target, source], DOC)], [source.id]);
  });

  test('selection rects merge per line and normalize', () => {
    const rects = selectionRects(
      [
        { left: 10, top: 100, width: 50, height: 12 },
        { left: 60, top: 101, width: 40, height: 12 },
        { left: 10, top: 120, width: 80, height: 12 },
      ],
      200,
      400,
    );
    assert.deepEqual(rects, [[0.05, 0.25, 0.45, 0.0325], [0.05, 0.3, 0.4, 0.03]]);
  });

  test('study queue orders due cards and splits tasks by status', () => {
    const now = 10_000;
    const card = due => item('card', { front: 'f', back: 'b', srs: { due, state: 2 } });
    const items = [card(500), card(50), card(now + 1), item('task', { text: 'x', type: 'explain', status: 'ready' }), item('task', { text: 'y', type: 'todo', status: 'open' })];
    const q = studyQueue(items, now);
    assert.deepEqual(q.dueCards.map(c => c.data.srs.due), [50, 500]);
    assert.equal(q.toReview.length, 1);
    assert.equal(q.open.length, 1);
  });
});

describe('ink sync across devices', () => {
  const ink = (strokes, updatedAt, erased = []) => ({
    id: inkId(DOC, 1), kind: 'ink', updatedAt, deleted: false, data: { docId: DOC, page: 1, strokes, erased },
  });

  test('two devices inking the same page offline both keep their strokes', async () => {
    const db = fakeD1();
    await pushItems(db, ACCOUNT, [ink([stroke('base')], 100)]);
    // Both devices start from "base", add a stroke offline, then push.
    const a = await pushItems(db, ACCOUNT, [ink([stroke('base'), stroke('fromA')], 200)]);
    const b = await pushItems(db, ACCOUNT, [ink([stroke('base'), stroke('fromB')], 300)]);
    const { items } = await pullItems(db, ACCOUNT, 0);
    assert.deepEqual(items[0].data.strokes.map(s => s.id).sort(), ['base', 'fromA', 'fromB']);
    assert.deepEqual(a.stale, []);
    // B's copy lacked fromA, so B gets the merged page back.
    assert.equal(b.stale.length, 1);
    assert.equal(b.stale[0].data.strokes.length, 3);
  });

  test('an older push still merges instead of being dropped', async () => {
    const db = fakeD1();
    await pushItems(db, ACCOUNT, [ink([stroke('new')], 500)]);
    await pushItems(db, ACCOUNT, [ink([stroke('old')], 100)]);
    const { items } = await pullItems(db, ACCOUNT, 0);
    assert.deepEqual(items[0].data.strokes.map(s => s.id).sort(), ['new', 'old']);
  });

  test('erasing on one device removes the stroke after merge', async () => {
    const db = fakeD1();
    await pushItems(db, ACCOUNT, [ink([stroke('s1'), stroke('s2')], 100)]);
    await pushItems(db, ACCOUNT, [ink([stroke('s2')], 200, ['s1'])]);
    const { items } = await pullItems(db, ACCOUNT, 0);
    assert.deepEqual(items[0].data.strokes.map(s => s.id), ['s2']);
  });

  test('a client that receives a merged page it already covers stays clean', () => {
    const remote = ink([stroke('a'), stroke('b')], 300);
    const local = { ...ink([stroke('a')], 200), dirty: true };
    const out = resolveIncoming(local, remote, 400);
    assert.equal(out.dirty, false);
    assert.equal(out.item, remote);
  });
});

describe('equation LaTeX tidy-up', async () => {
  const { tidyLatex } = await import('../lib/vault/ai.js');

  test('turns plain-text math copied from a PDF into LaTeX', () => {
    assert.equal(tidyLatex('Var( q .k / \\text{sqrt}(d\\_k) ) = d\\_k / d\\_k = 1'), 'Var( q .k / \\sqrt{d_k} ) = d_k / d_k = 1');
    assert.equal(tidyLatex('s_i (\\text{delta}_{ij} - s_j)'), 's_i (\\delta_{ij} - s_j)');
    assert.equal(tidyLatex('\\text{Var}(x) + sqrt(y)'), '\\operatorname{Var}(x) + \\sqrt{y}');
  });

  test('leaves good LaTeX alone', () => {
    const good = 'q \\cdot k = \\sum_{i=1}^{d_k} q_i k_i, \\quad \\sqrt{x}';
    assert.equal(tidyLatex(good), good);
  });
});
