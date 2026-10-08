// Why Academy — study vault model
//
// Pure functions shared by the browser store and the tests: item ids,
// conflict resolution for sync, ink merging, and wikilink parsing.
// Item kinds and data shapes must stay in sync with worker/vault.js.
//
// Item: { id, kind, updatedAt, deleted, data }
//   doc   id = SHA-256 of the PDF; data { title, filename, pages, size, lastPage? }
//   note  data { title, blocks: [{ id, type: 'md', text } | { id, type: 'ink', aspect, strokes, latex? }], tags? }
//   anno  data { docId, page, type: 'highlight' | 'region', rects: [[x, y, w, h]], quote, color, comment? }
//   ink   data { docId, page, strokes, erased }  (id derived from docId + page)
//   card  data { front, back, docId?, annoId?, noteId?, srs }
//   task  data { text, type: 'todo' | 'explain' | 'derive' | 'question', status: 'open' | 'ready' | 'done', ... }
//
// Coordinates on a PDF page are normalized to 0..1 of the page width/height.

const ID_ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789';

// 16 random base-36 chars (~82 bits). The time prefix keeps ids roughly sortable.
export function newId() {
  const bytes = new Uint8Array(12);
  globalThis.crypto.getRandomValues(bytes);
  let out = Date.now().toString(36);
  for (const b of bytes) out += ID_ALPHABET[b % ID_ALPHABET.length];
  return out;
}

// PDFs are identified by the SHA-256 of their bytes (client and worker).
export async function sha256Hex(buffer) {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// One ink item per (document, page) so a page's strokes load together.
export function inkId(docId, page) {
  return 'ink-' + docId.slice(0, 24) + '-' + page;
}

// Next edit time for an item: wall clock, but strictly after the previous
// edit so last-write-wins never ties with our own older copy.
export function nextUpdatedAt(prev, now) {
  return Math.max(now, (prev || 0) + 1);
}

// ── Ink ──

// Strokes are append-only and identified by id; erasing records the id.
// Merging two copies is a union, so pen work on two devices never collides.
export function mergeInk(a, b) {
  const erased = new Set([...(a.erased || []), ...(b.erased || [])]);
  const byId = new Map();
  for (const s of [...(a.strokes || []), ...(b.strokes || [])]) {
    if (!erased.has(s.id) && !byId.has(s.id)) byId.set(s.id, s);
  }
  return { ...a, ...b, strokes: [...byId.values()], erased: [...erased] };
}

export function sameInk(a, b) {
  const ids = d => (d.strokes || []).map(st => st.id).sort().join(',') + '|' + [...new Set(d.erased || [])].sort().join(',');
  return ids(a) === ids(b);
}

// ── Sync conflict resolution ──

function sameData(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// Decides what to keep when the server sends `remote` and we hold `local`.
// local.dirty means local edits the server has not accepted yet.
// Returns { item, dirty, extra } where extra are new items to create.
export function resolveIncoming(local, remote, now) {
  if (!local || !local.dirty) return { item: remote, dirty: false, extra: [] };

  if (local.kind === 'ink' && remote.kind === 'ink' && !local.deleted && !remote.deleted) {
    const merged = mergeInk(local.data, remote.data);
    // Already contains everything we have (e.g. the server merged our push).
    if (sameInk(merged, remote.data)) return { item: remote, dirty: false, extra: [] };
    return {
      item: {
        ...remote,
        data: merged,
        updatedAt: nextUpdatedAt(Math.max(local.updatedAt, remote.updatedAt), now),
      },
      dirty: true,
      extra: [],
    };
  }

  if (local.updatedAt > remote.updatedAt) return { item: local, dirty: true, extra: [] };

  // The server copy is newer. Losing typed note text silently is the worst
  // outcome here, so keep the local version as a separate note.
  const extra = [];
  if (local.kind === 'note' && !local.deleted && !remote.deleted && !sameData(local.data, remote.data)) {
    extra.push({
      id: newId(),
      kind: 'note',
      updatedAt: now,
      deleted: false,
      data: { ...local.data, title: (local.data.title || 'Untitled') + ' (conflict copy)' },
    });
  }
  return { item: remote, dirty: false, extra };
}

// ── Links ──

// [[Title]], [[Title|label]] link a note or document by title.
// [[@annoId]], [[@annoId|label]] link a passage or region in a PDF.
export const WIKILINK = /\[\[([^\[\]|]+?)(?:\|([^\[\]]*))?\]\]/g;

export function parseLinks(text) {
  const out = [];
  for (const m of String(text || '').matchAll(WIKILINK)) {
    const target = m[1].trim();
    const label = m[2] !== undefined ? m[2].trim() : null;
    if (target.startsWith('@')) out.push({ type: 'anno', id: target.slice(1), label, index: m.index, raw: m[0] });
    else out.push({ type: 'title', title: target, label, index: m.index, raw: m[0] });
  }
  return out;
}

export function noteText(note) {
  return (note.data.blocks || [])
    .map(b => (b.type === 'md' ? b.text : [b.latex, b.text].filter(Boolean).join('\n')))
    .join('\n');
}

export function normTitle(title) {
  return String(title || '').trim().toLowerCase();
}

// Builds the link graph: for every note, what it points at, and for every
// target (note, doc or anno id) which notes point at it.
export function buildLinkIndex(items) {
  const notesByTitle = new Map();
  const docsByTitle = new Map();
  for (const it of items) {
    if (it.deleted) continue;
    if (it.kind === 'note') notesByTitle.set(normTitle(it.data.title), it.id);
    if (it.kind === 'doc') docsByTitle.set(normTitle(it.data.title), it.id);
  }

  const outgoing = new Map(); // noteId -> [{ kind, id, title }]
  const backlinks = new Map(); // targetId -> Set(noteId)
  const unresolved = new Map(); // normalized title -> Set(noteId)
  const add = (target, noteId) => {
    if (!backlinks.has(target)) backlinks.set(target, new Set());
    backlinks.get(target).add(noteId);
  };

  for (const it of items) {
    if (it.deleted || it.kind !== 'note') continue;
    const links = [];
    for (const l of parseLinks(noteText(it))) {
      if (l.type === 'anno') {
        links.push({ kind: 'anno', id: l.id });
        add(l.id, it.id);
        continue;
      }
      const key = normTitle(l.title);
      const noteId = notesByTitle.get(key);
      const docId = noteId ? null : docsByTitle.get(key);
      if (noteId || docId) {
        links.push({ kind: noteId ? 'note' : 'doc', id: noteId || docId, title: l.title });
        add(noteId || docId, it.id);
      } else {
        links.push({ kind: 'missing', title: l.title });
        if (!unresolved.has(key)) unresolved.set(key, new Set());
        unresolved.get(key).add(it.id);
      }
    }
    outgoing.set(it.id, links);
  }
  return { notesByTitle, docsByTitle, outgoing, backlinks, unresolved };
}

// Notes that reference a document, directly or through one of its annotations.
export function notesForDoc(index, items, docId) {
  const ids = new Set(index.backlinks.get(docId) || []);
  for (const it of items) {
    if (it.kind === 'anno' && !it.deleted && it.data.docId === docId) {
      for (const n of index.backlinks.get(it.id) || []) ids.add(n);
    }
  }
  return ids;
}

// ── PDF selection geometry ──

// Merges client rects of a text selection into one rect per line, in
// page-normalized coordinates. rects: [{ left, top, width, height }] relative
// to the page box; pageW/pageH: page box size in the same units.
export function selectionRects(rects, pageW, pageH) {
  const lines = [];
  const sorted = rects
    .filter(r => r.width > 0.5 && r.height > 0.5)
    .sort((a, b) => a.top - b.top || a.left - b.left);
  for (const r of sorted) {
    const mid = r.top + r.height / 2;
    const line = lines.find(l => mid > l.top && mid < l.top + l.height);
    if (line) {
      const right = Math.max(line.left + line.width, r.left + r.width);
      const bottom = Math.max(line.top + line.height, r.top + r.height);
      line.left = Math.min(line.left, r.left);
      line.top = Math.min(line.top, r.top);
      line.width = right - line.left;
      line.height = bottom - line.top;
    } else {
      lines.push({ left: r.left, top: r.top, width: r.width, height: r.height });
    }
  }
  const round = v => Math.round(v * 10000) / 10000;
  return lines.map(l => [round(l.left / pageW), round(l.top / pageH), round(l.width / pageW), round(l.height / pageH)]);
}

// ── Study queue ──

export function isDue(card, now) {
  return !card.deleted && card.data.srs && card.data.srs.due <= now;
}

// What needs attention, most actionable first.
export function studyQueue(items, now) {
  const live = items.filter(it => !it.deleted);
  return {
    dueCards: live.filter(it => it.kind === 'card' && isDue(it, now)).sort((a, b) => a.data.srs.due - b.data.srs.due),
    toReview: live.filter(it => it.kind === 'task' && it.data.status === 'ready'),
    open: live.filter(it => it.kind === 'task' && it.data.status === 'open'),
  };
}
