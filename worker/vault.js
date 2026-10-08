// Study vault: synced items (notes, PDF annotations, ink, cards, tasks, doc
// metadata) in D1, and the PDF files in R2.
//
// Sync model: every item has a client-chosen id and a client edit time
// (updatedAt). A write is accepted only if it is newer than the stored copy
// (last-write-wins per item); accepted writes get the next per-account seq.
// Clients pull with "seq > cursor". Pushes that lose return the stored copy
// so the client can adopt it even if its cursor is already past that seq.
//
// Must stay in sync with lib/vault/model.js.

import { z } from 'zod';
import { mergeInk, sameInk } from '../lib/vault/model.js';

export const MAX_PUSH_BYTES = 2 * 1024 * 1024;
export const MAX_PUSH_ITEMS = 200;
export const MAX_PULL_ITEMS = 200;
export const MAX_PULL_BYTES = 4 * 1024 * 1024;
export const MAX_FILE_BYTES = 64 * 1024 * 1024;
export const MAX_ACCOUNT_FILE_BYTES = 4 * 1024 * 1024 * 1024;

const MAX_ITEM_BYTES = { ink: 768 * 1024, note: 512 * 1024 };
const DEFAULT_MAX_ITEM_BYTES = 128 * 1024;
const D1_MAX_PARAMS = 90;

export const ITEM_ID = /^[A-Za-z0-9_-]{6,64}$/;
export const FILE_ID = /^[0-9a-f]{64}$/;

const Id = z.string().regex(ITEM_ID);
const FileId = z.string().regex(FILE_ID);
const Text = max => z.string().max(max);
const Page = z.number().int().min(1).max(100_000);
const Coord = z.number().min(-0.5).max(1.5);
const Rect = z.tuple([Coord, Coord, Coord, Coord]);
const Tags = z.array(Text(64)).max(50);
const Timestamp = z.number().int().nonnegative();

// Points are flat [x, y, pressure, x, y, pressure, ...] in page-normalized
// coordinates (0..1), so ink is independent of zoom.
const Stroke = z.looseObject({
  id: Id,
  tool: z.enum(['pen', 'highlighter']),
  color: Text(32),
  width: z.number().positive().max(0.1),
  points: z.array(z.number().min(-0.5).max(1.5)).max(30_000),
});

const MdBlock = z.looseObject({ id: Id, type: z.literal('md'), text: Text(200_000) });
const InkBlock = z.looseObject({
  id: Id,
  type: z.literal('ink'),
  aspect: z.number().positive().max(10), // height / width
  strokes: z.array(Stroke).max(5_000),
  latex: Text(20_000).optional(),
  text: Text(20_000).optional(),
});

// looseObject keeps fields from newer clients instead of silently dropping them.
export const DATA_SCHEMAS = {
  doc: z.looseObject({
    title: Text(500),
    filename: Text(300),
    pages: z.number().int().min(0).max(100_000),
    size: z.number().int().min(0).max(MAX_FILE_BYTES),
    authors: Text(2_000).optional(),
    lastPage: Page.optional(),
    tags: Tags.optional(),
  }),
  note: z.looseObject({
    title: Text(300),
    blocks: z.array(z.discriminatedUnion('type', [MdBlock, InkBlock])).max(1_000),
    tags: Tags.optional(),
  }),
  anno: z.looseObject({
    docId: FileId,
    page: Page,
    type: z.enum(['highlight', 'region']),
    rects: z.array(Rect).min(1).max(500),
    quote: Text(20_000),
    color: Text(32),
    comment: Text(50_000).optional(),
    tags: Tags.optional(),
  }),
  ink: z.looseObject({
    docId: FileId,
    page: Page,
    strokes: z.array(Stroke).max(5_000),
    erased: z.array(Id).max(20_000),
  }),
  card: z.looseObject({
    front: Text(20_000),
    back: Text(20_000),
    docId: FileId.optional(),
    annoId: Id.optional(),
    noteId: Id.optional(),
    srs: z.looseObject({ due: Timestamp, state: z.number().int().min(0).max(3) }),
  }),
  task: z.looseObject({
    text: Text(5_000),
    type: z.enum(['todo', 'explain', 'derive', 'question']),
    status: z.enum(['open', 'ready', 'done']),
    docId: FileId.optional(),
    annoId: Id.optional(),
    noteId: Id.optional(),
    explanation: Text(100_000).optional(),
  }),
};

export const KINDS = Object.keys(DATA_SCHEMAS);

const ItemEnvelope = z.strictObject({
  id: Id,
  kind: z.enum(KINDS),
  updatedAt: Timestamp,
  deleted: z.boolean(),
  data: z.unknown(),
});

// Validates one pushed item. Deleted items are tombstones and carry no data.
// Returns { item } or { error }.
export function validateItem(raw) {
  const env = ItemEnvelope.safeParse(raw);
  if (!env.success) return { error: env.error.issues[0] };
  const item = env.data;
  if (item.kind === 'doc' && !FILE_ID.test(item.id)) {
    return { error: { message: 'doc id must be the file SHA-256' } };
  }
  if (item.deleted) return { item: { ...item, data: {} } };

  const data = DATA_SCHEMAS[item.kind].safeParse(item.data);
  if (!data.success) return { error: data.error.issues[0] };
  const bytes = new TextEncoder().encode(JSON.stringify(data.data)).length;
  if (bytes > (MAX_ITEM_BYTES[item.kind] || DEFAULT_MAX_ITEM_BYTES)) {
    return { error: { message: item.kind + ' item too large' } };
  }
  return { item: { ...item, data: data.data } };
}

export function docIdOf(item) {
  if (item.kind === 'doc') return item.id;
  return (item.data && item.data.docId) || null;
}

function chunks(list, size) {
  const out = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

function rowToItem(row) {
  return {
    id: row.id,
    kind: row.kind,
    updatedAt: row.updated_at,
    deleted: row.deleted === 1,
    data: JSON.parse(row.data),
    seq: row.seq,
  };
}

async function storedRows(db, accountId, ids) {
  const rows = new Map();
  for (const chunk of chunks(ids, D1_MAX_PARAMS)) {
    const { results } = await db
      .prepare(
        `SELECT id, kind, data, updated_at, deleted, seq FROM vault_items
         WHERE account_id = ? AND id IN (${chunk.map(() => '?').join(',')})`,
      )
      .bind(accountId, ...chunk)
      .all();
    for (const row of results) rows.set(row.id, row);
  }
  return rows;
}

const UPSERT_COLUMNS = `INSERT INTO vault_items (account_id, id, kind, doc_id, data, updated_at, deleted, seq)
     VALUES (?, ?, ?, ?, ?, ?, ?,
             (SELECT COALESCE(MAX(seq), 0) + 1 FROM vault_items WHERE account_id = ?))
     ON CONFLICT(account_id, id) DO UPDATE SET
       doc_id = excluded.doc_id, data = excluded.data, updated_at = excluded.updated_at,
       deleted = excluded.deleted, seq = excluded.seq`;

// Applies validated items. D1 runs a batch as one transaction and serializes
// writes, so MAX(seq) + 1 is unique and increasing.
//
// Most kinds are last-write-wins: the upsert fires only when the incoming copy
// is newer and of the same kind. Ink is merged instead (stroke union), because
// two devices inking the same page offline must both keep their strokes; the
// merged write is conditional on the row not having changed since it was read,
// and a client whose push lost merges and pushes again.
//
// Returns { stale: [stored items that differ from what the client pushed] }.
export async function pushItems(db, accountId, items) {
  if (items.length === 0) return { stale: [] };
  const lww = db.prepare(UPSERT_COLUMNS + `
     WHERE excluded.updated_at > vault_items.updated_at AND excluded.kind = vault_items.kind`);
  const guarded = db.prepare(UPSERT_COLUMNS + `
     WHERE vault_items.updated_at = ? AND vault_items.kind = 'ink'`);

  const inkIds = items.filter(it => it.kind === 'ink' && !it.deleted).map(it => it.id);
  const before = inkIds.length ? await storedRows(db, accountId, inkIds) : new Map();

  const written = new Map(); // id -> { updatedAt, merged }
  const stmts = items.map(it => {
    const row = before.get(it.id);
    if (it.kind === 'ink' && !it.deleted && row && row.kind === 'ink' && row.deleted === 0) {
      const data = mergeInk(JSON.parse(row.data), it.data);
      const updatedAt = Math.max(it.updatedAt, row.updated_at + 1);
      written.set(it.id, { updatedAt, merged: !sameInk(data, it.data) });
      return guarded.bind(accountId, it.id, it.kind, docIdOf(it), JSON.stringify(data), updatedAt, 0, accountId, row.updated_at);
    }
    written.set(it.id, { updatedAt: it.updatedAt, merged: false });
    return lww.bind(accountId, it.id, it.kind, docIdOf(it), JSON.stringify(it.data), it.updatedAt, it.deleted ? 1 : 0, accountId);
  });
  await db.batch(stmts);

  const after = await storedRows(db, accountId, items.map(it => it.id));
  const stale = [];
  for (const it of items) {
    const row = after.get(it.id);
    const w = written.get(it.id);
    if (row && (row.updated_at !== w.updatedAt || row.kind !== it.kind || w.merged)) stale.push(rowToItem(row));
  }
  return { stale };
}

// Returns items with seq > since, oldest first, bounded by count and bytes.
export async function pullItems(db, accountId, since) {
  const { results } = await db
    .prepare(
      `SELECT id, kind, data, updated_at, deleted, seq FROM vault_items
       WHERE account_id = ? AND seq > ? ORDER BY seq LIMIT ?`,
    )
    .bind(accountId, since, MAX_PULL_ITEMS + 1)
    .all();

  const items = [];
  let bytes = 0;
  for (const row of results.slice(0, MAX_PULL_ITEMS)) {
    bytes += row.data.length;
    if (items.length > 0 && bytes > MAX_PULL_BYTES) break;
    items.push(rowToItem(row));
  }
  const more = items.length < results.length;
  const cursor = items.length ? items[items.length - 1].seq : since;
  return { items, cursor, more };
}

// ── Files (R2) ──

export function fileKey(accountId, fileId) {
  return `pdf/${accountId}/${fileId}`;
}

export async function hasFile(db, accountId, fileId) {
  const row = await db
    .prepare('SELECT size FROM vault_files WHERE account_id = ? AND id = ?')
    .bind(accountId, fileId)
    .first();
  return row ? row.size : null;
}

export async function accountFileBytes(db, accountId) {
  const row = await db
    .prepare('SELECT COALESCE(SUM(size), 0) AS total FROM vault_files WHERE account_id = ?')
    .bind(accountId)
    .first();
  return row.total;
}

export async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export function isPdf(bytes) {
  // "%PDF-" may be preceded by junk; readers accept it within the first 1 KB.
  const head = new TextDecoder('latin1').decode(bytes.subarray(0, 1024));
  return head.includes('%PDF-');
}

export async function recordFile(db, accountId, fileId, size) {
  await db
    .prepare(
      `INSERT INTO vault_files (account_id, id, size, created_at) VALUES (?, ?, ?, ?)
       ON CONFLICT(account_id, id) DO NOTHING`,
    )
    .bind(accountId, fileId, size, Date.now())
    .run();
}

export async function forgetFile(db, accountId, fileId) {
  await db.prepare('DELETE FROM vault_files WHERE account_id = ? AND id = ?').bind(accountId, fileId).run();
}
