// Why Academy — undo/redo for the reader
//
// Every user edit that can be undone pushes an entry { label, undo, redo }
// whose functions write to the vault (so undo syncs like any other edit).
// Several writes from one action are grouped with batch() and undo together.

const LIMIT = 200;

export class History extends EventTarget {
  constructor() {
    super();
    this.done = [];
    this.undone = [];
    this._group = null;
    this._busy = false;
  }

  get canUndo() {
    return this.done.length > 0 && !this._busy;
  }

  get canRedo() {
    return this.undone.length > 0 && !this._busy;
  }

  push(entry) {
    if (this._group) {
      this._group.push(entry);
      return;
    }
    this.done.push(entry);
    if (this.done.length > LIMIT) this.done.shift();
    this.undone = [];
    this._changed();
  }

  // Runs fn; every entry pushed meanwhile becomes one undo step.
  async batch(label, fn) {
    if (this._group) return fn();
    const group = [];
    this._group = group;
    try {
      return await fn();
    } finally {
      this._group = null;
      if (group.length === 1) this.push(group[0]);
      else if (group.length) {
        this.push({
          label,
          undo: async () => {
            for (const e of [...group].reverse()) await e.undo();
          },
          redo: async () => {
            for (const e of group) await e.redo();
          },
        });
      }
    }
  }

  async undo() {
    return this._step(this.done, this.undone, 'undo');
  }

  async redo() {
    return this._step(this.undone, this.done, 'redo');
  }

  async _step(from, to, which) {
    if (this._busy || !from.length) return null;
    const entry = from.pop();
    this._busy = true;
    this._changed();
    try {
      await entry[which]();
      to.push(entry);
      return entry;
    } catch (e) {
      // A failed step is dropped rather than retried into a half-applied state.
      console.error('History ' + which + ' failed', e);
      throw e;
    } finally {
      this._busy = false;
      this._changed();
    }
  }

  _changed() {
    this.dispatchEvent(new Event('change'));
  }
}
