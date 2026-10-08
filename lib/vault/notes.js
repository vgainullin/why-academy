// Why Academy — note editor (the notebook)
//
// A note is a list of blocks:
//   md  - typed Markdown with $math$ and [[wikilinks]]. On iPad, Scribble in
//         the textarea already turns Pencil handwriting into text.
//   ink - a Pencil pad for scribbles, cursive, drawings and diagrams. On
//         demand it converts to LaTeX (checked line by line with SymPy) or
//         to text.
// Edits autosave to the vault store.

import { newId } from './model.js';
import { InkSurface } from './ink.js';
import { renderMarkdown, renderMath } from './markdown.js';
import { handwritingToText } from './ai.js';

const SAVE_DELAY_MS = 600;
const DEFAULT_ASPECT = 0.5;
const BACKUP_PREFIX = 'reader.note-draft.';

// Every edit is also written to localStorage at once. The vault save is
// debounced and asynchronous, so a reload, a crash or Safari dropping a
// background tab would otherwise lose the last edits. The backup is replayed
// when the note is opened again and removed once the vault has the edit.
export function noteBackup(id) {
  try {
    return JSON.parse(localStorage.getItem(BACKUP_PREFIX + id));
  } catch (e) {
    console.warn('Unreadable note backup', id, e);
    return null;
  }
}

function writeBackup(id, data) {
  try {
    localStorage.setItem(BACKUP_PREFIX + id, JSON.stringify({ data, at: Date.now() }));
  } catch (e) {
    console.warn('Could not back up the note being edited', e);
  }
}

function clearBackup(id, at) {
  const b = noteBackup(id);
  if (b && b.at <= at) localStorage.removeItem(BACKUP_PREFIX + id);
}

export class NoteEditor {
  /**
   * app: { store, getTool, resolveLink(link), openLink(el), titles(), toast(msg, isError) }
   */
  constructor(root, app) {
    this.root = root;
    this.app = app;
    this.noteId = null;
    this.pads = new Map(); // blockId -> InkSurface
    this._saveTimer = null;
    this._ro = new ResizeObserver(() => {
      for (const pad of this.pads.values()) pad.resize();
    });
  }

  get note() {
    return this.noteId ? this.app.store.get(this.noteId) : null;
  }

  // draft: data for a note not saved yet ("New note"); it is created in the
  // vault on its first edit, so an untouched new note never exists.
  open(noteId, draft) {
    this.flush();
    this.noteId = noteId;
    const note = this.note;
    const backup = noteBackup(noteId);
    if (backup && (!note || backup.at > note.updatedAt)) {
      // Unsaved edits from before a reload or crash.
      this.isDraft = !note;
      this.draft = backup.data;
      this.render();
      this.saveSoon();
      return;
    }
    if (backup) localStorage.removeItem(BACKUP_PREFIX + noteId);
    this.isDraft = !note && !!draft;
    this.draft = structuredClone(this.isDraft ? draft : note.data);
    this.render();
  }

  close() {
    const saved = this.flush();
    this._destroyPads();
    this.noteId = null;
    this.isDraft = false;
    this.root.innerHTML = '';
    return saved;
  }

  // Remote edit arrived for the open note: take it unless the user is typing.
  refreshFromStore() {
    if (!this.noteId) return;
    const note = this.note;
    if (!note) {
      if (!this.isDraft) this.close();
      return;
    }
    this.isDraft = false;
    if (this._saveTimer || this.root.contains(document.activeElement)) return;
    if (JSON.stringify(note.data) === JSON.stringify(this.draft)) return;
    this.draft = structuredClone(note.data);
    this.render();
  }

  // Appends Markdown to the end of the note (from PDF actions).
  appendMarkdown(text) {
    const last = this.draft.blocks[this.draft.blocks.length - 1];
    if (last && last.type === 'md') last.text = last.text.replace(/\s*$/, '') + (last.text.trim() ? '\n\n' : '') + text;
    else this.draft.blocks.push({ id: newId(), type: 'md', text });
    this.saveSoon();
    this.render();
    this.root.querySelector('.note-blocks').lastElementChild?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  saveSoon() {
    if (this.noteId) writeBackup(this.noteId, this.draft);
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => this.flush(), SAVE_DELAY_MS);
  }

  flush() {
    if (!this._saveTimer || !this.noteId) return this._lastSave || Promise.resolve();
    clearTimeout(this._saveTimer);
    this._saveTimer = null;
    const d = this.draft;
    const empty = !d.title.trim() && d.blocks.every(b => (b.type === 'md' ? !b.text.trim() : !b.strokes.length));
    const id = this.noteId;
    if (this.isDraft && empty) {
      localStorage.removeItem(BACKUP_PREFIX + id);
      return this._lastSave || Promise.resolve();
    }
    this.isDraft = false;
    const at = Date.now();
    this._lastSave = this.app.store.put('note', id, structuredClone(this.draft)).then(() => clearBackup(id, at)).catch(e => {
      console.error('Saving note failed', e);
      this.app.toast('Saving the note failed: ' + e.message, true);
    });
    return this._lastSave;
  }

  // Records an undoable pad edit. Undo and redo apply to the note the stroke
  // was made in, even after the editor has moved on to another note.
  _track(label, blockId, undo, redo) {
    if (!this.app.history) return;
    const noteId = this.noteId;
    const apply = mutate => this._padEdit(noteId, blockId, mutate);
    this.app.history.push({ label, undo: () => apply(undo), redo: () => apply(redo) });
  }

  async _padEdit(noteId, blockId, mutate) {
    const sameDraft = this.noteId === noteId ? this.draft : null;
    await this._applyToBlock(noteId, sameDraft, blockId, (blocks, blk) => mutate(blk));
    if (this.noteId === noteId) {
      const blk = this.draft.blocks.find(x => x.id === blockId);
      const pad = this.pads.get(blockId);
      if (blk && pad) pad.setStrokes(blk.strokes);
    }
  }

  // Applies the result of a slow ink action to the block it started from, in
  // the open draft if it is still the same note, otherwise in the stored note.
  async _applyToBlock(noteId, draft, blockId, mutate) {
    if (this.noteId === noteId && this.draft === draft) {
      const blk = draft.blocks.find(x => x.id === blockId);
      if (!blk) return;
      mutate(draft.blocks, blk);
      this.saveSoon();
      return;
    }
    const note = this.app.store.get(noteId);
    const data = note && structuredClone(note.data);
    const blk = data && data.blocks.find(x => x.id === blockId);
    if (!blk) return;
    mutate(data.blocks, blk);
    await this.app.store.put('note', noteId, data);
  }

  _destroyPads() {
    for (const pad of this.pads.values()) pad.destroy();
    this.pads.clear();
    this._ro.disconnect();
  }

  render() {
    this._destroyPads();
    const d = this.draft;
    this.root.innerHTML = `
      <div class="note">
        <input class="note-title" placeholder="Untitled" aria-label="Note title" maxlength="300">
        <div class="note-blocks"></div>
        <div class="note-add">
          <button class="btn-small" data-add="md">+ Text</button>
          <button class="btn-small" data-add="ink">+ Ink</button>
        </div>
        <div class="note-links"></div>
      </div>`;
    const title = this.root.querySelector('.note-title');
    title.value = d.title;
    let titleBefore = d.title;
    title.addEventListener('input', () => {
      d.title = title.value;
      this.saveSoon();
    });
    title.addEventListener('blur', () => {
      const saved = this.flush();
      // Links elsewhere follow the rename once the note itself is saved.
      if (d.title.trim() !== titleBefore.trim() && this.app.noteRenamed) {
        const from = titleBefore;
        const to = d.title.trim();
        titleBefore = d.title;
        saved.then(() => this.app.noteRenamed(from, to));
      }
    });

    const list = this.root.querySelector('.note-blocks');
    if (!d.blocks.length) d.blocks.push({ id: newId(), type: 'md', text: '' });
    for (const b of d.blocks) list.appendChild(this._block(b));

    this.root.querySelectorAll('[data-add]').forEach(btn => btn.addEventListener('click', () => {
      // An empty text block at the end is reused rather than stacking another.
      const last = d.blocks[d.blocks.length - 1];
      if (btn.dataset.add === 'md' && last && last.type === 'md' && !last.text.trim()) {
        list.lastElementChild.querySelector('.md-view')?.click();
        return;
      }
      const b = btn.dataset.add === 'md'
        ? { id: newId(), type: 'md', text: '' }
        : { id: newId(), type: 'ink', aspect: DEFAULT_ASPECT, strokes: [] };
      d.blocks.push(b);
      const el = this._block(b, btn.dataset.add === 'md');
      list.appendChild(el);
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      this.saveSoon();
    }));
    this.renderLinks();
  }

  renderLinks() {
    const box = this.root.querySelector('.note-links');
    if (box && this.app.renderNoteLinks) this.app.renderNoteLinks(box, this.noteId);
  }

  _blockShell(b) {
    const el = document.createElement('div');
    el.className = 'nb-block nb-block-' + b.type;
    el.dataset.id = b.id;
    const tools = document.createElement('div');
    tools.className = 'nb-tools';
    tools.innerHTML = `
      <button class="icon-btn" data-act="up" title="Move up" aria-label="Move up">&uarr;</button>
      <button class="icon-btn" data-act="down" title="Move down" aria-label="Move down">&darr;</button>
      <button class="icon-btn" data-act="del" title="Delete block" aria-label="Delete block">&times;</button>`;
    tools.addEventListener('click', e => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (!act) return;
      const blocks = this.draft.blocks;
      const i = blocks.findIndex(x => x.id === b.id);
      if (act === 'del') {
        const empty = b.type === 'md' ? !b.text.trim() : !b.strokes.length;
        if (!empty && !confirm('Delete this block?')) return;
        blocks.splice(i, 1);
      } else {
        const j = act === 'up' ? i - 1 : i + 1;
        if (j < 0 || j >= blocks.length) return;
        [blocks[i], blocks[j]] = [blocks[j], blocks[i]];
      }
      this.saveSoon();
      this.render();
    });
    el.appendChild(tools);
    return el;
  }

  // ── Markdown block ──

  _block(b, focus) {
    return b.type === 'md' ? this._mdBlock(b, focus) : this._inkBlock(b);
  }

  _mdBlock(b, focus) {
    const el = this._blockShell(b);
    const view = document.createElement('div');
    view.className = 'md-view';
    const edit = document.createElement('textarea');
    edit.className = 'md-edit hidden';
    edit.placeholder = 'Write in Markdown. $math$, [[Note]] links. Pencil Scribble works here.';
    edit.value = b.text;
    el.append(view, edit);

    const showView = () => {
      view.innerHTML = b.text.trim()
        ? renderMarkdown(b.text, link => this.app.resolveLink(link))
        : '<p class="md-empty">Empty text block: tap to write</p>';
      view.classList.remove('hidden');
      edit.classList.add('hidden');
    };
    const showEdit = () => {
      view.classList.add('hidden');
      edit.classList.remove('hidden');
      autosize();
      edit.focus();
    };
    const autosize = () => {
      edit.style.height = 'auto';
      edit.style.height = Math.max(80, edit.scrollHeight + 2) + 'px';
    };

    view.addEventListener('click', e => {
      const link = e.target.closest('a.wl');
      if (link) {
        e.preventDefault();
        this.flush();
        this.app.openLink(link);
        return;
      }
      if (e.target.closest('a, details, summary')) return;
      showEdit();
    });
    edit.addEventListener('input', () => {
      b.text = edit.value;
      autosize();
      this.saveSoon();
      this._suggest(edit);
    });
    edit.addEventListener('keydown', e => {
      if (this._suggestBox && this._suggestKey(e, edit)) return;
      if (e.key === 'Escape') edit.blur();
    });
    edit.addEventListener('blur', () => {
      setTimeout(() => {
        if (document.activeElement === edit) return;
        this._closeSuggest();
        this.flush();
        showView();
        this.renderLinks();
      }, 150);
    });

    if (focus) requestAnimationFrame(showEdit);
    else showView();
    return el;
  }

  // [[ autocomplete over note and document titles.
  _suggest(edit) {
    const before = edit.value.slice(0, edit.selectionStart);
    const m = before.match(/\[\[([^\[\]|\n]*)$/);
    if (!m) return this._closeSuggest();
    const q = m[1].toLowerCase();
    const rank = t => (t.title.toLowerCase().startsWith(q) ? 0 : 2) + (t.kind === 'paper' ? 0 : 1);
    const matches = this.app.titles()
      .filter(t => t.title.toLowerCase().includes(q))
      .sort((a, b) => rank(a) - rank(b) || a.title.localeCompare(b.title))
      .slice(0, 8);
    if (!matches.length && !q) return this._closeSuggest();
    if (!this._suggestBox) {
      this._suggestBox = document.createElement('div');
      this._suggestBox.className = 'suggest';
      this._suggestBox.setAttribute('role', 'listbox');
      this._suggestBox.setAttribute('aria-label', 'Link suggestions');
      edit.after(this._suggestBox);
    }
    this._suggestIndex = 0;
    this._suggestItems = matches.length ? matches : [{ title: m[1], kind: 'new' }];
    this._suggestBox.innerHTML = this._suggestItems
      .map((t, i) => `<button class="suggest-item${i === 0 ? ' active' : ''}" role="option" aria-selected="${i === 0}" data-i="${i}"><span class="suggest-kind">${t.kind}</span></button>`)
      .join('');
    this._suggestBox.querySelectorAll('.suggest-item').forEach((btn, i) => {
      btn.prepend(document.createTextNode(this._suggestItems[i].title + ' '));
      btn.addEventListener('mousedown', e => {
        e.preventDefault();
        this._accept(edit, i);
      });
    });
  }

  _suggestKey(e, edit) {
    const n = this._suggestItems.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      this._suggestIndex = (this._suggestIndex + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
      this._suggestBox.querySelectorAll('.suggest-item').forEach((b, i) => {
        b.classList.toggle('active', i === this._suggestIndex);
        b.setAttribute('aria-selected', String(i === this._suggestIndex));
      });
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      this._accept(edit, this._suggestIndex);
    } else if (e.key === 'Escape') {
      this._closeSuggest();
    } else {
      return false;
    }
    e.preventDefault();
    return true;
  }

  _accept(edit, i) {
    const pos = edit.selectionStart;
    const before = edit.value.slice(0, pos).replace(/\[\[([^\[\]|\n]*)$/, '[[' + this._suggestItems[i].title + ']]');
    let after = edit.value.slice(pos);
    if (after.startsWith(']]')) after = after.slice(2);
    edit.value = before + after;
    edit.selectionStart = edit.selectionEnd = before.length;
    edit.dispatchEvent(new Event('input'));
    this._closeSuggest();
  }

  _closeSuggest() {
    if (this._suggestBox) this._suggestBox.remove();
    this._suggestBox = null;
  }

  // ── Ink block ──

  _inkBlock(b) {
    const el = this._blockShell(b);
    const bar = document.createElement('div');
    bar.className = 'ink-bar';
    bar.innerHTML = `
      <button class="btn-small" data-ink="latex" title="Convert handwriting to LaTeX">To LaTeX</button>
      <button class="btn-small" data-ink="check" title="Check each line follows from the previous one (SymPy)">Check with SymPy</button>
      <button class="btn-small" data-ink="text" title="Transcribe handwriting into a text block">To text</button>
      <button class="btn-small" data-ink="taller" title="More room">Taller</button>
      <span class="ink-status" role="status"></span>`;
    const pad = document.createElement('div');
    pad.className = 'ink-pad';
    pad.style.aspectRatio = String(1 / b.aspect);
    const out = document.createElement('div');
    out.className = 'ink-latex';
    el.append(bar, pad, out);

    const status = bar.querySelector('.ink-status');
    const setStatus = (msg, isError) => {
      status.textContent = msg || '';
      status.classList.toggle('error', !!isError);
    };

    const showLatex = checks => {
      out.innerHTML = '';
      if (!b.latex) return;
      b.latex.split('\n').forEach((line, i) => {
        const row = document.createElement('div');
        row.className = 'latex-line';
        const dot = document.createElement('span');
        const c = checks && checks[i];
        dot.className = 'check-dot ' + (c ? c.status : 'none');
        dot.title = c ? c.message : '';
        const tex = document.createElement('span');
        tex.innerHTML = renderMath(line, true);
        row.append(dot, tex);
        out.appendChild(row);
      });
    };
    showLatex(b.checks);

    requestAnimationFrame(() => {
      const surface = new InkSurface(pad, {
        getTool: this.app.getTool,
        onAdd: s => {
          b.strokes.push(s);
          this.saveSoon();
          this._track('Pen stroke', b.id,
            blk => { blk.strokes = blk.strokes.filter(x => x.id !== s.id); },
            blk => { blk.strokes.push(s); });
        },
        onErase: ids => {
          const gone = new Set(ids);
          const removed = b.strokes.filter(s => gone.has(s.id));
          b.strokes = b.strokes.filter(s => !gone.has(s.id));
          this.saveSoon();
          this._track('Erase', b.id,
            blk => { blk.strokes.push(...removed); },
            blk => { blk.strokes = blk.strokes.filter(x => !gone.has(x.id)); });
        },
        onRegion: () => {},
      });
      surface.setStrokes(b.strokes);
      this.pads.set(b.id, surface);
      this._ro.observe(pad);
    });

    bar.addEventListener('click', async e => {
      const act = e.target.closest('[data-ink]')?.dataset.ink;
      if (!act) return;
      const surface = this.pads.get(b.id);
      // Recognition takes seconds; by then the editor may show another note.
      const noteId = this.noteId;
      const draft = this.draft;
      const stillHere = () => this.noteId === noteId && this.draft === draft;
      try {
        if (act === 'taller') {
          b.aspect = Math.min(4, b.aspect + 0.25);
          pad.style.aspectRatio = String(1 / b.aspect);
          this.saveSoon();
          return;
        }
        if (!b.strokes.length) {
          setStatus('Write something first', true);
          return;
        }
        if (act === 'latex') {
          setStatus('Reading handwriting...');
          const { lines } = await window.WhyCommon.transcribeMultiLine(surface.toPng());
          if (!lines.length) throw new Error('Could not read the handwriting');
          await this._applyToBlock(noteId, draft, b.id, (blocks, blk) => {
            blk.latex = lines.join('\n');
            delete blk.checks;
          });
          if (stillHere()) showLatex();
          setStatus('');
        } else if (act === 'check') {
          let latex = b.latex;
          if (!latex) {
            setStatus('Reading handwriting...');
            const { lines } = await window.WhyCommon.transcribeMultiLine(surface.toPng());
            if (!lines.length) throw new Error('SymPy needs LaTeX first, and the handwriting could not be read. Write more clearly or use To LaTeX and fix it.');
            latex = lines.join('\n');
          }
          setStatus('Loading SymPy (first time takes a while)...');
          const checks = await checkChain(latex.split('\n'));
          await this._applyToBlock(noteId, draft, b.id, (blocks, blk) => {
            blk.latex = latex;
            blk.checks = checks;
          });
          if (stillHere()) showLatex(checks);
          const bad = checks.filter(c => c.status === 'bad').length;
          setStatus(bad ? bad + ' step(s) do not follow' : 'Every step follows', bad > 0);
        } else if (act === 'text') {
          setStatus('Transcribing...');
          const text = await handwritingToText(surface.toPng());
          await this._applyToBlock(noteId, draft, b.id, (blocks, blk) => {
            blocks.splice(blocks.indexOf(blk) + 1, 0, { id: newId(), type: 'md', text: text.trim() });
          });
          if (stillHere()) this.render();
          return;
        }
      } catch (err) {
        console.error('Ink action failed', err);
        setStatus(err.message, true);
      }
    });
    return el;
  }
}

// Checks that each line is equivalent to the one before it, using the SymPy
// helpers from shared-core (equiv). Returns [{ status: 'ok'|'bad'|'skip', message }].
const SYMPY_LOAD_TIMEOUT_MS = 120_000;

async function checkChain(lines) {
  const C = window.WhyCommon;
  C.startPyodidePreload();
  // ensureSympy waits forever if the Python runtime failed to download.
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('SymPy did not load. Check your connection and try again.')), SYMPY_LOAD_TIMEOUT_MS);
  });
  try {
    await Promise.race([C.ensureSympy(), timeout]);
  } finally {
    clearTimeout(timer);
  }
  const results = [{ status: 'skip', message: 'First line' }];
  for (let i = 1; i < lines.length; i++) {
    C.pyodide.globals.set('_s', C.canonicalizeLatex(lines[i]));
    C.pyodide.globals.set('_t', C.canonicalizeLatex(lines[i - 1]));
    const out = (await C.pyodide.runPythonAsync('equiv(_s, _t)')).toJs();
    const [code, detail] = out;
    if (code === 'ok') results.push({ status: 'ok', message: 'Follows from the line above' });
    else if (code === 'mismatch') results.push({ status: 'bad', message: 'Not equivalent to the line above' });
    else results.push({ status: 'skip', message: 'SymPy could not check this line: ' + detail });
  }
  return results;
}
