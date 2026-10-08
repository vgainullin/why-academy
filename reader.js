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
} from './lib/vault/model.js';
import { PdfView, readPdfInfo } from './lib/vault/pdf-view.js';
import { NoteEditor, noteBackup } from './lib/vault/notes.js';
import { renderMarkdown } from './lib/vault/markdown.js';
import { INK_COLORS, HIGHLIGHT_COLORS } from './lib/vault/ink.js';
import { explainPassage, equationToLatex, draftCard } from './lib/vault/ai.js';
import { newSrs, previewReview, GRADES } from './lib/vault/srs.js';

const $ = sel => document.querySelector(sel);
const C = window.WhyCommon;

const PEN_WIDTHS = { pen: 0.0028, highlighter: 0.016 };
const TASK_LABELS = { todo: 'Follow-up', explain: 'Explain', derive: 'Derive', question: 'Question' };
const COLOR_NAMES = {
  '#1f2937': 'Black', '#2563eb': 'Blue', '#dc2626': 'Red', '#059669': 'Green',
  '#fde047': 'Yellow', '#86efac': 'Green', '#f9a8d4': 'Pink', '#93c5fd': 'Blue',
};
const NARROW = matchMedia('(max-width: 900px)');

const store = new VaultStore();
const state = {
  view: 'empty',
  docId: null,
  noteId: null,
  pdf: null,
  tool: { tool: matchMedia('(pointer: coarse)').matches ? 'pen' : 'select', color: INK_COLORS[0], hlColor: HIGHLIGHT_COLORS[0] },
  links: null,
  // On narrow screens the panel covers the page, so it never reopens by itself.
  panelOpen: localStorage.getItem('reader.panel') === '1' && !NARROW.matches,
  notebookOpen: localStorage.getItem('reader.notebook') === '1',
  target: null, // current action target: { kind: 'selection'|'region'|'anno', ... }
  review: null, // { queue: [ids], index, revealed, done }
  panelFilter: 'all', // marks panel: 'all' | 'unclear'
};

// Notes made with "New note" stay here until their first edit, so an
// abandoned new note never reaches the vault.
const pendingNotes = new Map();

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// A note without a title is shown by its first line of text.
function noteTitle(n) {
  if (n.data.title && n.data.title.trim()) return n.data.title;
  const md = (n.data.blocks || []).find(b => b.type === 'md' && b.text.trim());
  if (!md) return 'Untitled';
  return snippet(md.text.trim().split('\n')[0].replace(/^[#>*\-\s]+|\[\[|\]\]/g, ''), 50) || 'Untitled';
}

function snippet(s, n = 120) {
  s = String(s || '').replace(/\s+/g, ' ').trim();
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
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
  return { tool: t.tool, color: isHl ? t.hlColor : t.color, width: PEN_WIDTHS[isHl ? 'highlighter' : 'pen'] };
}

// Notebook ink pads always take the Pencil: Select and Region are reading
// tools and mean nothing on a pad.
function getInkTool() {
  const t = getTool();
  if (t.tool === 'select' || t.tool === 'region') return { tool: 'pen', color: state.tool.color, width: PEN_WIDTHS.pen };
  return t;
}

function setTool(tool) {
  state.tool.tool = tool;
  document.querySelectorAll('.tool[data-tool]').forEach(b => {
    b.classList.toggle('active', b.dataset.tool === tool);
    b.setAttribute('aria-pressed', String(b.dataset.tool === tool));
  });
  document.body.dataset.tool = tool;
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
    btn.title = (isHl ? 'Highlighter' : 'Ink') + ' color: ' + COLOR_NAMES[current];
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
  if (h.has('doc')) return { view: 'doc', id: h.get('doc'), page: +h.get('p') || null, anno: h.get('a') };
  if (h.has('note')) return { view: 'note', id: h.get('note') };
  if (h.has('brief')) return { view: 'brief', id: h.get('brief') };
  if (h.has('study')) return { view: 'study' };
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
  const exists = id => store.get(id) || pendingNotes.has(id) || noteBackup(id);
  if ((r.view === 'doc' || r.view === 'note' || r.view === 'brief') && !exists(r.id)) {
    toast(r.view === 'note' ? 'That note was empty or has been deleted' : 'That paper is not in your library', r.view !== 'note');
    const last = localStorage.getItem('reader.last');
    const lr = last && new URLSearchParams(last.slice(1));
    const lastId = lr && (lr.get('doc') || lr.get('note'));
    history.replaceState(null, '', lastId && store.get(lastId) ? last : location.pathname);
    return route();
  }
  // In portrait the panel covers the page, so it does not follow you around.
  if (NARROW.matches && state.panelOpen) state.panelOpen = false;
  if (r.view === 'doc' && store.get(r.id)) {
    await openDoc(r.id, r.page, r.anno);
  } else if (r.view === 'note' && exists(r.id)) {
    openNoteView(r.id);
  } else if (r.view === 'brief' && store.get(r.id)) {
    showView('brief');
    renderBrief(r.id);
  } else if (r.view === 'study') {
    showView('study');
    if (state.review && state.review.done) state.review = null;
    renderStudy();
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
  const docs = store.all('doc').sort((a, b) => b.updatedAt - a.updatedAt);
  const notes = store.all('note').sort((a, b) => b.updatedAt - a.updatedAt);

  const docList = $('#doc-list');
  docList.innerHTML = '';
  if (!docs.length) docList.innerHTML = '<li class="side-empty">No papers yet</li>';
  for (const d of docs) {
    const li = document.createElement('li');
    const marks = store.forDoc(d.id, 'anno').length;
    li.innerHTML = `<a href="#doc=${d.id}" class="side-item${state.docId === d.id ? ' active' : ''}">
      <span class="side-item-title"></span><span class="side-item-meta">${d.data.pages} pp${marks ? ' &middot; ' + marks + ' marks' : ''}</span></a>`;
    li.querySelector('.side-item-title').textContent = d.data.title;
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
  for (const it of store.all()) {
    let text = '', label = '', href = '';
    if (it.kind === 'doc') { text = it.data.title + ' ' + (it.data.authors || ''); label = 'Paper'; href = '#doc=' + it.id; }
    else if (it.kind === 'note') { text = it.data.title + '\n' + noteText(it); label = 'Note'; href = '#note=' + it.id; }
    else if (it.kind === 'anno') { text = it.data.quote + ' ' + (it.data.comment || ''); label = 'p. ' + it.data.page; href = `#doc=${it.data.docId}&a=${it.id}`; }
    else if (it.kind === 'card') { text = it.data.front + ' ' + it.data.back; label = 'Card'; href = markHref(it) || '#study'; }
    else if (it.kind === 'task') { text = it.data.text + ' ' + (it.data.explanation || ''); label = TASK_LABELS[it.data.type]; href = markHref(it) || '#study'; }
    else continue;
    const at = text.toLowerCase().indexOf(q);
    if (at < 0) continue;
    let from = Math.max(0, at - 30);
    while (from > 0 && /\S/.test(text[from - 1])) from--;
    const title = it.kind === 'doc' ? it.data.title : it.kind === 'note' ? noteTitle(it) : (from > 0 ? '\u2026' : '') + snippet(text.slice(from), 90);
    hits.push({ label, href, title, rank: it.kind === 'doc' || it.kind === 'note' ? 0 : 1 });
  }
  hits.sort((a, b) => a.rank - b.rank);
  box.innerHTML = hits.length ? '' : '<div class="side-empty">No matches</div>';
  for (const h of hits.slice(0, 40)) {
    const a = document.createElement('a');
    a.className = 'search-hit';
    a.href = h.href;
    a.innerHTML = '<span class="search-kind"></span><span class="search-title"></span>';
    a.querySelector('.search-kind').textContent = h.label;
    a.querySelector('.search-title').textContent = h.title;
    box.appendChild(a);
  }
  box.classList.remove('hidden');
}

// Link to the passage a card or task came from, if it still exists.
function markHref(it) {
  const a = it.data.annoId && store.get(it.data.annoId);
  return a ? `#doc=${a.data.docId}&a=${a.id}` : null;
}

// ── Links between notes, papers and passages ──

function linkIndex() {
  if (!state.links) state.links = buildLinkIndex(store.all());
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
    ...store.all('doc').map(d => ({ title: d.data.title, kind: 'paper' })),
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

const editorApp = { store, getTool: getInkTool, resolveLink, openLink, titles, toast, renderNoteLinks };
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
      const bytes = new Uint8Array(await file.arrayBuffer());
      const id = await store.addFile(bytes);
      if (!store.get(id)) {
        const meta = await readPdfInfo(bytes);
        const fallback = file.name.replace(/\.pdf$/i, '').replace(/[_-]+/g, ' ');
        const title = meta.title && meta.title.length > 3 && !/^untitled|\.(docx?|tex|dvi)$/i.test(meta.title) ? meta.title : fallback;
        await store.put('doc', id, { title, filename: file.name, pages: meta.pages, size: bytes.length, authors: meta.authors || undefined });
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

async function openDoc(docId, page, annoId) {
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
      onInkAdd: (p, stroke) => saveInk(docId, p, d => d.strokes.push(stroke)),
      onInkErase: (p, ids) => saveInk(docId, p, d => {
        const gone = new Set(ids);
        d.strokes = d.strokes.filter(s => !gone.has(s.id));
        d.erased.push(...ids);
      }),
      onRegion: (p, rect) => showActions({ kind: 'region', page: p, rects: [rect] }),
    });
    state.pdf = view;
    const n = await view.load(bytes);
    $('#page-count').textContent = '/ ' + n;
    $('#page-input').max = n;
    if (doc.data.pages !== n) store.update(docId, { pages: n });
    view.addEventListener('page', e => {
      $('#page-input').value = e.detail;
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
    refreshDocOverlays();
    const localPage = +localStorage.getItem('reader.page.' + docId) || 0;
    view.goTo(page || localPage || doc.data.lastPage || 1, 0, 'instant');
    applyNotebook();
  } else if (page) {
    state.pdf.goTo(page);
  }
  if (annoId) {
    const a = store.get(annoId);
    if (a) state.pdf.showAnno(a);
  }
  renderPanel();
}

function refreshDocOverlays() {
  if (!state.pdf) return;
  const annos = store.forDoc(state.docId, 'anno').map(a => {
    const linked = store.all().filter(it => (it.kind === 'card' || it.kind === 'task') && it.data.annoId === a.id);
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

// ── Paper notebook (split view) ──

function paperNotebook(docId) {
  return store.all('note').find(n => n.data.notebookFor === docId);
}

async function ensurePaperNotebook(docId) {
  const existing = paperNotebook(docId);
  if (existing) return existing;
  const doc = store.get(docId);
  return store.create('note', {
    title: 'Notes: ' + doc.data.title,
    notebookFor: docId,
    blocks: [{ id: newId(), type: 'md', text: `Reading [[${doc.data.title}]]\n` }],
  });
}

async function applyNotebook() {
  const pane = $('#doc-notebook');
  pane.classList.toggle('hidden', !state.notebookOpen);
  $('#toggle-notebook').classList.toggle('active', state.notebookOpen);
  if (!state.docId) return;
  if (state.notebookOpen) {
    const note = await ensurePaperNotebook(state.docId);
    if (sideEditor.noteId !== note.id) sideEditor.open(note.id);
  } else {
    sideEditor.close();
  }
  if (state.pdf) state.pdf.layout();
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
  const quote = sel.toString().replace(/\s+/g, ' ').trim();
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
  selection: ['highlight', 'comment', 'notebook', 'card', 'explain', 'unclear', 'todo', 'question', 'link'],
  region: ['eqcard', 'latex', 'explain', 'unclear', 'comment', 'todo', 'question', 'derive', 'link'],
  anno: ['readexp', 'comment', 'notebook', 'card', 'explain', 'unclear', 'understood', 'todo', 'question', 'link', 'delete'],
};
const ACTION_LABELS = {
  highlight: 'Highlight', comment: 'Comment', notebook: 'To notebook', card: 'Card', explain: 'Explain',
  todo: 'Follow-up', question: 'Question', link: 'Copy link', eqcard: 'Equation card', latex: 'LaTeX to notebook',
  derive: 'Re-derive', delete: 'Delete', unclear: 'Not clear yet', understood: 'Understood', readexp: 'Read explanation',
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
    if (Object.keys(patch).length) await store.update(p.anno.id, patch);
    return store.get(p.anno.id);
  }
  p.anno = await store.put('anno', p.anno.id, { ...p.anno.data, ...patch });
  p.saved = true;
  window.getSelection().removeAllRanges();
  return p.anno;
}

function docTitle() {
  const d = store.get(state.docId);
  return d ? d.data.title : '';
}

async function runAction(act) {
  const target = state.target;
  if (!target) return;
  const page = target.page || (target.anno && target.anno.data.page);
  const isRegion = target.kind === 'region' || (target.anno && target.anno.data.type === 'region');

  if (act === 'delete') {
    const a = target.anno;
    const linked = store.all().filter(it => (it.kind === 'card' || it.kind === 'task') && it.data.annoId === a.id);
    if (linked.length && !confirm(`Delete this mark? Its ${linked.length} card(s)/task(s) are kept.`)) return;
    await store.remove(a.id);
    hideActions();
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

  if (act === 'highlight') {
    await commitAnno(p);
  } else if (act === 'unclear' || act === 'understood') {
    await commitAnno(p, { status: act });
    toast(act === 'unclear' ? 'Marked as not clear yet: it is listed in the Brief and the Marks panel' : 'Marked as understood');
  } else if (act === 'comment') {
    const text = await promptDialog('Comment', p.anno.data.comment || '', { multiline: true, placeholder: 'Margin note for this passage', context: quote });
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
    await store.create('task', { text: `Re-derive: $${latex}$`, type: 'derive', status: 'open', docId: state.docId, annoId: anno.id });
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
      await store.create('task', { text, type: act, status: 'open', docId: state.docId, annoId: anno.id });
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
  if (!anno.data.status) await store.update(anno.id, { status: 'unclear' });
  const task = await store.create('task', {
    text: 'Explain: ' + (isRegion ? `region on p. ${anno.data.page}` : snippet(anno.data.quote, 100)),
    type: 'explain',
    status: 'open',
    docId,
    annoId: anno.id,
  });
  toast('Writing an explanation. It will appear in Study.');
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

function explainState(task) {
  if (explaining.has(task.id)) return 'writing';
  if (task.data.error) return 'failed';
  if (task.data.pending && Date.now() - task.data.pending > EXPLAIN_STALE_MS) return 'interrupted';
  if (task.data.pending) return 'writing';
  return 'idle';
}

async function generateExplanation(taskId) {
  if (explaining.has(taskId)) return;
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
    const explanation = await explainPassage({ docTitle: doc ? doc.data.title : '', quote: anno.data.quote || anno.data.latex, context, image });
    await store.update(taskId, { explanation, status: 'ready', pending: undefined, error: undefined });
    toast('Explanation ready in Study');
  } catch (e) {
    console.error('Explanation failed', e);
    if (store.get(taskId)) await store.update(taskId, { error: e.message, pending: undefined });
    toast('Explanation failed: ' + e.message, true);
  } finally {
    explaining.delete(taskId);
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
      <p class="dialog-status" role="status"></p>
      <label>Front <textarea name="front" rows="3" placeholder="A precise question"></textarea></label>
      <div class="card-preview" data-for="front"></div>
      <label>Back <textarea name="back" rows="4" placeholder="Answer, with $math$"></textarea></label>
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
  front.addEventListener('input', preview);
  back.addEventListener('input', preview);

  let latex = anno.data.latex || '';
  back.value = latex ? `$$${latex}$$` : anno.data.quote;
  preview();

  const draft = async () => {
    status.classList.remove('error');
    status.textContent = 'Drafting...';
    try {
      if (fromEquation && !latex) {
        status.textContent = 'Reading the equation...';
        latex = await equationToLatex(await withPaper(anno.data.docId, v => v.regionImage(anno.data.page, anno.data.rects[0])));
        if (!back.value.trim()) back.value = `$$${latex}$$`;
        preview();
        status.textContent = 'Drafting...';
      }
      const context = await withPaper(anno.data.docId, v => v.contextFor(anno.data.page, anno.data.quote, 3000));
      const doc = store.get(anno.data.docId);
      const card = await draftCard({ docTitle: doc ? doc.data.title : '', quote: anno.data.quote, latex, context });
      front.value = card.front;
      back.value = card.back;
      preview();
      status.textContent = 'Edit the draft, then save.';
    } catch (e) {
      console.error('Card draft failed', e);
      status.textContent = 'AI draft failed: ' + e.message + '. You can still write the card yourself.';
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
  await store.create('card', {
    front: front.value.trim(),
    back: back.value.trim(),
    docId: saved.data.docId,
    annoId: saved.id,
    srs: newSrs(),
  });
  toast('Card saved');
}

// ── Context panel ──

function setPanel(open) {
  state.panelOpen = open;
  try {
    localStorage.setItem('reader.panel', open ? '1' : '0');
  } catch (e) {
    console.warn('Could not remember the panel state', e);
  }
  renderPanel();
  // On wide screens the panel takes width from the page.
  if (state.pdf && !NARROW.matches) state.pdf.layout();
}

function renderPanel() {
  const panel = $('#panel');
  const show = state.panelOpen && (state.view === 'doc' || state.view === 'note');
  panel.classList.toggle('hidden', !show);
  $('#toggle-panel').classList.toggle('active', state.panelOpen);
  $('#toggle-note-panel').classList.toggle('active', state.panelOpen);
  if (!show) return;
  if (state.view === 'doc') renderDocPanel(panel);
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
    return d ? `<a href="#doc=${d.id}" class="source"></a>` : '';
  }
  const a = store.get(it.data.annoId);
  return `<a href="#doc=${a.data.docId}&a=${a.id}" class="source"></a>`;
}

function fillSourceLabels(root, it) {
  const el = root.querySelector('.source');
  if (!el) return;
  const a = it.data.annoId && store.get(it.data.annoId);
  const d = store.get(a ? a.data.docId : it.data.docId);
  el.textContent = (d ? d.data.title : 'Paper') + (a ? ', p. ' + a.data.page : '');
}

function renderStudy() {
  const root = $('#view-study');
  if (state.review) return renderReview(root);
  const now = Date.now();
  const q = studyQueue(store.all(), now);
  const questions = q.open.filter(t => t.data.type === 'question');
  const open = q.open.filter(t => t.data.type !== 'question');

  root.innerHTML = `
    <div class="study">
      <section class="study-block">
        <h2>Cards</h2>
        <p class="muted cards-line"></p>
        <button class="btn btn-primary" id="start-review" ${q.dueCards.length ? '' : 'disabled'}>Review ${q.dueCards.length} due</button>
      </section>
      <section class="study-block"><h2>Explanations to read <span class="muted">${q.toReview.length}</span></h2><div class="study-list" id="study-ready"></div></section>
      <section class="study-block"><h2>Open follow-ups <span class="muted">${open.length}</span></h2><div class="study-list" id="study-open"></div></section>
      <section class="study-block"><h2>Questions for journal club <span class="muted">${questions.length}</span></h2>
        <p class="muted">Each paper's <strong>Brief</strong> (in its toolbar) collects its questions, open points and key equations for presenting.</p>
        <div class="study-list" id="study-questions"></div></section>
    </div>`;
  const allCards = store.all('card');
  const next = allCards.filter(c => c.data.srs.due > now).sort((a, b) => a.data.srs.due - b.data.srs.due)[0];
  root.querySelector('.cards-line').textContent = `${allCards.length} cards, ${q.dueCards.length} due now` +
    (next ? `, next one ${new Date(next.data.srs.due).toLocaleString()}` : '');
  root.querySelector('#start-review').addEventListener('click', () => {
    state.review = { queue: q.dueCards.map(c => c.id), index: 0, revealed: false };
    renderStudy();
  });

  const readyBox = root.querySelector('#study-ready');
  if (!q.toReview.length) readyBox.innerHTML = '<p class="muted">Select a passage and choose Explain to get one.</p>';
  for (const t of q.toReview) readyBox.appendChild(explanationCard(t));

  const openBox = root.querySelector('#study-open');
  if (!open.length) openBox.innerHTML = '<p class="muted">Nothing open.</p>';
  for (const t of open) openBox.appendChild(taskRow(t));

  const qBox = root.querySelector('#study-questions');
  if (!questions.length) qBox.innerHTML = '<p class="muted">Mark passages with Question to collect them for discussion.</p>';
  for (const t of questions) qBox.appendChild(taskRow(t));
}

function explanationCard(t) {
  const el = document.createElement('article');
  el.className = 'explain-card';
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
  if (explainState(t) === 'writing') {
    const again = el.querySelector('[data-act="again"]');
    again.disabled = true;
    again.textContent = 'Writing a new one...';
    el.classList.add('is-writing');
  }
  el.querySelector('.explain-foot').addEventListener('click', async e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    const a = t.data.annoId && store.get(t.data.annoId);
    try {
      if (act === 'done') {
        await store.update(t.id, { status: 'done' });
        if (a) await store.update(a.id, { status: 'understood' });
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
  if (!a) return '';
  if (a.data.type === 'region') return a.data.latex ? `$${a.data.latex}$` : '';
  return a.data.quote;
}

function taskRow(t) {
  const el = document.createElement('div');
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
    ${t.data.error || gen === 'interrupted' ? '<span class="task-error"></span>' : ''}`;
  el.querySelector('.task-text').innerHTML = renderMarkdown(t.data.text, resolveLink);
  if (quote) el.querySelector('.task-quote').innerHTML = renderMarkdown(snippet(quote, 400), resolveLink);
  fillSourceLabels(el, t);
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
      : soon.length === 1 ? `Next card back in ${wait} min.`
      : soon.length ? `Next card back in ${wait} min; ${soon.length} back within ${lastWait} min.`
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
  const card = store.get(r.queue[r.index]);
  try {
    await store.update(card.id, { srs: r.preview[i].srs });
  } catch (e) {
    reportError('Saving the review failed', e);
    return;
  }
  r.index += 1;
  r.revealed = false;
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
    const state = ex ? (ex.data.status === 'ready' ? 'explanation ready to read' : ex.data.status === 'done' ? 'explained' : 'explanation pending') : 'no explanation yet';
    out.push('', `- ${ref(a)} *(${state})*`, `  ${quoteLine(a).replace(/\n/g, ' ')}`);
  }

  const equations = annos.filter(a => a.data.type === 'region' && a.data.latex);
  out.push('', `## Key equations (${equations.length})`);
  if (!equations.length) out.push('Use the Region tool on an equation and choose Equation card or LaTeX to notebook.');
  for (const a of equations) {
    const n = cards.filter(c => c.data.annoId === a.id).length;
    out.push('', `$$${a.data.latex}$$`, `${ref(a)}${n ? ` - ${n} card${n > 1 ? 's' : ''}` : ''}${a.data.status === 'understood' ? ' - understood' : a.data.status === 'unclear' ? ' - not clear yet' : ''}`);
  }

  const open = tasks.filter(t => t.data.type !== 'question' && t.data.type !== 'explain' && t.data.status !== 'done');
  out.push('', `## Open follow-ups (${open.length})`);
  if (!open.length) out.push('Nothing open.');
  for (const t of open) {
    const a = t.data.annoId && store.get(t.data.annoId);
    out.push(`- [ ] ${TASK_LABELS[t.data.type]}: ${t.data.text.replace(/^Explain:\s*/, '')}` + (a ? ` ${ref(a)}` : ''));
  }

  const commented = annos.filter(a => a.data.comment);
  if (commented.length) {
    out.push('', `## Comments (${commented.length})`);
    for (const a of commented) out.push('', `- ${ref(a)} ${a.data.comment}`, `  ${quoteLine(a).replace(/\n/g, ' ')}`);
  }

  const nb = paperNotebook(docId);
  const nbText = nb ? nb.data.blocks.filter(b => b.type === 'md').map(b => b.text.trim()).filter(Boolean) : [];
  if (nbText.length) out.push('', '## From the notebook', '', nbText.join('\n\n'));

  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  out.push('', `---`, `${plural(cards.length, 'card')}, ${plural(annos.length, 'mark')}.`);
  return out.join('\n');
}

function plainLinks(md) {
  return md.replace(/\[\[([^\[\]|]+?)(?:\|([^\[\]]*))?\]\]/g, (m, target, label) => {
    if (label) return label;
    if (!target.startsWith('@')) return target;
    const a = store.get(target.slice(1));
    return a ? `p. ${a.data.page}` : '';
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
      renderPanel();
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
  $('#toggle-panel').addEventListener('click', () => setPanel(!state.panelOpen));
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
    if (lastPointer !== 'touch' && state.tool.tool !== 'select') return;
    const a = state.pdf.annoAt(e.clientX, e.clientY);
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
