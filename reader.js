// Why Academy — Reader
//
// PDF reader + linked notes + study queue, built on the vault store
// (lib/vault/store.js). Everything the reader marks becomes an item:
//   anno  a highlighted passage or a region of a page
//   ink   Pencil strokes on a page
//   card  a flashcard (FSRS schedule), often from an equation region
//   task  a todo, an "explain this" follow-up, a derivation, or a question
//         for journal club
//   note  Markdown + ink blocks, linked with [[Title]] and [[@anno]]
// Routes: #doc=<id>[&p=<page>], #note=<id>, #study

import { VaultStore } from './lib/vault/store.js';
import {
  newId,
  inkId,
  selectionRects,
  buildLinkIndex,
  notesForDoc,
  noteText,
  normTitle,
  studyQueue,
  WIKILINK,
} from './lib/vault/model.js';
import { PdfView, readPdfInfo } from './lib/vault/pdf-view.js';
import { NoteEditor, noteBackup } from './lib/vault/notes.js';
import { renderMarkdown, escapeHtml } from './lib/vault/markdown.js';
import { INK_COLORS, HIGHLIGHT_COLORS } from './lib/vault/ink.js';
import { explainPassage, equationToLatex, draftCard } from './lib/vault/ai.js';
import { newSrs, previewReview, GRADES } from './lib/vault/srs.js';
import { History } from './lib/vault/history.js';

const $ = sel => document.querySelector(sel);
const C = window.WhyCommon;

// Stroke widths relative to the page width, per size.
const PEN_WIDTHS = {
  fine: { pen: 0.0018, highlighter: 0.011 },
  medium: { pen: 0.0028, highlighter: 0.016 },
  thick: { pen: 0.0046, highlighter: 0.024 },
};
const PEN_SIZES = ['fine', 'medium', 'thick'];
const TASK_LABELS = { todo: 'Follow-up', explain: 'Explain', derive: 'Derive', question: 'Question' };
const COLOR_NAMES = {
  '#1f2937': 'Black', '#2563eb': 'Blue', '#dc2626': 'Red', '#059669': 'Green',
  '#fde047': 'Yellow', '#86efac': 'Green', '#f9a8d4': 'Pink', '#93c5fd': 'Blue',
};
const NARROW = matchMedia('(max-width: 900px)');
const MAX_PDF_BYTES = 64 * 1024 * 1024; // worker/vault.js MAX_FILE_BYTES

const store = new VaultStore();
const state = {
  view: 'empty',
  docId: null,
  noteId: null,
  pdf: null,
  tool: {
    tool: matchMedia('(pointer: coarse)').matches ? 'pen' : 'select',
    color: INK_COLORS[0],
    hlColor: HIGHLIGHT_COLORS[0],
    size: PEN_SIZES.includes(localStorage.getItem('reader.penSize')) ? localStorage.getItem('reader.penSize') : 'medium',
  },
  links: null,
  // On narrow screens the panel covers the page, so it never reopens by itself.
  panelOpen: localStorage.getItem('reader.panel') === '1' && !NARROW.matches,
  notebookOpen: localStorage.getItem('reader.notebook') === '1',
  target: null, // current action target: { kind: 'selection'|'region'|'anno', ... }
  review: null, // { queue: [ids], index, revealed, done }
  panelFilter: 'all', // marks panel: 'all' | 'unclear'
  panelMode: localStorage.getItem('reader.panelMode') === 'contents' ? 'contents' : 'marks', // doc panel
};

// Notes made with "New note" stay here until their first edit, so an
// abandoned new note never reaches the vault.
const pendingNotes = new Map();

// A note without a title is shown by its first line of text.
function noteTitle(n) {
  if (n.data.title && n.data.title.trim()) return n.data.title;
  const md = (n.data.blocks || []).find(b => b.type === 'md' && b.text.trim());
  if (!md) return 'Untitled';
  return snippet(md.text.trim().split('\n')[0].replace(/^[#>*\-\s]+|\[\[|\]\]/g, ''), 50) || 'Untitled';
}

function snippet(s, n = 120) {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  if (s.length <= n) return s;
  const cut = s.slice(0, n - 1);
  const space = cut.lastIndexOf(' ');
  return (space > n * 0.6 ? cut.slice(0, space) : cut) + '…';
}

// ── Recently deleted ──
//
// Removing a paper moves it to the trash (doc.data.trashedAt) for 30 days:
// hidden everywhere, restorable, then purged with its marks, ink and file.

const TRASH_DAYS = 30;
const DAY_MS = 24 * 60 * 60 * 1000;

function isTrashed(d) {
  return !!(d && d.kind === 'doc' && d.data.trashedAt);
}

// A paper that is in the library (not in the trash).
function liveDoc(id) {
  const d = store.get(id);
  return d && d.kind === 'doc' && !d.data.trashedAt ? d : null;
}

// The vault as the app shows it: trashed papers, and their marks and ink,
// are left out.
function visibleItems() {
  const trashed = new Set(store.all('doc').filter(isTrashed).map(d => d.id));
  if (!trashed.size) return store.all();
  return store.all().filter(it => !(it.kind === 'doc' && trashed.has(it.id))
    && !((it.kind === 'anno' || it.kind === 'ink') && trashed.has(it.data.docId)));
}

// Deletes a paper for good: marks, ink, the file and its search text.
// Cards, tasks and notes are study material and stay.
async function purgePaper(docId) {
  for (const it of [...store.forDoc(docId, 'anno'), ...store.forDoc(docId, 'ink')]) await store.remove(it.id);
  await store.remove(docId);
  await store.removeFile(docId);
  if (textIndex) textIndex.delete(docId);
  localStorage.removeItem('reader.page.' + docId);
}

async function purgeExpiredTrash() {
  const cutoff = Date.now() - TRASH_DAYS * DAY_MS;
  for (const d of store.all('doc').filter(d => isTrashed(d) && d.data.trashedAt < cutoff)) {
    try {
      await purgePaper(d.id);
    } catch (e) {
      console.error('Emptying the trash failed for', d.id, e);
    }
  }
}

// "in 5 min", "in 3 h", "tomorrow", "in 12 days".
function relativeTime(t) {
  const min = Math.round((t - Date.now()) / 60000);
  if (min < 1) return 'now';
  if (min < 60) return `in ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `in ${h} h`;
  const d = Math.round(h / 24);
  return d === 1 ? 'tomorrow' : `in ${d} days`;
}

// ── Toast ──

let toastTimer = null;
function toast(msg, isError) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.toggle('error', !!isError);
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), isError ? 7000 : 3500);
}

function reportError(context, e) {
  console.error(context, e);
  toast(context + ': ' + (e && e.message ? e.message : e), true);
}

// ── Tools ──

function getTool() {
  const t = state.tool;
  const isHl = t.tool === 'highlighter';
  return { tool: t.tool, color: isHl ? t.hlColor : t.color, width: PEN_WIDTHS[t.size][isHl ? 'highlighter' : 'pen'] };
}

// Notebook ink pads always take the Pencil: Select and Region are reading
// tools and mean nothing on a pad.
function getInkTool() {
  const t = getTool();
  if (t.tool === 'select' || t.tool === 'region') return { tool: 'pen', color: state.tool.color, width: PEN_WIDTHS[state.tool.size].pen };
  return t;
}

// ── Undo ──

const undoHistory = new History();

function removeStrokes(d, ids) {
  const gone = new Set(ids);
  d.strokes = d.strokes.filter(s => !gone.has(s.id));
  d.erased.push(...ids);
}

// Ink merges by stroke id and erasing is permanent per id, so redoing a
// stroke (or undoing an erase) re-adds it under a fresh id.
function inkAdded(docId, page, stroke) {
  let current = stroke;
  saveInk(docId, page, d => d.strokes.push(stroke));
  undoHistory.push({
    label: 'Pen stroke',
    undo: () => saveInk(docId, page, d => removeStrokes(d, [current.id])),
    redo: () => {
      current = { ...current, id: newId() };
      return saveInk(docId, page, d => d.strokes.push(current));
    },
  });
}

function inkErased(docId, page, ids, label = 'Erase') {
  let removed = [];
  const done = saveInk(docId, page, d => {
    const gone = new Set(ids);
    removed = d.strokes.filter(s => gone.has(s.id));
    removeStrokes(d, ids);
  });
  undoHistory.push({
    label,
    undo: () => {
      removed = removed.map(s => ({ ...s, id: newId() }));
      return saveInk(docId, page, d => d.strokes.push(...removed));
    },
    redo: () => saveInk(docId, page, d => removeStrokes(d, removed.map(s => s.id))),
  });
  return done;
}

// Vault writes that can be undone.
async function trackedPut(kind, id, data) {
  const before = store.get(id);
  const prev = before ? structuredClone(before.data) : null;
  const snapshot = structuredClone(data);
  const item = await store.put(kind, id, data);
  undoHistory.push({
    label: kind,
    undo: () => (prev ? store.put(kind, id, prev) : store.remove(id)),
    redo: () => store.put(kind, id, structuredClone(snapshot)),
  });
  return item;
}

function trackedCreate(kind, data) {
  return trackedPut(kind, newId(), data);
}

function trackedUpdate(id, patch) {
  const it = store.get(id);
  return trackedPut(it.kind, id, { ...it.data, ...patch });
}

async function trackedRemove(id) {
  const it = store.get(id);
  if (!it) return;
  const prev = structuredClone(it.data);
  await store.remove(id);
  undoHistory.push({ label: 'Delete', undo: () => store.put(it.kind, id, prev), redo: () => store.remove(id) });
}

async function undo() {
  try {
    const e = await undoHistory.undo();
    if (e) toast('Undid ' + e.label.toLowerCase());
  } catch (e) {
    reportError('Undo failed', e);
  }
}

async function redo() {
  try {
    const e = await undoHistory.redo();
    if (e) toast('Redid ' + e.label.toLowerCase());
  } catch (e) {
    reportError('Redo failed', e);
  }
}

function renderUndoButtons() {
  document.querySelectorAll('[data-history="undo"]').forEach(b => { b.disabled = !undoHistory.canUndo; });
  document.querySelectorAll('[data-history="redo"]').forEach(b => { b.disabled = !undoHistory.canRedo; });
}
undoHistory.addEventListener('change', renderUndoButtons);

// Highlights the eraser passed over. Marks that carry work (cards, tasks,
// comments, an understanding state) are left alone: deleting those is an
// explicit action on the mark.
const erasingMarks = new Set();
let eraseWarned = 0;
function eraseMark(a) {
  if (erasingMarks.has(a.id) || !store.get(a.id)) return;
  const linked = (itemsByAnno().get(a.id) || []).length;
  if (linked || a.data.comment || a.data.status) {
    if (Date.now() - eraseWarned > 4000) {
      eraseWarned = Date.now();
      const why = linked ? 'has cards or tasks' : a.data.comment ? 'has a comment' : 'is marked ' + (a.data.status === 'unclear' ? 'not clear yet' : 'understood');
      toast(`This highlight ${why}, so the eraser keeps it. Tap it and choose Delete.`);
    }
    return;
  }
  erasingMarks.add(a.id);
  trackedRemove(a.id).catch(e => reportError('Erasing the highlight failed', e)).finally(() => erasingMarks.delete(a.id));
}

function setTool(tool) {
  state.tool.tool = tool;
  document.querySelectorAll('.tool[data-tool]').forEach(b => {
    b.classList.toggle('active', b.dataset.tool === tool);
    b.setAttribute('aria-pressed', String(b.dataset.tool === tool));
  });
  document.body.dataset.tool = tool;
  $('#clear-page').classList.toggle('hidden', tool !== 'eraser');
  renderColors();
}

// One button shows the current color; tapping it opens the choices.
function renderColors() {
  const isHl = state.tool.tool === 'highlighter';
  const colors = isHl ? HIGHLIGHT_COLORS : INK_COLORS;
  const current = isHl ? state.tool.hlColor : state.tool.color;
  for (const group of [$('#color-group'), $('#note-color-group')]) {
    group.innerHTML = '';
    const btn = document.createElement('button');
    btn.className = 'swatch active';
    btn.style.setProperty('--swatch', current);
    btn.title = `${isHl ? 'Highlighter' : 'Pen'}: ${COLOR_NAMES[current].toLowerCase()}, ${state.tool.size} (tap for colors and sizes)`;
    btn.dataset.size = state.tool.size;
    btn.setAttribute('aria-label', btn.title);
    btn.setAttribute('aria-expanded', 'false');
    const menu = document.createElement('div');
    menu.className = 'swatch-menu hidden';
    for (const c of colors) {
      const b = document.createElement('button');
      b.className = 'swatch' + (c === current ? ' active' : '');
      b.style.setProperty('--swatch', c);
      b.title = COLOR_NAMES[c];
      b.setAttribute('aria-label', COLOR_NAMES[c]);
      b.addEventListener('click', () => {
        if (isHl) state.tool.hlColor = c;
        else state.tool.color = c;
        renderColors();
      });
      menu.appendChild(b);
    }
    const sizes = document.createElement('div');
    sizes.className = 'size-row';
    for (const size of PEN_SIZES) {
      const b = document.createElement('button');
      b.className = 'size-dot size-' + size + (size === state.tool.size ? ' active' : '');
      b.title = size[0].toUpperCase() + size.slice(1) + ' line';
      b.setAttribute('aria-label', b.title);
      b.setAttribute('aria-pressed', String(size === state.tool.size));
      b.addEventListener('click', e => {
        e.stopPropagation();
        state.tool.size = size;
        try {
          localStorage.setItem('reader.penSize', size);
        } catch (err) {
          console.warn('Could not remember the pen size', err);
        }
        renderColors();
      });
      sizes.appendChild(b);
    }
    menu.appendChild(sizes);
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const open = menu.classList.toggle('hidden') === false;
      btn.setAttribute('aria-expanded', String(open));
    });
    group.append(btn, menu);
  }
}

// ── Routing ──

function parseHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.has('doc')) return { view: 'doc', id: h.get('doc'), page: +h.get('p') || null, anno: h.get('a'), q: h.get('q') };
  if (h.has('note')) return { view: 'note', id: h.get('note') };
  if (h.has('brief')) return { view: 'brief', id: h.get('brief') };
  if (h.has('study')) return { view: 'study', task: h.get('t') };
  return { view: 'empty' };
}

function navigate(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

async function route() {
  const r = parseHash();
  hideActions();
  // A dialog belongs to the view it was opened in.
  const dlg = $('#dialog');
  if (dlg.open) dlg.close('cancel');
  const exists = id => (r.view === 'note' ? store.get(id) || pendingNotes.has(id) || noteBackup(id) : liveDoc(id));
  if ((r.view === 'doc' || r.view === 'note' || r.view === 'brief') && !exists(r.id)) {
    toast(r.view === 'note' ? 'That note was empty or has been deleted'
      : isTrashed(store.get(r.id)) ? 'That paper is in Recently deleted; restore it from the library'
      : 'That paper is not in your library', r.view !== 'note');
    const last = localStorage.getItem('reader.last');
    const lr = last && new URLSearchParams(last.slice(1));
    const lastId = lr && (lr.get('doc') || lr.get('note'));
    history.replaceState(null, '', lastId && store.get(lastId) ? last : location.pathname);
    return route();
  }
  // In portrait the panel covers the page, so it does not follow you around.
  if (NARROW.matches && state.panelOpen) state.panelOpen = false;
  // On narrow screens the library covers the content: any navigation out of
  // it (even to the paper already open) puts it away, before slow loading.
  if (NARROW.matches && r.view !== 'empty') setSidebar(false);
  if (r.view === 'doc' && liveDoc(r.id)) {
    await openDoc(r.id, r.page, r.anno, r.q);
  } else if (r.view === 'note' && exists(r.id)) {
    openNoteView(r.id);
  } else if (r.view === 'brief' && liveDoc(r.id)) {
    showView('brief');
    renderBrief(r.id);
  } else if (r.view === 'study') {
    showView('study');
    if (state.review && state.review.done) state.review = null;
    renderStudy();
    if (r.task) focusStudyItem(r.task);
  } else {
    showView('empty');
  }
  // Only saved items: an unsaved new note is no place to resume.
  if ((r.view === 'doc' || r.view === 'note') && store.get(r.id)) {
    try {
      localStorage.setItem('reader.last', location.hash);
    } catch (e) {
      console.warn('Could not remember the last page', e);
    }
  }
  renderSidebar();
}

function showView(view) {
  if (state.view === 'note' && view !== 'note') closeNoteView();
  if (state.view === 'doc' && view !== 'doc') closeDoc();
  state.view = view;
  for (const v of ['empty', 'doc', 'note', 'study', 'brief']) $('#view-' + v).classList.toggle('hidden', v !== view);
  $('#panel').classList.toggle('hidden', !(state.panelOpen && (view === 'doc' || view === 'note')));
  const titles = { empty: '', study: 'Study' };
  if (view in titles) $('#view-title').textContent = titles[view];
  // The library is the way forward from the empty view; elsewhere it covers
  // the content on narrow screens.
  if (view === 'empty') setSidebar(true);
  else if (NARROW.matches) setSidebar(false);
}

// ── Sidebar ──

function setSidebar(open) {
  document.body.classList.toggle('sidebar-closed', !open);
  $('#sidebar-toggle').setAttribute('aria-expanded', String(open));
}

function renderSidebar() {
  const docs = store.all('doc').filter(d => !isTrashed(d)).sort((a, b) => b.updatedAt - a.updatedAt);
  renderTrash(store.all('doc').filter(isTrashed));
  const notes = store.all('note').sort((a, b) => b.updatedAt - a.updatedAt);

  const markCounts = new Map();
  for (const a of store.all('anno')) markCounts.set(a.data.docId, (markCounts.get(a.data.docId) || 0) + 1);

  const docList = $('#doc-list');
  docList.innerHTML = '';
  if (!docs.length) docList.innerHTML = '<li class="side-empty">No papers yet</li>';
  for (const d of docs) {
    const li = document.createElement('li');
    const marks = markCounts.get(d.id) || 0;
    li.className = 'side-row';
    li.innerHTML = `<a href="#doc=${d.id}" class="side-item${state.docId === d.id ? ' active' : ''}">
      <span class="side-item-title"></span><span class="side-item-meta">${d.data.pages} pp${marks ? ' &middot; ' + marks + ' marks' : ''}</span></a>
      <button class="icon-btn side-more" aria-label="Rename or remove paper" title="Rename or remove">&#8943;</button>`;
    li.querySelector('.side-item-title').textContent = d.data.title;
    li.querySelector('.side-more').addEventListener('click', () => paperDialog(d.id));
    docList.appendChild(li);
  }

  const noteList = $('#note-list');
  noteList.innerHTML = '';
  if (!notes.length) noteList.innerHTML = '<li class="side-empty">No notes yet</li>';
  for (const n of notes) {
    const li = document.createElement('li');
    li.innerHTML = `<a href="#note=${n.id}" class="side-item${state.noteId === n.id && state.view === 'note' ? ' active' : ''}"><span class="side-item-title"></span></a>`;
    li.querySelector('.side-item-title').textContent = noteTitle(n);
    noteList.appendChild(li);
  }

  const q = studyQueue(store.all(), Date.now());
  const parts = [];
  if (q.dueCards.length) parts.push(`<span class="count due">${q.dueCards.length} due</span>`);
  if (q.toReview.length) parts.push(`<span class="count ready">${q.toReview.length} to read</span>`);
  if (q.open.length) parts.push(`<span class="count open">${q.open.length} open</span>`);
  $('#study-counts').innerHTML = parts.join('') || '<span class="count">all clear</span>';
  $('#open-study').classList.toggle('active', state.view === 'study');
}

// ── Search ──

let lastQuery = '';

function search(q) {
  const box = $('#search-results');
  q = q.trim().toLowerCase();
  if (!q) {
    box.classList.add('hidden');
    return;
  }
  const hits = [];
  for (const it of visibleItems()) {
    let text = '', label = '', href = '';
    if (it.kind === 'doc') { text = it.data.title + ' ' + (it.data.authors || ''); label = 'Paper'; href = '#doc=' + it.id; }
    else if (it.kind === 'note') { text = it.data.title + '\n' + noteText(it); label = 'Note'; href = '#note=' + it.id; }
    else if (it.kind === 'anno') { text = it.data.quote + ' ' + (it.data.comment || ''); label = 'p. ' + it.data.page; href = `#doc=${it.data.docId}&a=${it.id}`; }
    else if (it.kind === 'card') { text = it.data.front + ' ' + it.data.back; label = 'Card'; href = markHref(it) || '#study'; }
    else if (it.kind === 'task') {
      text = it.data.text + ' ' + (it.data.explanation || '');
      label = TASK_LABELS[it.data.type];
      href = it.data.type === 'explain' || !markHref(it) ? '#study&t=' + it.id : markHref(it);
    }
    else continue;
    const at = text.toLowerCase().indexOf(q);
    if (at < 0) continue;
    text = text.replace(/[#*_>`]+/g, '');
    const at2 = text.toLowerCase().indexOf(q);
    let from = Math.max(0, (at2 < 0 ? at : at2) - 30);
    while (from > 0 && /\S/.test(text[from - 1])) from--;
    const title = it.kind === 'doc' ? it.data.title : it.kind === 'note' ? noteTitle(it) : (from > 0 ? '\u2026' : '') + snippet(text.slice(from), 90);
    hits.push({ label, href, title, rank: it.kind === 'doc' || it.kind === 'note' ? 0 : 1 });
  }
  hits.sort((a, b) => a.rank - b.rank);
  box.innerHTML = hits.length ? '' : '<div class="side-empty no-matches">No matches</div>';
  appendSearchHits(box, hits.slice(0, 40));
  box.classList.remove('hidden');
  searchPaperText(q, box);
}

function appendSearchHits(box, hits) {
  for (const h of hits) {
    const a = document.createElement('a');
    a.className = 'search-hit';
    a.href = h.href;
    a.innerHTML = '<span class="search-kind"></span><span class="search-title"></span>';
    a.querySelector('.search-kind').textContent = h.label;
    a.querySelector('.search-title').textContent = h.title;
    box.appendChild(a);
  }
}

// ── Full-text search of papers ──

// Page texts of papers, extracted once per device when a paper is opened.
let textIndex = null; // Map docId -> [page text]

async function loadTextIndex() {
  if (!textIndex) textIndex = new Map((await store.allText()).map(r => [r.id, r.pages]));
  return textIndex;
}

// Extracts and stores a paper's text in the background after it opens.
async function indexPaperText(docId, view) {
  const index = await loadTextIndex();
  if (index.has(docId)) return;
  const pages = [];
  for (let n = 1; n <= view.numPages; n++) {
    if (state.pdf !== view) return; // paper closed; next open retries
    pages.push(await view.pageText(n));
  }
  await store.putText(docId, pages);
  index.set(docId, pages);
}

// Appends "p. N" hits from the text of every indexed paper.
async function searchPaperText(q, box) {
  const query = q;
  let index;
  try {
    index = await loadTextIndex();
  } catch (e) {
    console.error('Search index unavailable', e);
    return;
  }
  if (query !== lastQuery.trim().toLowerCase()) return;
  const hits = [];
  for (const [docId, pages] of index) {
    const doc = liveDoc(docId);
    if (!doc) continue;
    let perDoc = 0;
    pages.forEach((text, i) => {
      if (perDoc >= 8) return;
      const at = text.toLowerCase().indexOf(query);
      if (at < 0) return;
      perDoc++;
      hits.push({
        label: 'p. ' + (i + 1),
        href: `#doc=${docId}&p=${i + 1}&q=${encodeURIComponent(query)}`,
        title: snippet(doc.data.title, 40) + ': ' + contextSnippet(text, at, query.length),
      });
    });
  }
  if (!hits.length) return;
  box.querySelector('.no-matches')?.remove();
  const head = document.createElement('div');
  head.className = 'search-section';
  head.textContent = 'In the papers';
  box.appendChild(head);
  appendSearchHits(box, hits.slice(0, 40));
}

// [before, match, after] with the original spacing, cut at word boundaries.
function splitAround(text, at, len, radius) {
  let from = Math.max(0, at - radius);
  let to = Math.min(text.length, at + len + radius);
  while (from > 0 && /\S/.test(text[from - 1])) from--;
  while (to < text.length && /\S/.test(text[to])) to++;
  const clean = s => s.replace(/\s+/g, ' ');
  return [
    (from > 0 ? '\u2026' : '') + clean(text.slice(from, at)).replace(/^ /, ''),
    text.slice(at, at + len),
    clean(text.slice(at + len, to)).replace(/ $/, '') + (to < text.length ? '\u2026' : ''),
  ];
}

// "...words around the match..." cut at word boundaries.
function contextSnippet(text, at, len, radius = 50) {
  let from = Math.max(0, at - radius);
  let to = Math.min(text.length, at + len + radius);
  while (from > 0 && /\S/.test(text[from - 1])) from--;
  while (to < text.length && /\S/.test(text[to])) to++;
  return (from > 0 ? '\u2026' : '') + text.slice(from, to).replace(/\s+/g, ' ').trim() + (to < text.length ? '\u2026' : '');
}

// Link to the passage a card or task came from, if it still exists.
function markHref(it) {
  const a = it.data.annoId && store.get(it.data.annoId);
  return a ? `#doc=${a.data.docId}&a=${a.id}` : null;
}

// ── Links between notes, papers and passages ──

function linkIndex() {
  if (!state.links) state.links = buildLinkIndex(visibleItems());
  return state.links;
}

function resolveLink(link) {
  if (link.type === 'anno') {
    const a = store.get(link.id);
    if (!a) return { label: link.label || 'missing passage', cls: 'wl-missing', attrs: { kind: 'missing' } };
    const doc = store.get(a.data.docId);
    const label = link.label || (a.data.type === 'region' ? `${doc ? doc.data.title + ', ' : ''}p. ${a.data.page} region` : '“' + snippet(a.data.quote, 60) + '”');
    return { label, cls: 'wl-anno', attrs: { kind: 'anno', id: a.id } };
  }
  const idx = linkIndex();
  const key = normTitle(link.title);
  const label = link.label || link.title;
  if (idx.notesByTitle.has(key)) return { label, cls: 'wl-note', attrs: { kind: 'note', id: idx.notesByTitle.get(key) } };
  if (idx.docsByTitle.has(key)) return { label, cls: 'wl-doc', attrs: { kind: 'doc', id: idx.docsByTitle.get(key) } };
  return { label, cls: 'wl-missing', attrs: { kind: 'new', title: link.title } };
}

// Following a link to a note that does not exist yet creates it (as in Obsidian).
async function openLink(el) {
  const { kind, id, title } = el.dataset;
  if (kind === 'note') navigate('#note=' + id);
  else if (kind === 'doc') navigate('#doc=' + id);
  else if (kind === 'anno') {
    const a = store.get(id);
    navigate(`#doc=${a.data.docId}&a=${id}`);
  } else if (kind === 'new') {
    const note = await store.create('note', { title, blocks: [{ id: newId(), type: 'md', text: '' }] });
    navigate('#note=' + note.id);
  }
}

function titles() {
  return [
    ...store.all('note').filter(n => n.data.title && n.data.title.trim()).map(n => ({ title: n.data.title, kind: 'note' })),
    ...store.all('doc').filter(d => !isTrashed(d)).map(d => ({ title: d.data.title, kind: 'paper' })),
  ];
}

function renderNoteLinks(box, noteId) {
  const idx = linkIndex();
  const back = [...(idx.backlinks.get(noteId) || [])].map(id => store.get(id)).filter(Boolean);
  box.innerHTML = back.length ? '<h4>Linked from</h4>' : '';
  for (const n of back) {
    const a = document.createElement('a');
    a.href = '#note=' + n.id;
    a.className = 'chip';
    a.textContent = noteTitle(n);
    box.appendChild(a);
  }
}

// A note's title changed: links to the old title follow it.
async function noteRenamed(oldTitle, newTitle) {
  if (!oldTitle.trim()) return;
  try {
    const n = await retitleLinks(oldTitle, newTitle);
    if (n) toast(`Updated links in ${n} note${n === 1 ? '' : 's'}`);
  } catch (e) {
    reportError('Updating links to the renamed note failed', e);
  }
}

const editorApp = { store, getTool: getInkTool, resolveLink, openLink, titles, toast, renderNoteLinks, history: undoHistory, noteRenamed };
const mainEditor = new NoteEditor($('#note-root'), editorApp);
const sideEditor = new NoteEditor($('#doc-notebook'), editorApp);

// ── Notes view ──

function openNoteView(noteId) {
  if (state.view === 'note' && state.noteId !== noteId) closeNoteView();
  showView('note');
  state.noteId = noteId;
  mainEditor.open(noteId, pendingNotes.get(noteId));
  $('#view-title').textContent = mainEditor.draft.title || 'Untitled';
  renderPanel();
}

function closeNoteView() {
  mainEditor.close();
  // A new note that was never edited was never saved; forget it.
  if (state.noteId && !store.get(state.noteId)) pendingNotes.delete(state.noteId);
}

function newNote() {
  const id = newId();
  pendingNotes.set(id, { title: '', blocks: [{ id: newId(), type: 'md', text: '' }] });
  navigate('#note=' + id);
  setTimeout(() => $('#note-root .note-title')?.focus(), 50);
}

// ── Documents ──

async function importFiles(files) {
  for (const file of files) {
    if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
      toast(file.name + ' is not a PDF', true);
      continue;
    }
    try {
      if (file.size > MAX_PDF_BYTES) {
        toast(`${file.name} is ${Math.round(file.size / 1048576)} MB; the limit is ${MAX_PDF_BYTES / 1048576} MB`, true);
        continue;
      }
      const bytes = new Uint8Array(await file.arrayBuffer());
      const id = await store.addFile(bytes);
      if (isTrashed(store.get(id))) {
        // Adding a paper that is in the trash brings it back, marks and all.
        await trackedUpdate(id, { trashedAt: undefined });
        toast('Restored from Recently deleted, with its marks');
      } else if (!store.get(id)) {
        const meta = await readPdfInfo(bytes);
        const fallback = file.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' ');
        const title = meta.title && meta.title.length > 3 && !/^untitled|\.(docx?|tex|dvi)$/i.test(meta.title) ? meta.title : fallback;
        await store.put('doc', id, {
          title: title.slice(0, 500),
          filename: file.name.slice(0, 300),
          pages: meta.pages,
          size: bytes.length,
          authors: meta.authors ? meta.authors.slice(0, 2000) : undefined,
        });
      }
      navigate('#doc=' + id);
    } catch (e) {
      reportError('Could not add ' + file.name, e);
    }
  }
}

function closeDoc() {
  sideEditor.close();
  if (state.pdf) state.pdf.destroy();
  state.pdf = null;
  state.docId = null;
}

let pageSaveTimer = null;

async function openDoc(docId, page, annoId, query) {
  const doc = store.get(docId);
  if (state.docId !== docId) {
    showView('doc');
    closeDoc();
    state.docId = docId;
    $('#view-title').textContent = doc.data.title;
    const scroll = $('#pdf-scroll');
    scroll.innerHTML = '<div class="loading">Loading PDF...</div>';

    let bytes;
    try {
      bytes = await store.getFile(docId);
    } catch (e) {
      scroll.innerHTML = '';
      const msg = document.createElement('div');
      msg.className = 'loading error';
      msg.textContent = e.message;
      scroll.appendChild(msg);
      return;
    }
    if (state.docId !== docId) return;

    const view = new PdfView(scroll, {
      getTool,
      onInkAdd: (p, stroke) => inkAdded(docId, p, stroke),
      onInkErase: (p, ids) => inkErased(docId, p, ids),
      onEraseMark: a => eraseMark(a),
      onRegion: (p, rect) => showActions({ kind: 'region', page: p, rects: [rect] }),
    });
    state.pdf = view;
    let n;
    try {
      n = await view.load(bytes);
    } catch (e) {
      // Another paper was opened while this one loaded.
      if (e.closed || state.pdf !== view) return;
      throw e;
    }
    if (state.pdf !== view) return;
    $('#page-count').textContent = '/ ' + n;
    $('#page-input').max = n;
    if (doc.data.pages !== n) store.update(docId, { pages: n });
    view.addEventListener('page', e => {
      $('#page-input').value = e.detail;
      markCurrentSection();
      // Locally at once (survives an immediate reload), synced after a pause.
      try {
        localStorage.setItem('reader.page.' + docId, String(e.detail));
      } catch (err) {
        console.warn('Could not remember the page', err);
      }
      clearTimeout(pageSaveTimer);
      pageSaveTimer = setTimeout(() => {
        const d = store.get(docId);
        if (d && d.data.lastPage !== e.detail) store.update(docId, { lastPage: e.detail });
      }, 4000);
    });
    let sectionFrame = 0;
    $('#pdf-scroll').addEventListener('scroll', () => {
      if (sectionFrame || state.pdf !== view || !state.panelOpen || state.panelMode !== 'contents') return;
      sectionFrame = requestAnimationFrame(() => {
        sectionFrame = 0;
        markCurrentSection();
      });
    }, { passive: true, signal: view.signal });
    refreshDocOverlays();
    // Open the notebook first: it changes the PDF pane's size, and the
    // scroll position must be set for the final size.
    await applyNotebook();
    if (state.pdf !== view) return;
    const localPage = +localStorage.getItem('reader.page.' + docId) || 0;
    view.goTo(page || localPage || doc.data.lastPage || 1, 0, 'instant');
    indexPaperText(docId, view).catch(e => console.error('Indexing the paper text failed', e));
  } else if (page) {
    state.pdf.goTo(page);
  }
  // From a search hit: highlight the words on that page.
  if (query && page) state.pdf.markText(page, query);
  if (annoId) {
    const a = store.get(annoId);
    if (a) state.pdf.showAnno(a);
  }
  renderPanel();
}

// Cards and tasks grouped by the mark they belong to, in one pass.
function itemsByAnno() {
  const map = new Map();
  for (const it of store.all()) {
    if ((it.kind !== 'card' && it.kind !== 'task') || !it.data.annoId) continue;
    if (!map.has(it.data.annoId)) map.set(it.data.annoId, []);
    map.get(it.data.annoId).push(it);
  }
  return map;
}

function refreshDocOverlays() {
  if (!state.pdf) return;
  const byAnno = itemsByAnno();
  const annos = store.forDoc(state.docId, 'anno').map(a => {
    const linked = byAnno.get(a.id) || [];
    const labels = linked.map(it => (it.kind === 'card' ? 'Card' : TASK_LABELS[it.data.type]));
    const details = linked.map(it => (it.kind === 'card'
      ? 'Card: ' + snippet(it.data.front, 60)
      : TASK_LABELS[it.data.type] + ': ' + snippet(it.data.text.replace(/^Explain:\s*/, ''), 60)));
    let marker = labels.map(l => l[0]).join('');
    if (a.data.status === 'unclear') marker = '?' + marker;
    const markerTitle = [
      a.data.status === 'unclear' ? 'Not understood yet' : a.data.status === 'understood' ? 'Understood' : '',
      ...details,
      a.data.comment ? 'Comment: ' + a.data.comment : '',
    ].filter(Boolean).join('\n');
    return { ...a, marker, markerTitle };
  });
  state.pdf.setAnnos(annos);
  for (const ink of store.forDoc(state.docId, 'ink')) state.pdf.setInk(ink.data.page, ink.data.strokes);
}

// Ink writes are serialized per page so quick strokes never overwrite each other.
const inkQueues = new Map();
function saveInk(docId, page, mutate) {
  const id = inkId(docId, page);
  const prev = inkQueues.get(id) || Promise.resolve();
  const next = prev.then(() => {
    const cur = store.get(id);
    const data = cur ? structuredClone(cur.data) : { docId, page, strokes: [], erased: [] };
    mutate(data);
    if (data.erased.length > 5000) data.erased = data.erased.slice(-5000);
    return store.put('ink', id, data);
  }).catch(e => reportError('Saving ink failed', e));
  inkQueues.set(id, next);
  return next;
}

// Rewrites [[Old title]] links in every note after a rename, keeping any
// |label, as Obsidian does. Undoable with the rename it belongs to.
async function retitleLinks(oldTitle, newTitle) {
  const key = normTitle(oldTitle);
  if (!key || !newTitle.trim() || key === normTitle(newTitle)) return 0;
  let changed = 0;
  for (const note of store.all('note')) {
    let touched = false;
    const blocks = note.data.blocks.map(b => {
      if (b.type !== 'md') return b;
      const text = b.text.replace(WIKILINK, (m, target, label) => {
        if (normTitle(target) !== key) return m;
        touched = true;
        return `[[${newTitle}${label !== undefined ? '|' + label : ''}]]`;
      });
      return text === b.text ? b : { ...b, text };
    });
    if (touched) {
      changed++;
      await trackedPut('note', note.id, { ...note.data, blocks });
    }
  }
  return changed;
}

function renderTrash(trashed) {
  const box = $('#trash');
  box.classList.toggle('hidden', !trashed.length);
  if (!trashed.length) return;
  box.querySelector('summary').textContent = `Recently deleted (${trashed.length})`;
  const list = box.querySelector('ul');
  list.innerHTML = '';
  for (const d of trashed.sort((a, b) => b.data.trashedAt - a.data.trashedAt)) {
    const days = Math.max(0, Math.ceil((d.data.trashedAt + TRASH_DAYS * DAY_MS - Date.now()) / DAY_MS));
    const li = document.createElement('li');
    li.className = 'trash-item';
    li.dataset.doc = d.id;
    li.innerHTML = `<div class="trash-title"></div><div class="side-item-meta">Deleted for good in ${days} day${days === 1 ? '' : 's'}</div>
      <div class="trash-actions"><button class="btn-small" data-act="restore">Restore</button><button class="btn-small danger" data-act="purge">Delete now</button></div>`;
    li.querySelector('.trash-title').textContent = d.data.title;
    li.querySelector('[data-act="restore"]').addEventListener('click', async () => {
      try {
        await trackedUpdate(d.id, { trashedAt: undefined });
        toast('Restored ' + snippet(d.data.title, 50));
      } catch (e) {
        reportError('Restoring failed', e);
      }
    });
    li.querySelector('[data-act="purge"]').addEventListener('click', async () => {
      if (!confirm(`Delete "${d.data.title}" for good, with its marks and ink? Cards, tasks and notes are kept. This cannot be undone.`)) return;
      try {
        await purgePaper(d.id);
        toast('Deleted for good');
      } catch (e) {
        reportError('Deleting failed', e);
      }
    });
    list.appendChild(li);
  }
}

// Rename a paper, or remove it with its marks and ink. Cards, tasks and notes
// are study material and stay.
async function paperDialog(docId) {
  const doc = store.get(docId);
  if (!doc) return;
  const dlg = $('#dialog');
  dlg.innerHTML = `<form method="dialog" class="dialog-form">
      <h3>Paper</h3>
      <label>Title <input type="text" name="title" maxlength="500"></label>
      <p class="muted paper-meta"></p>
      <div class="dialog-actions">
        <button value="remove" class="btn btn-secondary danger">Remove paper</button>
        <span class="spacer"></span>
        <button value="cancel" class="btn btn-secondary">Cancel</button>
        <button value="ok" class="btn btn-primary">Save</button>
      </div>
    </form>`;
  const title = dlg.querySelector('[name=title]');
  title.value = doc.data.title;
  const marks = store.forDoc(docId, 'anno').length;
  dlg.querySelector('[value="remove"]').textContent = 'Move to Recently deleted';
  dlg.querySelector('.paper-meta').textContent = `${doc.data.filename} \u00b7 ${doc.data.pages} pages \u00b7 ${marks} marks`;
  const done = new Promise(r => { dlg.onclose = r; });
  dlg.showModal();
  await done;
  try {
    if (dlg.returnValue === 'ok' && title.value.trim() && title.value.trim() !== doc.data.title) {
      const newTitle = title.value.trim();
      const n = await undoHistory.batch('Rename', async () => {
        await trackedUpdate(docId, { title: newTitle });
        const nb = paperNotebook(docId);
        if (nb && nb.data.title === ('Notes: ' + doc.data.title).slice(0, 300)) {
          await trackedUpdate(nb.id, { title: ('Notes: ' + newTitle).slice(0, 300) });
        }
        return retitleLinks(doc.data.title, newTitle);
      });
      if (state.docId === docId) $('#view-title').textContent = newTitle;
      if (n) toast(`Renamed; updated links in ${n} note${n === 1 ? '' : 's'}`);
    } else if (dlg.returnValue === 'remove') {
      if (state.docId === docId) navigate('#');
      await trackedUpdate(docId, { trashedAt: Date.now() });
      toast(`Moved to Recently deleted for ${TRASH_DAYS} days: Undo or restore it from the library`);
    }
  } catch (e) {
    reportError('Updating the paper failed', e);
  }
}

// ── Paper notebook (split view) ──

// One notebook per paper, with an id derived from the paper, so two devices
// that open it offline create the same note (and sync merges it) rather than
// two notebooks.
function notebookId(docId) {
  return 'nb-' + docId.slice(0, 40);
}

function paperNotebook(docId) {
  return store.get(notebookId(docId)) || store.all('note').find(n => n.data.notebookFor === docId);
}

async function ensurePaperNotebook(docId) {
  const existing = paperNotebook(docId);
  if (existing) return existing;
  const doc = store.get(docId);
  // Deterministic content too: two untouched notebooks from two devices are
  // identical, so merging them makes no conflict copy.
  return store.put('note', notebookId(docId), {
    title: ('Notes: ' + doc.data.title).slice(0, 300),
    notebookFor: docId,
    blocks: [{ id: 'nbb-' + docId.slice(0, 40), type: 'md', text: `Reading [[${doc.data.title}]]\n` }],
  });
}

async function applyNotebook() {
  const pane = $('#doc-notebook');
  pane.classList.toggle('hidden', !state.notebookOpen);
  $('#split-handle').classList.toggle('hidden', !state.notebookOpen);
  $('#toggle-notebook').classList.toggle('active', state.notebookOpen);
  $('#toggle-notebook').setAttribute('aria-pressed', String(state.notebookOpen));
  if (!state.docId) return;
  if (state.notebookOpen) {
    const note = await ensurePaperNotebook(state.docId);
    if (sideEditor.noteId !== note.id) sideEditor.open(note.id);
  } else {
    sideEditor.close();
  }
  // The PDF view re-fits itself when its pane changes size.
}

// Drag (or arrow keys on) the handle between the PDF and the notebook. The
// notebook's share is kept per orientation: side by side, or stacked.
function wireSplitHandle() {
  const handle = $('#split-handle');
  const split = $('.doc-split');
  const key = () => (NARROW.matches ? 'reader.nbSizeV' : 'reader.nbSize');
  const prop = () => (NARROW.matches ? '--nb-size-v' : '--nb-size');
  const apply = frac => {
    const f = Math.min(0.8, Math.max(0.2, frac));
    split.style.setProperty(prop(), String(f));
    handle.setAttribute('aria-valuenow', String(Math.round(f * 100)));
    return f;
  };
  const save = f => {
    try {
      localStorage.setItem(key(), String(f));
    } catch (e) {
      console.warn('Could not remember the notebook size', e);
    }
  };
  for (const [k, p] of [['reader.nbSize', '--nb-size'], ['reader.nbSizeV', '--nb-size-v']]) {
    const v = parseFloat(localStorage.getItem(k));
    if (v >= 0.2 && v <= 0.8) split.style.setProperty(p, String(v));
  }
  handle.setAttribute('aria-orientation', NARROW.matches ? 'horizontal' : 'vertical');
  NARROW.addEventListener('change', () => handle.setAttribute('aria-orientation', NARROW.matches ? 'horizontal' : 'vertical'));

  let dragging = false;
  let frac = 0;
  handle.addEventListener('pointerdown', e => {
    e.preventDefault();
    dragging = true;
    handle.classList.add('dragging');
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', e => {
    if (!dragging) return;
    const r = split.getBoundingClientRect();
    frac = apply(NARROW.matches ? (r.bottom - e.clientY) / r.height : (r.right - e.clientX) / r.width);
  });
  const end = () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('dragging');
    if (frac) save(frac);
  };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
  handle.addEventListener('keydown', e => {
    const grow = NARROW.matches ? 'ArrowUp' : 'ArrowLeft';
    const shrink = NARROW.matches ? 'ArrowDown' : 'ArrowRight';
    if (e.key !== grow && e.key !== shrink) return;
    e.preventDefault();
    const cur = parseFloat(getComputedStyle(split).getPropertyValue(prop())) || (NARROW.matches ? 0.45 : 0.46);
    save(apply(cur + (e.key === grow ? 0.05 : -0.05)));
  });
}

// The note that "To notebook" writes into: the open side notebook, else the
// paper's notebook.
async function notebookTarget() {
  if (state.notebookOpen && sideEditor.noteId) return sideEditor;
  state.notebookOpen = true;
  localStorage.setItem('reader.notebook', '1');
  await applyNotebook();
  return sideEditor;
}

// ── Selection, regions and actions ──

function currentSelectionTarget() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const range = sel.getRangeAt(0);
  const startEl = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
  const pageEl = startEl && startEl.closest('.pdf-page');
  if (!pageEl || !startEl.closest('.textLayer')) return null;
  // Capped at the vault's limit; a select-all highlight still works.
  const quote = sel.toString().replace(/\s+/g, ' ').trim().slice(0, 20_000);
  if (!quote) return null;
  const box = pageEl.getBoundingClientRect();
  const rects = [...range.getClientRects()]
    .filter(r => r.top >= box.top - 2 && r.bottom <= box.bottom + 2)
    .map(r => ({ left: r.left - box.left, top: r.top - box.top, width: r.width, height: r.height }));
  const norm = selectionRects(rects, box.width, box.height);
  if (!norm.length) return null;
  return { kind: 'selection', page: +pageEl.dataset.page, rects: norm, quote, anchor: range.getBoundingClientRect() };
}

const ACTIONS = {
  selection: ['highlight', 'comment', 'notebook', 'card', 'explain', 'unclear', 'todo', 'question', 'pin', 'link'],
  region: ['eqcard', 'latex', 'explain', 'unclear', 'comment', 'todo', 'question', 'derive', 'pin', 'link'],
  anno: ['readexp', 'comment', 'notebook', 'card', 'explain', 'unclear', 'understood', 'todo', 'question', 'pin', 'unpin', 'link', 'delete'],
};
const ACTION_LABELS = {
  highlight: 'Highlight', comment: 'Comment', notebook: 'To notebook', card: 'Card', explain: 'Explain',
  todo: 'Follow-up', question: 'Question', link: 'Copy link', eqcard: 'Equation card', latex: 'LaTeX to notebook',
  derive: 'Re-derive', delete: 'Delete', unclear: 'Not clear yet', understood: 'Understood', readexp: 'Read explanation',
  pin: 'Add to Brief', unpin: 'Remove from Brief',
};

function showActions(target) {
  state.target = target;
  const bar = $('#action-bar');
  bar.innerHTML = '';
  if (target.kind === 'anno') {
    const head = document.createElement('div');
    head.className = 'action-head';
    head.textContent = target.anno.data.type === 'region' ? `Region, p. ${target.anno.data.page}` : '“' + snippet(target.anno.data.quote, 80) + '”';
    bar.appendChild(head);
  }
  const status = target.kind === 'anno' ? target.anno.data.status : null;
  for (const act of ACTIONS[target.kind]) {
    if ((act === 'unclear' && status === 'unclear') || (act === 'understood' && status !== 'unclear')) continue;
    if (act === 'readexp' && !explanationFor(target.anno.id)) continue;
    const pinned = target.kind === 'anno' && target.anno.data.brief;
    if ((act === 'pin' && pinned) || (act === 'unpin' && !pinned)) continue;
    const b = document.createElement('button');
    b.className = 'action-btn' + (act === 'delete' ? ' danger' : '');
    b.textContent = ACTION_LABELS[act];
    b.addEventListener('pointerdown', e => e.preventDefault()); // keep the text selection
    b.addEventListener('click', () => runAction(act).catch(e => reportError(ACTION_LABELS[act] + ' failed', e)));
    bar.appendChild(b);
  }
  if (target.kind === 'selection') {
    for (const c of HIGHLIGHT_COLORS) {
      const s = document.createElement('button');
      s.className = 'swatch small' + (c === state.tool.hlColor ? ' active' : '');
      s.style.setProperty('--swatch', c);
      s.setAttribute('aria-label', 'Highlight ' + COLOR_NAMES[c].toLowerCase());
      s.title = 'Highlight ' + COLOR_NAMES[c].toLowerCase();
      s.addEventListener('pointerdown', e => e.preventDefault());
      s.addEventListener('click', () => {
        state.tool.hlColor = c;
        runAction('highlight').catch(e => reportError('Highlight failed', e));
      });
      bar.appendChild(s);
    }
  }
  bar.classList.remove('hidden');
  positionBar(target);
}

function positionBar(target) {
  const bar = $('#action-bar');
  let anchor = target.anchor;
  if (!anchor && state.pdf) {
    const pageEl = state.pdf.pageElement(target.page || target.anno.data.page);
    const [x, y, w, h] = (target.rects || target.anno.data.rects).slice(-1)[0];
    const r = pageEl.getBoundingClientRect();
    anchor = { left: r.left + x * r.width, top: r.top + y * r.height, bottom: r.top + (y + h) * r.height, width: w * r.width };
  }
  const bw = bar.offsetWidth, bh = bar.offsetHeight;
  // Below the selection: iPad shows its own copy/look-up menu above it.
  let top = anchor.bottom + 12;
  if (top + bh > innerHeight - 8) top = anchor.top - bh - 12;
  top = Math.min(Math.max(8, top), innerHeight - bh - 8);
  const left = Math.min(Math.max(8, anchor.left + anchor.width / 2 - bw / 2), innerWidth - bw - 8);
  bar.style.top = top + 'px';
  bar.style.left = left + 'px';
}

function hideActions() {
  $('#action-bar').classList.add('hidden');
  state.target = null;
}

// The mark an action applies to. Marks from a fresh selection or region are
// saved only when the action completes, so a cancelled dialog or a failed AI
// call leaves nothing behind. Returns { anno, saved }.
function pendingAnno(target) {
  if (target.kind === 'anno') return { anno: target.anno, saved: true };
  const type = target.kind === 'region' ? 'region' : 'highlight';
  if (type === 'region') {
    // Dragging around an equation that is already marked reuses that mark.
    const same = store.forDoc(state.docId, 'anno').find(a => a.data.type === 'region'
      && a.data.page === target.page && overlap(a.data.rects[0], target.rects[0]) > 0.6);
    if (same) return { anno: same, saved: true };
  }
  return {
    saved: false,
    anno: {
      id: newId(),
      kind: 'anno',
      data: {
        docId: state.docId,
        page: target.page,
        type,
        rects: target.rects,
        quote: target.quote || '',
        color: type === 'region' ? '#2563eb' : state.tool.hlColor,
      },
    },
  };
}

// Intersection over union of two [x, y, w, h] rects.
function overlap([ax, ay, aw, ah], [bx, by, bw, bh]) {
  const iw = Math.max(0, Math.min(ax + aw, bx + bw) - Math.max(ax, bx));
  const ih = Math.max(0, Math.min(ay + ah, by + bh) - Math.max(ay, by));
  const inter = iw * ih;
  return inter / (aw * ah + bw * bh - inter || 1);
}

// Saves the mark (with any extra fields) and returns the stored item.
async function commitAnno(p, patch = {}) {
  if (p.saved) {
    if (Object.keys(patch).length) await trackedUpdate(p.anno.id, patch);
    return store.get(p.anno.id);
  }
  p.anno = await trackedPut('anno', p.anno.id, { ...p.anno.data, ...patch });
  p.saved = true;
  window.getSelection().removeAllRanges();
  return p.anno;
}

function docTitle() {
  const d = store.get(state.docId);
  return d ? d.data.title : '';
}

// Everything one action writes (mark, task, card) undoes as one step.
function runAction(act) {
  return undoHistory.batch(ACTION_LABELS[act] || act, () => runActionNow(act));
}

async function runActionNow(act) {
  const target = state.target;
  if (!target) return;
  const page = target.page || (target.anno && target.anno.data.page);
  const isRegion = target.kind === 'region' || (target.anno && target.anno.data.type === 'region');

  if (act === 'delete') {
    const a = target.anno;
    const linked = store.all().filter(it => (it.kind === 'card' || it.kind === 'task') && it.data.annoId === a.id);
    if (linked.length && !confirm(`Delete this mark? Its ${linked.length} card(s)/task(s) are kept, with the passage's text and page.`)) return;
    // Cards and tasks keep what they were about.
    const source = { page: a.data.page, quote: a.data.type === 'region' ? (a.data.latex ? `$${a.data.latex}$` : '') : snippet(a.data.quote, 2000) };
    for (const it of linked) await trackedUpdate(it.id, { source });
    await trackedRemove(a.id);
    hideActions();
    toast('Mark deleted: Undo brings it back');
    return;
  }

  if (act === 'readexp') {
    hideActions();
    showExplanation(explanationFor(target.anno.id));
    return;
  }

  const p = pendingAnno(target);
  hideActions();
  const quote = p.anno.data.quote;
  const regionLatex = async () => p.anno.data.latex
    || equationToLatex(await state.pdf.regionImage(page, p.anno.data.rects[0]));

  if (act === 'pin' || act === 'unpin') {
    const pin = act === 'pin';
    const anno = await commitAnno(p, { brief: pin });
    toast(pin ? 'Added to the Brief' : 'Removed from the Brief');
    // An equation in the Brief should read as an equation.
    if (pin && anno.data.type === 'region' && !anno.data.latex && state.pdf) {
      equationToLatex(await state.pdf.regionImage(anno.data.page, anno.data.rects[0]))
        .then(latex => store.get(anno.id) && store.update(anno.id, { latex }))
        .catch(e => console.warn('No LaTeX for the pinned region', e));
    }
  } else if (act === 'highlight') {
    await commitAnno(p);
  } else if (act === 'unclear' || act === 'understood') {
    await commitAnno(p, { status: act });
    toast(act === 'unclear' ? 'Marked as not clear yet: it is listed in the Brief and the Marks panel' : 'Marked as understood');
  } else if (act === 'comment') {
    const text = await promptDialog('Comment', p.anno.data.comment || '', { multiline: true, placeholder: 'Margin note for this passage', context: quote, maxLength: 50_000 });
    if (text !== null) await commitAnno(p, { comment: text });
  } else if (act === 'link') {
    const anno = await commitAnno(p);
    const link = `[[@${anno.id}]]`;
    try {
      await navigator.clipboard.writeText(link);
      toast('Copied ' + link + ': paste it into any note');
    } catch (e) {
      await promptDialog('Copy this link into a note', link);
    }
  } else if (act === 'notebook') {
    const anno = await commitAnno(p);
    const ed = await notebookTarget();
    ed.appendMarkdown(`> ${quote.replace(/\n/g, ' ')}\n> [[@${anno.id}|p. ${page}]]\n\n`);
  } else if (act === 'latex') {
    toast('Reading the equation...');
    const latex = await regionLatex();
    const anno = await commitAnno(p, { latex });
    const ed = await notebookTarget();
    ed.appendMarkdown(`$$${latex}$$\n[[@${anno.id}|p. ${page}]]\n\n`);
  } else if (act === 'card' || act === 'eqcard') {
    await cardDialog(p, act === 'eqcard' || isRegion);
  } else if (act === 'explain') {
    await createExplainTask(await commitAnno(p), isRegion);
  } else if (act === 'derive') {
    toast('Reading the equation...');
    const latex = await regionLatex();
    const anno = await commitAnno(p, { latex });
    await trackedCreate('task', { text: `Re-derive: $${latex}$`, type: 'derive', status: 'open', docId: state.docId, annoId: anno.id });
    const ed = await notebookTarget();
    ed.draft.blocks.push(
      { id: newId(), type: 'md', text: `**Derive** $${latex}$ [[@${anno.id}|p. ${page}]]\nWrite each step below, then *Check with SymPy*.` },
      { id: newId(), type: 'ink', aspect: 0.75, strokes: [] },
    );
    ed.saveSoon();
    ed.render();
  } else if (act === 'todo' || act === 'question') {
    const label = act === 'todo' ? 'Follow-up task' : 'Question for journal club';
    const def = act === 'todo' ? 'Follow up: ' + snippet(quote || 'region on p. ' + page, 80) : '';
    const text = await promptDialog(label, def, {
      multiline: true,
      context: quote || `Region on p. ${page}`,
      placeholder: act === 'question' ? 'What do you want to ask or discuss?' : '',
    });
    if (text) {
      const anno = await commitAnno(p);
      await trackedCreate('task', { text, type: act, status: 'open', docId: state.docId, annoId: anno.id });
    }
  }
}

// The latest written explanation for a mark, if any.
function explanationFor(annoId) {
  return store.all('task')
    .filter(t => t.data.type === 'explain' && t.data.annoId === annoId && t.data.explanation)
    .sort((a, b) => b.updatedAt - a.updatedAt)[0] || null;
}

function showExplanation(t) {
  const dlg = $('#dialog');
  dlg.innerHTML = `<form method="dialog" class="dialog-form">
      <h3></h3>
      <div class="md-view explain-body"></div>
      <div class="dialog-actions"><button value="cancel" class="btn btn-primary">Close</button></div>
    </form>`;
  dlg.querySelector('h3').textContent = t.data.text;
  dlg.querySelector('.explain-body').innerHTML = renderMarkdown(t.data.explanation, resolveLink);
  dlg.showModal();
}

async function createExplainTask(anno, isRegion) {
  const docId = anno.data.docId;
  // Asking for an explanation means it is not clear (again).
  if (anno.data.status !== 'unclear') await trackedUpdate(anno.id, { status: 'unclear' });
  const task = await trackedCreate('task', {
    text: 'Explain: ' + (isRegion ? `region on p. ${anno.data.page}` : snippet(anno.data.quote, 100)),
    type: 'explain',
    status: 'open',
    docId,
    annoId: anno.id,
  });
  toast('Writing an explanation: open Study to watch it appear.');
  generateExplanation(task.id);
}

// Runs fn with a PdfView for the paper: the open one, or the file loaded
// off screen (e.g. when writing an explanation from Study).
async function withPaper(docId, fn) {
  if (state.pdf && state.docId === docId) return fn(state.pdf);
  const view = new PdfView(document.createElement('div'), { getTool });
  await view.open(await store.getFile(docId));
  try {
    return await fn(view);
  } finally {
    view.destroy();
  }
}

// A generation older than this with no result was interrupted (tab closed,
// reload); Study offers Retry for it.
const EXPLAIN_STALE_MS = 3 * 60 * 1000;
const explaining = new Set();

// Explanations stream in: the text so far, shown in Study while it is written.
const liveText = new Map(); // taskId -> markdown so far
let liveTimer = null;
function showLiveText() {
  if (liveTimer) return;
  liveTimer = setTimeout(() => {
    liveTimer = null;
    for (const el of document.querySelectorAll('[data-live]')) {
      const text = liveText.get(el.dataset.live);
      if (text) el.innerHTML = renderMarkdown(text, resolveLink);
    }
  }, 200);
}

function explainState(task) {
  if (explaining.has(task.id)) return 'writing';
  if (task.data.error) return 'failed';
  if (task.data.pending && Date.now() - task.data.pending > EXPLAIN_STALE_MS) return 'interrupted';
  if (task.data.pending) return 'writing';
  return 'idle';
}

// What a student can act on, instead of "Failed to fetch".
function friendlyError(e) {
  const msg = e && e.message ? e.message : String(e);
  if (e instanceof TypeError || /failed to fetch|network|load failed/i.test(msg)) {
    return "Couldn't reach the AI service. Check your connection, then Retry.";
  }
  if (/HTTP 401|HTTP 403/.test(msg)) return 'The AI service rejected the API key. Check it in Settings.';
  if (/HTTP 429/.test(msg)) return 'The AI service is rate limiting requests. Wait a minute, then Retry.';
  if (/HTTP 5\d\d/.test(msg)) return 'The AI service had an error. Retry in a moment.';
  return msg;
}

async function generateExplanation(taskId) {
  if (explaining.has(taskId) || !store.get(taskId)) return;
  explaining.add(taskId);
  const task = store.get(taskId);
  const anno = store.get(task.data.annoId);
  const doc = anno && store.get(anno.data.docId);
  try {
    await store.update(taskId, { pending: Date.now(), error: undefined });
    if (!anno) throw new Error('The marked passage was deleted');
    const { context, image } = await withPaper(anno.data.docId, async view => ({
      context: await view.contextFor(anno.data.page, anno.data.quote),
      image: anno.data.type === 'region' ? await view.regionImage(anno.data.page, anno.data.rects[0]) : null,
    }));
    const explanation = await explainPassage({
      docTitle: doc ? doc.data.title : '',
      quote: anno.data.quote || anno.data.latex,
      context,
      image,
      onDelta: text => {
        liveText.set(taskId, text);
        showLiveText();
      },
    });
    // The task may have been undone while the model was writing.
    if (!store.get(taskId)) return;
    await store.update(taskId, { explanation, status: 'ready', pending: undefined, error: undefined });
    toast('Explanation ready in Study');
  } catch (e) {
    console.error('Explanation failed', e);
    if (store.get(taskId)) await store.update(taskId, { error: friendlyError(e), pending: undefined });
    toast('Explanation failed: ' + friendlyError(e), true);
  } finally {
    explaining.delete(taskId);
    liveText.delete(taskId);
    renderSidebar();
    if (state.view === 'study' && !state.review) renderStudy();
  }
}

// ── Dialogs ──

function promptDialog(title, value = '', opts = {}) {
  const dlg = $('#dialog');
  dlg.innerHTML = `<form method="dialog" class="dialog-form">
      <h3></h3>
      ${opts.context ? '<blockquote class="dialog-context"></blockquote>' : ''}
      ${opts.multiline ? '<textarea rows="4"></textarea>' : '<input type="text">'}
      <div class="dialog-actions">
        <button value="cancel" class="btn btn-secondary">Cancel</button>
        <button value="ok" class="btn btn-primary">Save</button>
      </div>
    </form>`;
  dlg.querySelector('h3').textContent = title;
  dlg.querySelector('textarea, input').setAttribute('aria-label', title);
  if (opts.context) dlg.querySelector('.dialog-context').textContent = snippet(opts.context, 300);
  const field = dlg.querySelector('textarea, input');
  // Matches the vault's limits (task text 5k, comments 50k).
  field.maxLength = opts.maxLength || 5000;
  field.value = value;
  if (opts.placeholder) field.placeholder = opts.placeholder;
  return new Promise(resolve => {
    dlg.onclose = () => resolve(dlg.returnValue === 'ok' ? field.value.trim() : null);
    dlg.showModal();
    field.focus();
  });
}

// p: { anno, saved } from pendingAnno. The mark is saved with the card.
async function cardDialog(p, fromEquation) {
  const anno = p.anno;
  const dlg = $('#dialog');
  dlg.innerHTML = `<form method="dialog" class="dialog-form card-form">
      <h3>New card</h3>
      <div class="card-source md-view"></div>
      <p class="dialog-status" role="status"></p>
      <label>Front <textarea name="front" rows="3" maxlength="20000" placeholder="A precise question"></textarea></label>
      <div class="card-preview" data-for="front"></div>
      <label>Back <textarea name="back" rows="4" maxlength="20000" placeholder="Answer, with $math$"></textarea></label>
      <div class="card-preview" data-for="back"></div>
      <div class="dialog-actions">
        <button type="button" class="btn btn-secondary" data-draft>Draft with AI</button>
        <span class="spacer"></span>
        <button value="cancel" class="btn btn-secondary">Cancel</button>
        <button value="ok" class="btn btn-primary">Save card</button>
      </div>
    </form>`;
  const front = dlg.querySelector('[name=front]');
  const back = dlg.querySelector('[name=back]');
  const status = dlg.querySelector('.dialog-status');
  const preview = () => {
    for (const f of [front, back]) {
      dlg.querySelector(`[data-for=${f.name}]`).innerHTML = renderMarkdown(f.value, resolveLink);
    }
  };
  // Text the user typed is never replaced by a draft that arrives later.
  const typed = { front: false, back: false };
  front.addEventListener('input', () => { typed.front = true; preview(); });
  back.addEventListener('input', () => { typed.back = true; preview(); });

  let latex = anno.data.latex || '';
  back.value = latex ? `$$${latex}$$` : anno.data.quote;
  preview();
  // The source stays in view, to check the draft against.
  const source = dlg.querySelector('.card-source');
  const showSource = () => {
    source.innerHTML = renderMarkdown('**From the paper:** ' + (latex ? `$$${latex}$$` : '> ' + snippet(anno.data.quote, 600)), resolveLink);
  };
  showSource();

  const draft = async () => {
    status.classList.remove('error');
    status.textContent = 'Drafting...';
    try {
      if (fromEquation && !latex) {
        status.textContent = 'Reading the equation...';
        latex = await equationToLatex(await withPaper(anno.data.docId, v => v.regionImage(anno.data.page, anno.data.rects[0])));
        if (!back.value.trim()) back.value = `$$${latex}$$`;
        preview();
        showSource();
        status.textContent = 'Drafting...';
      }
      const context = await withPaper(anno.data.docId, v => v.contextFor(anno.data.page, anno.data.quote, latex ? 1500 : 3000));
      const doc = store.get(anno.data.docId);
      const card = await draftCard({ docTitle: doc ? doc.data.title : '', quote: anno.data.quote, latex, context });
      if (!dlg.open) return;
      if (!typed.front && !typed.back) {
        front.value = card.front;
        back.value = card.back;
        preview();
        status.textContent = 'Edit the draft, then save.';
        return;
      }
      // The user started writing: offer the draft instead of overwriting.
      status.textContent = 'The AI draft is ready. ';
      const use = document.createElement('button');
      use.type = 'button';
      use.className = 'btn-small';
      use.textContent = 'Replace my text with it';
      use.addEventListener('click', () => {
        front.value = card.front;
        back.value = card.back;
        typed.front = typed.back = false;
        preview();
        status.textContent = 'Edit the draft, then save.';
      });
      status.appendChild(use);
    } catch (e) {
      console.error('Card draft failed', e);
      status.textContent = 'AI draft failed: ' + friendlyError(e) + ' You can still write the card yourself.';
      status.classList.add('error');
    }
  };
  dlg.querySelector('[data-draft]').addEventListener('click', draft);

  // Saving with an empty front keeps the editor open instead of losing the draft.
  dlg.querySelector('form').addEventListener('submit', e => {
    if (e.submitter && e.submitter.value === 'ok' && !front.value.trim()) {
      e.preventDefault();
      status.textContent = 'Write a question on the front first.';
      status.classList.add('error');
      front.focus();
    }
  });
  const done = new Promise(resolve => { dlg.onclose = resolve; });
  dlg.showModal();
  // Draft right away when an AI backend is set up; otherwise write by hand.
  if (fromEquation || C.handwriteBackend() === 'lmstudio' || C.openrouterApiKey()) draft();
  else front.focus();
  await done;
  if (dlg.returnValue !== 'ok') return;
  const saved = await commitAnno(p, latex && latex !== anno.data.latex ? { latex } : {});
  await trackedCreate('card', {
    front: front.value.trim(),
    back: back.value.trim(),
    docId: saved.data.docId,
    annoId: saved.id,
    srs: newSrs(),
  });
  toast('Card saved');
}

// ── Context panel ──

function setPanel(open, mode) {
  state.panelOpen = open;
  if (mode) state.panelMode = mode;
  try {
    localStorage.setItem('reader.panel', open ? '1' : '0');
    localStorage.setItem('reader.panelMode', state.panelMode);
  } catch (e) {
    console.warn('Could not remember the panel state', e);
  }
  renderPanel();
}

// The Marks and Contents buttons share the doc panel: each opens its own view,
// and pressing it again closes the panel.
function togglePanel(mode) {
  setPanel(!(state.panelOpen && state.panelMode === mode), mode);
}

function renderPanel() {
  const panel = $('#panel');
  const show = state.panelOpen && (state.view === 'doc' || state.view === 'note');
  panel.classList.toggle('hidden', !show);
  const pressed = (id, on) => {
    $(id).classList.toggle('active', on);
    $(id).setAttribute('aria-pressed', String(on));
  };
  pressed('#toggle-panel', state.panelOpen && state.panelMode === 'marks');
  pressed('#toggle-contents', state.panelOpen && state.panelMode === 'contents');
  pressed('#toggle-note-panel', state.panelOpen);
  if (!show) return;
  // In portrait the panel overlays the page; it starts below the toolbar so
  // every toolbar button stays reachable.
  const bar = state.view === 'doc' ? $('.doc-toolbar') : $('.note-toolbar');
  panel.style.top = NARROW.matches && bar ? bar.offsetHeight + 'px' : '';
  if (state.view === 'doc' && state.panelMode === 'contents') renderContentsPanel(panel);
  else if (state.view === 'doc') renderDocPanel(panel);
  else renderNotePanel(panel);
  // Always closable from inside: on narrow screens the panel covers the toolbar.
  const close = document.createElement('button');
  close.className = 'icon-btn panel-close';
  close.title = 'Close panel (Esc)';
  close.setAttribute('aria-label', 'Close panel');
  close.innerHTML = '&times;';
  close.addEventListener('click', () => setPanel(false));
  panel.prepend(close);
}

function renderContentsPanel(panel) {
  panel.innerHTML = `<section>
      <h3>Contents</h3>
      <div class="find-row">
        <input class="find-box" type="search" placeholder="Find in this paper" aria-label="Find in this paper" enterkeyhint="search">
        <span class="find-count muted" aria-live="polite"></span>
      </div>
      <ol class="find-results hidden"></ol>
      <p class="muted toc-note">Reading the table of contents...</p>
      <ol class="toc"></ol>
    </section>`;
  const view = state.pdf;
  if (!view || !view.pdf) return;
  wireFind(panel, view);
  view.contents().then(({ items, source }) => {
    if (state.pdf !== view || !state.panelOpen || state.panelMode !== 'contents') return;
    const note = panel.querySelector('.toc-note');
    note.textContent = !items.length
      ? 'This PDF has no outline, and no headings could be detected (it may be scanned).'
      : source === 'detected' ? 'This PDF has no outline; these headings were detected from font sizes.' : '';
    note.classList.toggle('hidden', !note.textContent);
    const list = panel.querySelector('.toc');
    items.forEach((it, i) => {
      const li = document.createElement('li');
      li.innerHTML = '<button class="toc-item"><span class="toc-title"></span><span class="toc-page"></span></button>';
      li.className = 'toc-depth-' + Math.min(it.depth, 3);
      li.dataset.i = String(i);
      li.querySelector('.toc-title').textContent = it.title;
      li.querySelector('.toc-page').textContent = String(it.page);
      li.querySelector('button').addEventListener('click', () => {
        if (NARROW.matches) setPanel(false);
        view.goTo(it.page, it.yFrac, 'smooth', 16);
      });
      list.appendChild(li);
    });
    markCurrentSection();
  }).catch(e => reportError('Reading the contents failed', e));
}

// Find in paper: results replace the contents list while there is a query.
let findTimer = null;
let lastFind = '';
function wireFind(panel, view) {
  const box = panel.querySelector('.find-box');
  const results = panel.querySelector('.find-results');
  const toc = panel.querySelector('.toc');
  const count = panel.querySelector('.find-count');
  let hitsNow = [];
  let at = -1;
  // Shows hit i: jumps there, highlights it, marks its row, updates "i of n".
  const show = (i, keepPanel) => {
    if (!hitsNow.length) return;
    at = (i + hitsNow.length) % hitsNow.length;
    const h = hitsNow[at];
    results.querySelectorAll('.current').forEach(b => b.classList.remove('current'));
    const btn = results.querySelectorAll('.find-hit-item')[at];
    if (btn) {
      btn.classList.add('current');
      btn.scrollIntoView({ block: 'nearest' });
    }
    count.textContent = `${at + 1} of ${hitsNow.length}`;
    if (!keepPanel && NARROW.matches) setPanel(false);
    view.goTo(h.page, 0, 'instant');
    view.markText(h.page, box.value.trim());
  };
  const note = panel.querySelector('.toc-note');
  const run = async () => {
    // The panel may have switched or closed during the debounce.
    if (!box.isConnected) return;
    const q = box.value.trim();
    lastFind = box.value;
    toc.classList.toggle('hidden', !!q);
    note.classList.toggle('hidden', !!q || !note.textContent);
    results.classList.toggle('hidden', !q);
    if (!q) {
      view.markText(null);
      count.textContent = '';
      hitsNow = [];
      return;
    }
    const hits = await view.find(q);
    if (!box.isConnected || box.value.trim() !== q) return;
    hitsNow = hits.slice(0, 200);
    at = -1;
    count.textContent = hits.length ? `${hits.length}${hits.length >= 300 ? '+' : ''} found` : '';
    results.innerHTML = hits.length ? '' : '<li class="muted">No matches in this paper.</li>';
    hits.slice(0, 200).forEach((h, i) => {
      const li = document.createElement('li');
      li.innerHTML = '<button class="find-hit-item"><span class="toc-page"></span><span class="find-snippet"></span></button>';
      li.querySelector('.toc-page').textContent = 'p. ' + h.page;
      // The match itself is wrapped in <mark>; the text around it is set as text.
      const snip = li.querySelector('.find-snippet');
      const [before, match, after] = splitAround(h.text, h.at, q.length, 45);
      const mark = document.createElement('mark');
      mark.textContent = match;
      snip.append(before, mark, after);
      li.querySelector('button').addEventListener('click', () => show(i, false));
      results.appendChild(li);
    });
    if (hits.length >= 300) results.insertAdjacentHTML('beforeend', '<li class="muted">Showing the first 300 matches.</li>');
  };
  box.addEventListener('input', () => {
    clearTimeout(findTimer);
    findTimer = setTimeout(run, 250);
  });
  // Enter / Shift+Enter step through the matches and keep the panel open.
  box.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    show(at < 0 ? 0 : at + (e.shiftKey ? -1 : 1), true);
  });
  if (lastFind) {
    box.value = lastFind;
    run();
  }
}

// Highlights the section being read: the last entry that starts at or
// before the top of the current page view.
function markCurrentSection() {
  const list = document.querySelector('#panel .toc');
  const view = state.pdf;
  if (!list || !view || !view._contents) return;
  const pos = view.position();
  if (!pos) return;
  const at = pos.page + pos.frac;
  let current = -1;
  view._contents.items.forEach((it, i) => {
    if (it.page + it.yFrac <= at + 0.05) current = i;
  });
  for (const li of list.children) {
    const on = +li.dataset.i === current;
    li.classList.toggle('current', on);
    if (on && !li.dataset.seen) {
      li.dataset.seen = '1';
      li.scrollIntoView({ block: 'nearest' });
    }
  }
}

function renderDocPanel(panel) {
  const docId = state.docId;
  const all = store.forDoc(docId, 'anno').sort((a, b) => a.data.page - b.data.page || a.data.rects[0][1] - b.data.rects[0][1]);
  const unclearCount = all.filter(a => a.data.status === 'unclear').length;
  const annos = state.panelFilter === 'unclear' ? all.filter(a => a.data.status === 'unclear') : all;
  const linked = store.all().filter(it => (it.kind === 'card' || it.kind === 'task') && it.data.docId === docId);
  const idx = linkIndex();
  const noteIds = notesForDoc(idx, store.all(), docId);

  panel.innerHTML = `
    <section><h3>Linked notes</h3><div class="panel-notes"></div></section>
    <section>
      <h3>Marks <span class="muted">${all.length}</span></h3>
      <div class="mark-filter" role="group" aria-label="Filter marks">
        <button class="btn-small${state.panelFilter === 'all' ? ' active' : ''}" data-filter="all">All</button>
        <button class="btn-small${state.panelFilter === 'unclear' ? ' active' : ''}" data-filter="unclear">Not clear yet (${unclearCount})</button>
      </div>
      <ol class="mark-list"></ol>
    </section>`;
  panel.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => {
    state.panelFilter = b.dataset.filter;
    renderPanel();
  }));
  const notesBox = panel.querySelector('.panel-notes');
  const nb = paperNotebook(docId);
  if (nb) noteIds.add(nb.id);
  if (!noteIds.size) notesBox.innerHTML = '<p class="muted">Link this paper from any note with [[' + escapeHtml(docTitle()) + ']]</p>';
  for (const id of noteIds) {
    const n = store.get(id);
    if (!n) continue;
    const a = document.createElement('a');
    a.className = 'chip';
    a.href = '#note=' + id;
    a.textContent = noteTitle(n);
    notesBox.appendChild(a);
  }

  const list = panel.querySelector('.mark-list');
  if (!annos.length) {
    list.innerHTML = state.panelFilter === 'unclear'
      ? '<li class="muted">Nothing marked as not clear. Use Explain or "Not clear yet" on a mark.</li>'
      : '<li class="muted">Select text or use the Region tool to mark something.</li>';
  }
  for (const a of annos) {
    const li = document.createElement('li');
    li.className = 'mark';
    li.dataset.anno = a.id;
    li.style.setProperty('--anno-color', a.data.color);
    const items = linked.filter(it => it.data.annoId === a.id);
    li.innerHTML = `<div class="mark-page">p. ${a.data.page}</div><div class="mark-quote"></div>
      ${a.data.comment ? '<div class="mark-comment"></div>' : ''}
      <div class="mark-items">${a.data.status ? `<span class="tag tag-${a.data.status}">${a.data.status === 'unclear' ? 'Not clear yet' : 'Understood'}</span>` : ''}${items.map(it => `<span class="tag tag-${it.kind === 'card' ? 'card' : it.data.type} ${it.data.status === 'done' ? 'done' : ''}">${it.kind === 'card' ? 'Card' : TASK_LABELS[it.data.type]}</span>`).join('')}</div>`;
    li.querySelector('.mark-quote').textContent = a.data.type === 'region' ? (a.data.latex ? '' : 'Region') : snippet(a.data.quote, 160);
    if (a.data.type === 'region' && a.data.latex) li.querySelector('.mark-quote').innerHTML = renderMarkdown(`$${a.data.latex}$`, resolveLink);
    if (a.data.comment) li.querySelector('.mark-comment').textContent = a.data.comment;
    for (const q of items.filter(it => it.kind === 'task' && it.data.type === 'question')) {
      const d = document.createElement('div');
      d.className = 'mark-question';
      d.textContent = 'Q: ' + q.data.text;
      li.querySelector('.mark-items').before(d);
    }
    li.addEventListener('click', () => {
      // On narrow screens the panel covers the page: get out of the way.
      if (NARROW.matches) setPanel(false);
      state.pdf.showAnno(a);
      setTimeout(() => showActions({ kind: 'anno', anno: a }), 450);
    });
    list.appendChild(li);
  }
}

function pointToMarkRow(annoId) {
  const row = document.querySelector(`#panel .mark[data-anno="${CSS.escape(annoId)}"]`);
  if (!row) return;
  document.querySelectorAll('#panel .mark.current').forEach(r => r.classList.remove('current'));
  row.classList.add('current');
  row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

function renderNotePanel(panel) {
  const idx = linkIndex();
  const id = state.noteId;
  const out = idx.outgoing.get(id) || [];
  const back = [...(idx.backlinks.get(id) || [])];
  panel.innerHTML = `<section><h3>Links</h3><div class="panel-out"></div></section>
    <section><h3>Backlinks</h3><div class="panel-back"></div></section>`;
  const outBox = panel.querySelector('.panel-out');
  if (!out.length) outBox.innerHTML = '<p class="muted">Type [[ to link a note or paper.</p>';
  for (const l of out) {
    const a = document.createElement('a');
    a.href = '#';
    a.className = 'chip' + (l.kind === 'missing' ? ' chip-missing' : '');
    if (l.kind === 'anno') {
      const r = resolveLink({ type: 'anno', id: l.id, label: null });
      a.textContent = r.label;
      Object.assign(a.dataset, r.attrs);
    } else if (l.kind === 'missing') {
      a.textContent = l.title + ' (new)';
      Object.assign(a.dataset, { kind: 'new', title: l.title });
    } else {
      a.textContent = l.title;
      Object.assign(a.dataset, { kind: l.kind, id: l.id });
    }
    a.addEventListener('click', e => {
      e.preventDefault();
      openLink(a);
    });
    outBox.appendChild(a);
  }
  const backBox = panel.querySelector('.panel-back');
  if (!back.length) backBox.innerHTML = '<p class="muted">No notes link here yet.</p>';
  for (const nid of back) {
    const n = store.get(nid);
    if (!n) continue;
    const a = document.createElement('a');
    a.className = 'chip';
    a.href = '#note=' + nid;
    a.textContent = noteTitle(n);
    backBox.appendChild(a);
  }
}

// ── Study ──

function sourceLink(it) {
  if (!it.data.annoId || !store.get(it.data.annoId)) {
    const d = it.data.docId && store.get(it.data.docId);
    const page = it.data.source && it.data.source.page;
    return d ? `<a href="#doc=${d.id}${page ? '&p=' + page : ''}" class="source"></a>` : '';
  }
  const a = store.get(it.data.annoId);
  return `<a href="#doc=${a.data.docId}&a=${a.id}" class="source"></a>`;
}

function fillSourceLabels(root, it) {
  const el = root.querySelector('.source');
  if (!el) return;
  const a = it.data.annoId && store.get(it.data.annoId);
  const d = store.get(a ? a.data.docId : it.data.docId);
  const page = a ? a.data.page : it.data.source && it.data.source.page;
  el.textContent = (d ? d.data.title : 'Paper') + (page ? ', p. ' + page : '');
}

function renderStudy() {
  const root = $('#view-study');
  if (state.review) return renderReview(root);
  const now = Date.now();
  const q = studyQueue(store.all(), now);
  const questions = q.open.filter(t => t.data.type === 'question');
  // Explanations still being written, or failed, belong with the others.
  const explaining = q.open.filter(t => t.data.type === 'explain');
  const open = q.open.filter(t => t.data.type !== 'question' && t.data.type !== 'explain');
  const understood = store.all('task')
    .filter(t => t.data.type === 'explain' && t.data.status === 'done' && t.data.explanation)
    .sort((a, b) => b.updatedAt - a.updatedAt);

  root.innerHTML = `
    <div class="study">
      <section class="study-block">
        <h2>Cards</h2>
        <p class="muted cards-line"></p>
        <button class="btn btn-primary" id="start-review" ${q.dueCards.length ? '' : 'disabled'}>Review ${q.dueCards.length} due</button>
      </section>
      <section class="study-block"><h2>Explanations to read <span class="muted">${q.toReview.length + explaining.length}</span></h2>
        <div class="study-list" id="study-ready"></div>
        ${understood.length ? `<details class="study-archive"><summary>Understood (${understood.length})</summary><div class="study-list" id="study-understood"></div></details>` : ''}
      </section>
      <section class="study-block"><h2>Open follow-ups <span class="muted">${open.length}</span></h2><div class="study-list" id="study-open"></div></section>
      <section class="study-block"><h2>Questions for journal club <span class="muted">${questions.length}</span></h2>
        <p class="muted">Each paper's <strong>Brief</strong> (in its toolbar) collects its questions, open points and key equations for presenting.</p>
        <div class="study-list" id="study-questions"></div></section>
    </div>`;
  const allCards = store.all('card');
  const next = allCards.filter(c => c.data.srs.due > now).sort((a, b) => a.data.srs.due - b.data.srs.due)[0];
  root.querySelector('.cards-line').textContent = `${allCards.length} card${allCards.length === 1 ? '' : 's'}, ${q.dueCards.length} due now` +
    (next ? `, next one due ${relativeTime(next.data.srs.due)}` : '');
  root.querySelector('#start-review').addEventListener('click', () => {
    state.review = { queue: q.dueCards.map(c => c.id), index: 0, revealed: false };
    renderStudy();
  });

  const readyBox = root.querySelector('#study-ready');
  if (!q.toReview.length && !explaining.length) readyBox.innerHTML = '<p class="muted">Select a passage and choose Explain to get one.</p>';
  for (const t of q.toReview) readyBox.appendChild(explanationCard(t));
  for (const t of explaining) readyBox.appendChild(taskRow(t));
  const archive = root.querySelector('#study-understood');
  if (archive) for (const t of understood) archive.appendChild(explanationCard(t, true));

  const openBox = root.querySelector('#study-open');
  if (!open.length) openBox.innerHTML = '<p class="muted">Nothing open.</p>';
  for (const t of open) openBox.appendChild(taskRow(t));

  const qBox = root.querySelector('#study-questions');
  if (!questions.length) qBox.innerHTML = '<p class="muted">Mark passages with Question to collect them for discussion.</p>';
  for (const t of questions) qBox.appendChild(taskRow(t));
}

// archived: an explanation already marked understood, kept for rereading.
function focusStudyItem(taskId) {
  const el = document.querySelector(`#view-study [data-task="${CSS.escape(taskId)}"]`);
  if (!el) return;
  const archive = el.closest('details');
  if (archive) archive.open = true;
  el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 1600);
}

function explanationCard(t, archived) {
  const el = document.createElement('article');
  el.dataset.task = t.id;
  el.className = 'explain-card' + (archived ? ' archived' : '');
  const savedNote = t.data.noteId && store.get(t.data.noteId);
  el.innerHTML = `<div class="explain-head"><h3></h3>${sourceLink(t)}</div>
    <div class="explain-body md-view"></div>
    <div class="explain-foot">
      <button class="btn btn-primary" data-act="done">I understand it now</button>
      ${savedNote ? `<a class="chip" href="#note=${savedNote.id}">Saved as note</a>` : '<button class="btn btn-secondary" data-act="note">Save as note</button>'}
      <button class="btn btn-secondary" data-act="card">Make a card</button>
      <button class="btn btn-secondary" data-act="again">Explain again</button>
    </div>`;
  el.querySelector('h3').textContent = t.data.text;
  fillSourceLabels(el, t);
  el.querySelector('.explain-body').innerHTML = renderMarkdown(t.data.explanation || '', resolveLink);
  if (archived) {
    const done = el.querySelector('[data-act="done"]');
    done.dataset.act = 'reopen';
    done.textContent = 'Not clear after all';
    done.className = 'btn btn-secondary';
  }
  if (explainState(t) === 'writing') {
    const again = el.querySelector('[data-act="again"]');
    again.disabled = true;
    again.textContent = 'Writing a new one...';
    el.classList.add('is-writing');
    const body = el.querySelector('.explain-body');
    body.dataset.live = t.id;
    if (liveText.has(t.id)) body.innerHTML = renderMarkdown(liveText.get(t.id), resolveLink);
  }
  el.querySelector('.explain-foot').addEventListener('click', async e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    const a = t.data.annoId && store.get(t.data.annoId);
    try {
      if (act === 'done') {
        await store.update(t.id, { status: 'done' });
        if (a) await store.update(a.id, { status: 'understood' });
      } else if (act === 'reopen') {
        await store.update(t.id, { status: 'ready' });
        if (a) await store.update(a.id, { status: 'unclear' });
      } else if (act === 'note') {
        const title = await promptDialog('Note title', snippet(t.data.text.replace(/^Explain:\s*/, ''), 60));
        if (!title) return;
        const ref = t.data.annoId ? `\n\nSource: [[@${t.data.annoId}]]` : '';
        const note = await store.create('note', { title, blocks: [{ id: newId(), type: 'md', text: t.data.explanation + ref }] });
        // Saving is not understanding: the explanation stays to read.
        await store.update(t.id, { noteId: note.id });
        toast('Saved as a note. The explanation stays here until you mark it understood.');
      } else if (act === 'card') {
        if (!a) throw new Error('The marked passage was deleted');
        await cardDialog({ anno: a, saved: true }, a.data.type === 'region');
      } else if (act === 'again') {
        toast('Writing a new explanation...');
        generateExplanation(t.id);
      }
    } catch (err) {
      reportError('Action failed', err);
    }
  });
  return el;
}

// The passage a task or card is about, for context in lists.
function quoteOf(it) {
  const a = it.data.annoId && store.get(it.data.annoId);
  if (!a) return (it.data.source && it.data.source.quote) || '';
  if (a.data.type === 'region') return a.data.latex ? `$${a.data.latex}$` : '';
  return a.data.quote;
}

function taskRow(t) {
  const el = document.createElement('div');
  el.dataset.task = t.id;
  el.className = 'task-row';
  const quote = quoteOf(t);
  const gen = t.data.type === 'explain' ? explainState(t) : null;
  const genLabel = { idle: 'Generate', failed: 'Retry', interrupted: 'Retry', writing: 'Writing...' }[gen];
  el.innerHTML = `<input type="checkbox" aria-label="Done">
    <span class="tag tag-${t.data.type}">${TASK_LABELS[t.data.type]}</span>
    <span class="task-text md-inline"></span>
    ${sourceLink(t)}
    ${gen ? `<button class="btn-small" data-gen ${gen === 'writing' ? 'disabled' : ''}>${genLabel}</button>` : ''}
    ${quote ? '<blockquote class="task-quote md-inline"></blockquote>' : ''}
    ${gen === 'writing' ? `<div class="md-view live-explain" data-live="${t.id}"><p class="muted">Writing...</p></div>` : ''}
    ${t.data.error || gen === 'interrupted' ? '<span class="task-error"></span>' : ''}`;
  el.querySelector('.task-text').innerHTML = renderMarkdown(t.data.text, resolveLink);
  if (quote) el.querySelector('.task-quote').innerHTML = renderMarkdown(snippet(quote, 400), resolveLink);
  fillSourceLabels(el, t);
  if (liveText.has(t.id)) el.querySelector('[data-live]').innerHTML = renderMarkdown(liveText.get(t.id), resolveLink);
  const err = el.querySelector('.task-error');
  if (err) err.textContent = t.data.error || 'Interrupted before it finished (the page was closed or reloaded).';
  el.querySelector('input').addEventListener('change', () => store.update(t.id, { status: 'done' }).catch(e => reportError('Update failed', e)));
  const genBtn = el.querySelector('[data-gen]');
  if (genBtn) genBtn.addEventListener('click', () => {
    genBtn.disabled = true;
    genBtn.textContent = 'Writing...';
    generateExplanation(t.id);
  });
  return el;
}

function renderReview(root) {
  const r = state.review;
  const id = r.queue[r.index];
  const card = id && store.get(id);
  if (!card) {
    // Stay on this screen (sync events re-render Study only when no review is open).
    r.done = true;
    const now = Date.now();
    const cards = store.all('card');
    const dueNow = cards.filter(c => c.data.srs.due <= now);
    // Cards in their learning steps come back within minutes.
    const soon = cards.filter(c => c.data.srs.due > now && c.data.srs.due - now < 30 * 60 * 1000)
      .sort((a, b) => a.data.srs.due - b.data.srs.due);
    const wait = soon.length ? Math.ceil((soon[0].data.srs.due - now) / 60000) : 0;
    root.innerHTML = `<div class="study"><section class="study-block"><h2>Done for now</h2>
      <p class="review-next"></p>
      <div class="review-actions">
        ${dueNow.length ? `<button class="btn btn-primary" id="review-more">Keep going (${dueNow.length} due)</button>` : ''}
        <button class="btn btn-secondary" id="review-back">Back to Study</button>
      </div></section></div>`;
    const lastWait = soon.length ? Math.ceil((soon[soon.length - 1].data.srs.due - now) / 60000) : 0;
    root.querySelector('.review-next').textContent = dueNow.length
      ? `${dueNow.length} card${dueNow.length === 1 ? '' : 's'} came due again while you reviewed.`
      : soon.length === 1 ? `1 card is due again in ${wait} min.`
      : soon.length ? `${soon.length} cards are due again within ${lastWait} min (the first in ${wait} min).`
      : 'No more cards due.';
    root.querySelector('#review-back').addEventListener('click', () => {
      state.review = null;
      renderStudy();
    });
    const more = root.querySelector('#review-more');
    if (more) more.addEventListener('click', () => {
      state.review = { queue: dueNow.sort((a, b) => a.data.srs.due - b.data.srs.due).map(c => c.id), index: 0, revealed: false };
      renderStudy();
    });
    // Offer to continue as soon as the next learning step comes due.
    if (!dueNow.length && soon.length) {
      clearTimeout(state.reviewTimer);
      state.reviewTimer = setTimeout(() => {
        if (state.view === 'study' && state.review && state.review.done) renderReview(root);
      }, soon[0].data.srs.due - now + 500);
    }
    renderSidebar();
    return;
  }
  // Computed once per card so the labels match what grading saves.
  if (!r.preview || r.previewFor !== card.id) {
    r.preview = previewReview(card.data.srs);
    r.previewFor = card.id;
  }
  const intervals = r.preview.map(p => p.interval);
  root.innerHTML = `
    <div class="review">
      <div class="review-progress">${r.index + 1} / ${r.queue.length} <button class="btn-small" id="review-stop">Stop</button></div>
      <div class="review-card">
        <div class="review-front md-view"></div>
        ${r.revealed ? '<hr><div class="review-back md-view"></div>' : ''}
        <div class="review-source">${sourceLink(card)}</div>
      </div>
      <div class="review-actions">
        ${r.revealed
          ? GRADES.map((g, i) => `<button class="btn grade grade-${g.label.toLowerCase()}" data-grade="${i}">${g.label}<small>${intervals[i]}</small></button>`).join('')
          : '<button class="btn btn-primary" id="reveal">Show answer <small>(space)</small></button>'}
      </div>
    </div>`;
  root.querySelector('.review-front').innerHTML = renderMarkdown(card.data.front, resolveLink);
  if (r.revealed) root.querySelector('.review-back').innerHTML = renderMarkdown(card.data.back, resolveLink);
  fillSourceLabels(root, card);
  root.querySelector('#review-stop').addEventListener('click', () => {
    state.review = null;
    renderStudy();
  });
  const reveal = root.querySelector('#reveal');
  if (reveal) reveal.addEventListener('click', () => { r.revealed = true; renderReview(root); });
  root.querySelectorAll('[data-grade]').forEach(b => b.addEventListener('click', () => grade(+b.dataset.grade)));
}

async function grade(i) {
  const r = state.review;
  // A double click or a repeated key must grade the card once, not skip the next.
  if (!r || r.grading || !r.revealed) return;
  r.grading = true;
  const card = store.get(r.queue[r.index]);
  try {
    await store.update(card.id, { srs: r.preview[i].srs });
    r.index += 1;
    r.revealed = false;
  } catch (e) {
    reportError('Saving the review failed', e);
  } finally {
    r.grading = false;
  }
  renderStudy();
}

// ── Brief (journal club handout) ──

// One paper's study material as Markdown: questions, what is still unclear,
// key equations, open follow-ups, comments and the paper notebook. The same
// text is rendered, printed and copied, so all three always agree.
function briefMarkdown(docId) {
  const doc = store.get(docId);
  const annos = store.forDoc(docId, 'anno').sort((a, b) => a.data.page - b.data.page || a.data.rects[0][1] - b.data.rects[0][1]);
  const tasks = store.all('task').filter(t => t.data.docId === docId);
  const cards = store.all('card').filter(c => c.data.docId === docId);
  const ref = a => `[[@${a.id}|p. ${a.data.page}]]`;
  const quoteLine = a => (a.data.type === 'region'
    ? (a.data.latex ? `$$${a.data.latex}$$` : `*(region)*`)
    : `> ${a.data.quote.replace(/\n/g, ' ')}`);
  const out = [`# ${doc.data.title}`];
  if (doc.data.authors) out.push(`*${doc.data.authors}*`);

  const questions = tasks.filter(t => t.data.type === 'question' && t.data.status !== 'done');
  out.push('', `## Questions for discussion (${questions.length})`);
  if (!questions.length) out.push('None yet: mark passages with **Question** while reading.');
  for (const t of questions) {
    const a = t.data.annoId && store.get(t.data.annoId);
    out.push('', `- **${t.data.text}**` + (a ? ` ${ref(a)}` : ''));
    if (a && a.data.type !== 'region') out.push(`  > ${snippet(a.data.quote, 300)}`);
  }

  const unclear = annos.filter(a => a.data.status === 'unclear');
  out.push('', `## Not clear yet (${unclear.length})`);
  if (!unclear.length) out.push('Nothing marked as unclear.');
  for (const a of unclear) {
    const ex = tasks.find(t => t.data.type === 'explain' && t.data.annoId === a.id);
    const exState = !ex ? 'no explanation yet'
      : ex.data.status === 'ready' ? 'explanation ready to read in Study'
      : ex.data.status === 'done' ? 'explained'
      : ex.data.error || explainState(ex) === 'interrupted' ? 'explanation failed: retry it in Study'
      : 'explanation being written';
    out.push('', `- ${ref(a)} *(${exState})*`, `  ${quoteLine(a).replace(/\n/g, ' ')}`);
    const gist = ex && ex.data.explanation && plainGist(ex.data.explanation);
    if (gist) out.push(`  **In short:** ${gist}`);
  }

  const equations = annos.filter(a => a.data.type === 'region' && (a.data.latex || a.data.brief));
  out.push('', `## Key equations (${equations.length})`);
  if (!equations.length) out.push('Use the Region tool on an equation and choose Equation card or LaTeX to notebook.');
  for (const a of equations) {
    const n = cards.filter(c => c.data.annoId === a.id).length;
    out.push('', a.data.latex ? `$$${a.data.latex}$$` : '*(equation region; LaTeX not read yet)*', `${ref(a)}${n ? ` - ${n} card${n > 1 ? 's' : ''}` : ''}${a.data.status === 'understood' ? ' - understood' : a.data.status === 'unclear' ? ' - not clear yet' : ''}`);
  }

  const open = tasks.filter(t => t.data.type !== 'question' && t.data.type !== 'explain' && t.data.status !== 'done');
  out.push('', `## Open follow-ups (${open.length})`);
  if (!open.length) out.push('Nothing open.');
  for (const t of open) {
    const a = t.data.annoId && store.get(t.data.annoId);
    out.push(`- [ ] ${TASK_LABELS[t.data.type]}: ${t.data.text.replace(/^Explain:\s*/, '')}` + (a ? ` ${ref(a)}` : ''));
  }

  const pinned = annos.filter(a => a.data.brief && a.data.type !== 'region');
  if (pinned.length) {
    out.push('', `## Key passages (${pinned.length})`);
    for (const a of pinned) out.push('', `- ${ref(a)}${a.data.comment ? ' ' + a.data.comment : ''}`, `  > ${snippet(a.data.quote, 400)}`);
  }

  const explained = tasks.filter(t => t.data.type === 'explain' && t.data.status === 'done' && t.data.explanation);
  if (explained.length) {
    out.push('', `## Explained (${explained.length})`);
    for (const t of explained) {
      const a = t.data.annoId && store.get(t.data.annoId);
      out.push('', `- ${a ? ref(a) + ' ' : ''}**${t.data.text.replace(/^Explain:\s*/, '')}**`, `  ${plainGist(t.data.explanation)}`);
    }
  }

  const commented = annos.filter(a => a.data.comment);
  if (commented.length) {
    out.push('', `## Comments (${commented.length})`);
    for (const a of commented) out.push('', `- ${ref(a)} ${a.data.comment}`, `  ${quoteLine(a).replace(/\n/g, ' ')}`);
  }

  const linkedNotes = [...notesForDoc(linkIndex(), store.all(), docId)].map(id => store.get(id))
    .filter(n => n && !n.data.notebookFor);
  if (linkedNotes.length) {
    out.push('', `## Linked notes (${linkedNotes.length})`);
    for (const n of linkedNotes) out.push(`- [[${noteTitle(n)}]]`);
  }

  const nb = paperNotebook(docId);
  const nbText = nb ? nb.data.blocks.filter(b => b.type === 'md')
    .map(b => b.text.trim().replace(/^(#{1,5}) /gm, '#$1 ')).filter(Boolean) : [];
  if (nbText.length) out.push('', '## From the notebook', '', nbText.join('\n\n'));

  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  out.push('', `---`, `${plural(cards.length, 'card')}, ${plural(annos.length, 'mark')}.`);
  return out.join('\n');
}

// The "In plain terms" part of an explanation, as one line of text.
function plainGist(md) {
  const m = md.match(/in plain terms\**\s*[-:\u2013\u2014]?\s*([\s\S]*?)(?:\n\s*\n|\n\s*\d+\.|$)/i);
  // Underscores stay: they are subscripts inside $...$ math.
  const text = (m ? m[1] : md).replace(/\$\$[\s\S]*?\$\$/g, '').replace(/[*#>`]/g, '').replace(/\s+/g, ' ').trim();
  return snippet(text, 240);
}

// Wikilinks for use outside the app: passages become web links that open
// the reader at the mark; note and paper links become their titles.
function plainLinks(md) {
  const base = location.origin + location.pathname;
  return md.replace(WIKILINK, (m, target, label) => {
    if (!target.startsWith('@')) return label || target;
    const a = store.get(target.slice(1));
    if (!a) return label || '';
    return `[${label || 'p. ' + a.data.page}](${base}#doc=${a.data.docId}&a=${a.id})`;
  });
}

function renderBrief(docId) {
  const doc = store.get(docId);
  $('#view-title').textContent = 'Brief: ' + doc.data.title;
  const root = $('#view-brief');
  const md = briefMarkdown(docId);
  root.innerHTML = `<div class="brief">
      <div class="brief-actions">
        <a class="btn btn-secondary" href="#doc=${docId}">Back to paper</a>
        <button class="btn btn-secondary" id="brief-copy">Copy as Markdown</button>
        <button class="btn btn-primary" id="brief-print">Print</button>
      </div>
      <article class="brief-body md-view"></article>
    </div>`;
  root.querySelector('.brief-body').innerHTML = renderMarkdown(md, resolveLink);
  root.querySelector('.brief-body').addEventListener('click', e => {
    const link = e.target.closest('a.wl');
    if (!link) return;
    e.preventDefault();
    openLink(link);
  });
  root.querySelector('#brief-print').addEventListener('click', () => print());
  root.querySelector('#brief-copy').addEventListener('click', async () => {
    try {
      // Wikilinks mean nothing outside the app: copy their labels as text.
      await navigator.clipboard.writeText(plainLinks(md));
      toast('Brief copied as Markdown');
    } catch (e) {
      reportError('Copy failed', e);
    }
  });
}

// ── Store events ──

let refreshQueued = false;
store.addEventListener('change', e => {
  state.links = null;
  if (refreshQueued) return;
  refreshQueued = true;
  requestAnimationFrame(() => {
    refreshQueued = false;
    renderSidebar();
    if (state.view === 'doc') {
      refreshDocOverlays();
      if (state.panelMode !== 'contents') renderPanel();
      if (!$('#doc-notebook').contains(document.activeElement)) sideEditor.refreshFromStore();
    } else if (state.view === 'note') {
      mainEditor.refreshFromStore();
      if (mainEditor.draft) $('#view-title').textContent = mainEditor.draft.title || 'Untitled';
      renderPanel();
    } else if (state.view === 'study' && !state.review) {
      renderStudy();
    } else if (state.view === 'brief') {
      const r = parseHash();
      if (store.get(r.id)) renderBrief(r.id);
    }
    if (lastQuery) search(lastQuery);
  });
  if (e.detail.remote && state.view === 'empty') route();
});

const SYNC_SHORT = { synced: 'Synced', syncing: 'Syncing', offline: 'Offline', error: 'Sync error', local: 'This device', 'signed-out': 'Signed out' };
store.addEventListener('status', e => {
  const el = $('#sync-status');
  el.innerHTML = '<span class="sync-long"></span><span class="sync-short"></span>';
  el.querySelector('.sync-long').textContent = e.detail.message;
  el.querySelector('.sync-short').textContent = SYNC_SHORT[e.detail.state] || e.detail.state;
  el.title = e.detail.message;
  el.dataset.state = e.detail.state;
});

// ── Wiring ──

function wire() {
  $('#sidebar-toggle').addEventListener('click', () => setSidebar(document.body.classList.contains('sidebar-closed')));
  // Tapping the item that is already open changes no URL, so no navigation
  // runs: close the library on narrow screens on any link tap.
  $('#sidebar').addEventListener('click', e => {
    if (NARROW.matches && e.target.closest('a[href^="#"], #open-study')) setSidebar(false);
  });
  $('#search').addEventListener('input', e => {
    lastQuery = e.target.value;
    search(lastQuery);
  });
  $('#open-study').addEventListener('click', () => navigate('#study'));
  $('#file-input').addEventListener('change', e => {
    importFiles([...e.target.files]);
    e.target.value = '';
  });
  $('#new-note').addEventListener('click', newNote);
  $('#delete-note').addEventListener('click', async () => {
    const n = store.get(state.noteId);
    if (n && !confirm(`Delete "${noteTitle(n)}"?`)) return;
    mainEditor.close();
    if (n) await store.remove(n.id);
    navigate('#');
  });

  document.querySelectorAll('.tool[data-tool]').forEach(b => b.addEventListener('click', () => setTool(b.dataset.tool)));
  $('#zoom-in').addEventListener('click', () => state.pdf && state.pdf.setZoom(state.pdf.zoom * 1.2, state.pdf.fitWidth));
  $('#zoom-out').addEventListener('click', () => state.pdf && state.pdf.setZoom(state.pdf.zoom / 1.2, state.pdf.fitWidth));
  $('#zoom-fit').addEventListener('click', () => state.pdf && state.pdf.setZoom(1, true));
  $('#page-input').addEventListener('change', e => state.pdf && state.pdf.goTo(+e.target.value));
  document.querySelectorAll('[data-history]').forEach(b => b.addEventListener('click', () => (b.dataset.history === 'undo' ? undo() : redo())));
  $('#clear-page').addEventListener('click', async () => {
    if (!state.pdf) return;
    const page = state.pdf.currentPage;
    const ink = store.get(inkId(state.docId, page));
    if (!ink || !ink.data.strokes.length) {
      toast(`No ink on page ${page}`);
      return;
    }
    await inkErased(state.docId, page, ink.data.strokes.map(s => s.id), 'Clear ink');
    toast(`Cleared ink on page ${page}: Undo brings it back`);
  });
  // Two-finger tap undoes, three-finger tap redoes (as in GoodNotes and
  // Notability). A tap is short and does not move; pinches and scrolls do.
  let tap = null;
  document.addEventListener('touchstart', e => {
    if (!e.target.closest('#view-doc, #view-note') || e.target.closest('input, textarea, button')) {
      tap = null;
      return;
    }
    const now = Date.now();
    if (!tap || now - tap.start > 300) tap = { start: now, max: 0, moved: false, pts: new Map() };
    for (const t of e.changedTouches) tap.pts.set(t.identifier, [t.clientX, t.clientY]);
    tap.max = Math.max(tap.max, e.touches.length);
  }, { passive: true });
  document.addEventListener('touchmove', e => {
    if (!tap) return;
    for (const t of e.changedTouches) {
      const p = tap.pts.get(t.identifier);
      if (p && Math.hypot(t.clientX - p[0], t.clientY - p[1]) > 12) tap.moved = true;
    }
  }, { passive: true });
  document.addEventListener('touchend', e => {
    if (!tap || e.touches.length) return;
    const t = tap;
    tap = null;
    if (t.moved || Date.now() - t.start > 350) return;
    if (t.max === 2) undo();
    else if (t.max === 3) redo();
  }, { passive: true });

  wireSplitHandle();
  $('#toggle-panel').addEventListener('click', () => togglePanel('marks'));
  $('#toggle-contents').addEventListener('click', () => togglePanel('contents'));
  $('#toggle-note-panel').addEventListener('click', () => setPanel(!state.panelOpen));
  $('#open-brief').addEventListener('click', () => state.docId && navigate('#brief=' + state.docId));
  // Close the color menus on any outside tap.
  document.addEventListener('click', () => {
    document.querySelectorAll('.swatch-menu:not(.hidden)').forEach(m => m.classList.add('hidden'));
  });
  $('#toggle-notebook').addEventListener('click', () => {
    state.notebookOpen = !state.notebookOpen;
    localStorage.setItem('reader.notebook', state.notebookOpen ? '1' : '0');
    applyNotebook().catch(e => reportError('Notebook failed', e));
  });

  // Text selection -> action bar. Debounced: selectionchange fires per character.
  let selTimer = null;
  document.addEventListener('selectionchange', () => {
    clearTimeout(selTimer);
    selTimer = setTimeout(() => {
      if (state.view !== 'doc') return;
      const t = currentSelectionTarget();
      if (t) showActions(t);
      else if (state.target && state.target.kind === 'selection') hideActions();
    }, 250);
  });

  // Tap on a mark -> its actions. Clicks that end a pen stroke do not count.
  let lastPointer = 'mouse';
  $('#pdf-scroll').addEventListener('pointerdown', e => { lastPointer = e.pointerType; }, true);
  $('#pdf-scroll').addEventListener('click', e => {
    if (!state.pdf || !window.getSelection().isCollapsed) return;
    const drawing = lastPointer !== 'touch' && state.tool.tool !== 'select';
    const a = drawing ? null : state.pdf.annoAt(e.clientX, e.clientY);
    // Working through marks: a tapped mark is found in the open Marks panel;
    // a tap elsewhere puts a portrait panel away.
    if (a && state.panelOpen && state.panelMode === 'marks') pointToMarkRow(a.id);
    else if (NARROW.matches && state.panelOpen) setPanel(false);
    if (drawing) return;
    if (a) showActions({ kind: 'anno', anno: store.get(a.id), anchor: { left: e.clientX, top: e.clientY, bottom: e.clientY, width: 0 } });
    else if (state.target) hideActions();
  });
  $('#pdf-scroll').addEventListener('scroll', () => {
    if (state.target && state.target.kind !== 'selection') hideActions();
  }, { passive: true });

  // Drag and drop PDFs anywhere.
  let dragDepth = 0;
  addEventListener('dragenter', e => {
    if (![...e.dataTransfer.types].includes('Files')) return;
    dragDepth++;
    $('#drop-overlay').classList.remove('hidden');
  });
  addEventListener('dragleave', () => {
    if (--dragDepth <= 0) $('#drop-overlay').classList.add('hidden');
  });
  addEventListener('dragover', e => e.preventDefault());
  addEventListener('drop', e => {
    e.preventDefault();
    dragDepth = 0;
    $('#drop-overlay').classList.add('hidden');
    if (e.dataTransfer.files.length) importFiles([...e.dataTransfer.files]);
  });

  addEventListener('keydown', e => {
    if (e.target.closest('input, textarea, [contenteditable], dialog')) return;
    if ((e.metaKey || e.ctrlKey) && e.key === 'f' && state.view === 'doc') {
      e.preventDefault();
      setPanel(true, 'contents');
      setTimeout(() => {
        const box = document.querySelector('#panel .find-box');
        if (box) {
          box.focus();
          box.select();
        }
      }, 50);
      return;
    }
    // Text fields keep their own undo; everywhere else Cmd/Ctrl+Z is ours.
    if ((e.metaKey || e.ctrlKey) && (e.key === 'z' || e.key === 'Z' || e.key === 'y')) {
      e.preventDefault();
      if (e.key === 'y' || e.shiftKey) redo();
      else undo();
      return;
    }
    if (state.review && state.view === 'study') {
      if (e.key === ' ' && !state.review.revealed) {
        e.preventDefault();
        state.review.revealed = true;
        renderStudy();
      } else if (state.review.revealed && GRADES.some(g => g.key === e.key)) {
        grade(GRADES.findIndex(g => g.key === e.key));
      }
      return;
    }
    const keys = { s: 'select', p: 'pen', h: 'highlighter', e: 'eraser', r: 'region' };
    if (state.view === 'doc' && keys[e.key] && !e.metaKey && !e.ctrlKey) setTool(keys[e.key]);
    if (e.key === 'Escape') {
      if (state.target) hideActions();
      else if (state.panelOpen && NARROW.matches) setPanel(false);
    }
  });

  $('#guest-adopt').addEventListener('click', async () => {
    try {
      const n = await store.adoptGuest();
      $('#guest-banner').classList.add('hidden');
      toast(`Moved ${n} items into your account`);
    } catch (e) {
      reportError('Moving device-only items failed', e);
    }
  });

  addEventListener('hashchange', () => route().catch(e => reportError('Navigation failed', e)));
  // Rotation: the panel's position depends on portrait or landscape.
  NARROW.addEventListener('change', () => renderPanel());
  const flushEditors = () => {
    mainEditor.flush();
    sideEditor.flush();
  };
  addEventListener('pagehide', flushEditors);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushEditors();
  });
}

let vaultOpening = Promise.resolve();
function openVault(user) {
  // The previous failure was already reported; do not let it block this open.
  vaultOpening = vaultOpening.catch(() => {}).then(() => openVaultNow(user));
  return vaultOpening;
}

async function openVaultNow(user) {
  const accountId = user ? user.id : null;
  if (store.db && store.accountId === accountId) return;
  mainEditor.close();
  sideEditor.close();
  closeDoc();
  await store.open(accountId);
  purgeExpiredTrash();
  // Opening the reader with no route resumes where you left off.
  if (!location.hash || location.hash === '#') {
    const last = localStorage.getItem('reader.last');
    const r = last && new URLSearchParams(last.slice(1));
    const id = r && (r.get('doc') || r.get('note'));
    if (id && store.get(id)) history.replaceState(null, '', last);
  }
  if (accountId) {
    const n = await store.guestItemCount();
    $('#guest-banner').classList.toggle('hidden', n === 0);
    $('#guest-banner-text').textContent = `${n} items were saved on this device while signed out.`;
  } else {
    $('#guest-banner').classList.add('hidden');
  }
  await route();
}

function init() {
  wire();
  setTool(state.tool.tool);
  if (matchMedia('(max-width: 900px)').matches) setSidebar(false);
  C.initSettingsModal();
  window.WhyAuth.onReady(() => openVault(window.WhyAuth.getUser()).catch(e => reportError('Opening the vault failed', e)));
  document.addEventListener('whyauth:change', e => openVault(e.detail.user).catch(err => reportError('Opening the vault failed', err)));
  window.WhyAuth.init();
}

init();
