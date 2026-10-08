// Why Academy — study vault store (browser)
//
// IndexedDB is the local source of truth; every edit is written there first
// and marked dirty, so reading and annotating work offline. When signed in,
// the sync loop pushes dirty items and pulls everything newer than the last
// cursor from /api/vault (see worker/vault.js). PDF bytes are cached in
// IndexedDB and uploaded to R2 by SHA-256.
//
// Each account gets its own database, so switching accounts never mixes
// vaults. Signed out, the vault is local to this browser ("guest").

import { newId, nextUpdatedAt, resolveIncoming } from './model.js';

const DB_VERSION = 1;
const PUSH_BATCH_ITEMS = 100;
const PUSH_BATCH_BYTES = 1.5 * 1024 * 1024;
const SYNC_DEBOUNCE_MS = 1500;
const SYNC_MAX_WAIT_MS = 5000;
const SYNC_INTERVAL_MS = 60_000;

function req(r) {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

function txDone(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error('IndexedDB transaction aborted'));
  });
}

function openDb(name) {
  const open = indexedDB.open(name, DB_VERSION);
  open.onupgradeneeded = () => {
    const db = open.result;
    db.createObjectStore('items', { keyPath: 'id' });
    db.createObjectStore('files', { keyPath: 'id' });
    db.createObjectStore('meta');
  };
  return req(open);
}

export async function sha256Hex(buffer) {
  const digest = await crypto.subtle.digest('SHA-256', buffer);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

export class VaultStore extends EventTarget {
  constructor() {
    super();
    this.db = null;
    this.accountId = null;
    this.items = new Map(); // id -> { id, kind, updatedAt, deleted, data, dirty }
    this.status = { state: 'local', message: 'Not signed in: saved on this device only' };
    this._timer = null;
    this._interval = null;
    this._syncing = null;
    this._again = false;
    this._onVisibility = () => {
      if (document.visibilityState === 'hidden') this.syncSoon(0);
    };
    this._onOnline = () => this.syncSoon(0);
  }

  // Opens the vault for an account (or null for the guest vault) and starts
  // syncing when there is an account.
  async open(accountId) {
    this.close();
    this.accountId = accountId;
    this.db = await openDb('why-vault-' + (accountId || 'guest'));
    const rows = await req(this.db.transaction('items').objectStore('items').getAll());
    this.items = new Map(rows.map(r => [r.id, r]));
    this._emit('change', { ids: null });

    if (accountId) {
      document.addEventListener('visibilitychange', this._onVisibility);
      window.addEventListener('online', this._onOnline);
      this._interval = setInterval(() => this.syncSoon(0), SYNC_INTERVAL_MS);
      this.syncSoon(0);
    } else {
      this._setStatus('local', 'Not signed in: saved on this device only');
    }
  }

  close() {
    clearTimeout(this._timer);
    clearInterval(this._interval);
    document.removeEventListener('visibilitychange', this._onVisibility);
    window.removeEventListener('online', this._onOnline);
    if (this.db) this.db.close();
    this.db = null;
  }

  // ── Reads ──

  get(id) {
    const it = this.items.get(id);
    return it && !it.deleted ? it : null;
  }

  all(kind) {
    const out = [];
    for (const it of this.items.values()) {
      if (!it.deleted && (!kind || it.kind === kind)) out.push(it);
    }
    return out;
  }

  forDoc(docId, kind) {
    return this.all(kind).filter(it => it.data.docId === docId);
  }

  // ── Writes ──

  // Creates or replaces an item. Returns the stored item.
  async put(kind, id, data) {
    const prev = this.items.get(id);
    const item = {
      id: id || newId(),
      kind,
      updatedAt: nextUpdatedAt(prev && prev.updatedAt, Date.now()),
      deleted: false,
      data,
      dirty: true,
    };
    await this._write([item]);
    this._emit('change', { ids: [item.id] });
    this.syncSoon();
    return item;
  }

  create(kind, data) {
    return this.put(kind, newId(), data);
  }

  // Shallow-merges fields into an item's data.
  update(id, patch) {
    const it = this.items.get(id);
    if (!it || it.deleted) throw new Error('No such item: ' + id);
    return this.put(it.kind, id, { ...it.data, ...patch });
  }

  async remove(id) {
    const it = this.items.get(id);
    if (!it || it.deleted) return;
    const tomb = { ...it, deleted: true, data: {}, dirty: true, updatedAt: nextUpdatedAt(it.updatedAt, Date.now()) };
    await this._write([tomb]);
    this._emit('change', { ids: [id] });
    this.syncSoon();
  }

  async _write(items) {
    const tx = this.db.transaction('items', 'readwrite');
    const st = tx.objectStore('items');
    for (const it of items) st.put(it);
    await txDone(tx);
    for (const it of items) this.items.set(it.id, it);
  }

  // ── Files ──

  // Stores PDF bytes locally and queues the upload. Returns the SHA-256 id.
  async addFile(bytes) {
    const id = await sha256Hex(bytes);
    const existing = await req(this.db.transaction('files').objectStore('files').get(id));
    if (!existing) {
      const tx = this.db.transaction('files', 'readwrite');
      tx.objectStore('files').put({ id, blob: new Blob([bytes], { type: 'application/pdf' }), uploaded: false });
      await txDone(tx);
      this.syncSoon(0);
    }
    return id;
  }

  // Returns the PDF bytes, from the local cache or the server.
  async getFile(id) {
    const local = await req(this.db.transaction('files').objectStore('files').get(id));
    if (local) return new Uint8Array(await local.blob.arrayBuffer());
    if (!this.accountId) throw new Error('This PDF is not on this device. Sign in to download it.');

    const resp = await fetch('/api/vault/files/' + id, { credentials: 'same-origin' });
    if (!resp.ok) throw new Error('Download failed: HTTP ' + resp.status);
    const bytes = new Uint8Array(await resp.arrayBuffer());
    const tx = this.db.transaction('files', 'readwrite');
    tx.objectStore('files').put({ id, blob: new Blob([bytes], { type: 'application/pdf' }), uploaded: true });
    await txDone(tx);
    return bytes;
  }

  async removeFile(id) {
    const tx = this.db.transaction('files', 'readwrite');
    tx.objectStore('files').delete(id);
    await txDone(tx);
    if (this.accountId) {
      const resp = await fetch('/api/vault/files/' + id, { method: 'DELETE', credentials: 'same-origin' });
      if (!resp.ok) throw new Error('Deleting the PDF on the server failed: HTTP ' + resp.status);
    }
  }

  // ── Guest vault ──

  // Items and files saved while signed out live in the guest database. After
  // sign-in they can be moved into the account (and then sync).
  async guestItemCount() {
    if (!this.accountId) return 0;
    const guest = await openDb('why-vault-guest');
    try {
      return await req(guest.transaction('items').objectStore('items').count());
    } finally {
      guest.close();
    }
  }

  async adoptGuest() {
    const guest = await openDb('why-vault-guest');
    try {
      const items = await req(guest.transaction('items').objectStore('items').getAll());
      const files = await req(guest.transaction('files').objectStore('files').getAll());
      const now = Date.now();
      const moved = items
        .filter(it => !this.items.has(it.id) || this.items.get(it.id).updatedAt < it.updatedAt)
        .map(it => ({ ...it, updatedAt: nextUpdatedAt(it.updatedAt, now), dirty: true }));
      const tx = this.db.transaction('files', 'readwrite');
      for (const f of files) tx.objectStore('files').put({ ...f, uploaded: false });
      await txDone(tx);
      await this._write(moved);

      const clear = guest.transaction(['items', 'files'], 'readwrite');
      clear.objectStore('items').clear();
      clear.objectStore('files').clear();
      await txDone(clear);
      this._emit('change', { ids: null });
      this.syncSoon(0);
      return moved.length;
    } finally {
      guest.close();
    }
  }

  // ── Sync ──

  // Debounced, but a steady stream of edits still syncs every few seconds.
  syncSoon(delay = SYNC_DEBOUNCE_MS) {
    if (!this.accountId) return;
    const now = Date.now();
    if (!this._firstScheduled) this._firstScheduled = now;
    delay = Math.min(delay, Math.max(0, this._firstScheduled + SYNC_MAX_WAIT_MS - now));
    clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      this._firstScheduled = 0;
      this.sync();
    }, delay);
  }

  // Runs one sync; concurrent calls coalesce into a follow-up run.
  async sync() {
    if (!this.accountId || !this.db) return;
    if (this._syncing) {
      this._again = true;
      return this._syncing;
    }
    this._syncing = (async () => {
      do {
        this._again = false;
        this._setStatus('syncing', 'Syncing');
        try {
          await this._uploadFiles();
          await this._push();
          await this._pull();
          const pending = [...this.items.values()].filter(it => it.dirty).length;
          this._setStatus('synced', pending ? pending + ' changes waiting' : 'Synced');
        } catch (e) {
          if (e.signedOut) {
            this._setStatus('signed-out', 'Signed out: changes stay on this device');
            return;
          }
          const offline = !navigator.onLine || e instanceof TypeError;
          console.error('Vault sync failed', e);
          this._setStatus(offline ? 'offline' : 'error', offline ? 'Offline: changes saved on this device' : 'Sync failed: ' + e.message);
          return;
        }
      } while (this._again);
    })();
    try {
      await this._syncing;
    } finally {
      this._syncing = null;
    }
  }

  async _api(path, init) {
    const resp = await fetch(path, { credentials: 'same-origin', ...init });
    if (resp.status === 401) {
      const err = new Error('Not signed in');
      err.signedOut = true;
      throw err;
    }
    return resp;
  }

  async _uploadFiles() {
    const files = await req(this.db.transaction('files').objectStore('files').getAll());
    for (const f of files.filter(f => !f.uploaded)) {
      // PUT is idempotent (the server answers existed: true), so no HEAD probe
      // first: its 404 for a new file shows up as a console error.
      const resp = await this._api('/api/vault/files/' + f.id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/pdf' },
        body: f.blob,
      });
      if (!resp.ok) throw new Error('PDF upload failed: ' + (await resp.text()));
      const tx = this.db.transaction('files', 'readwrite');
      tx.objectStore('files').put({ ...f, uploaded: true });
      await txDone(tx);
    }
  }

  async _push() {
    const dirty = [...this.items.values()].filter(it => it.dirty);
    let batch = [];
    let bytes = 0;
    for (const it of dirty) {
      const wire = { id: it.id, kind: it.kind, updatedAt: it.updatedAt, deleted: it.deleted, data: it.data };
      const size = JSON.stringify(wire).length;
      if (batch.length && (batch.length >= PUSH_BATCH_ITEMS || bytes + size > PUSH_BATCH_BYTES)) {
        await this._pushBatch(batch);
        batch = [];
        bytes = 0;
      }
      batch.push(wire);
      bytes += size;
    }
    if (batch.length) await this._pushBatch(batch);
  }

  async _pushBatch(batch) {
    const resp = await this._api('/api/vault/push', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: batch }),
    });
    if (!resp.ok) throw new Error('push: HTTP ' + resp.status + ' ' + (await resp.text()));
    const { stale } = await resp.json();

    // Pushed items are clean unless edited again while the request was out.
    // Items the server answered with a different copy stay dirty, so _apply
    // resolves them against our version (ink merges, notes keep a conflict
    // copy) instead of silently adopting the server's.
    const staleIds = new Set(stale.map(it => it.id));
    const clean = [];
    for (const w of batch) {
      const cur = this.items.get(w.id);
      if (cur && cur.dirty && cur.updatedAt === w.updatedAt && !staleIds.has(w.id)) clean.push({ ...cur, dirty: false });
    }
    if (clean.length) await this._write(clean);
    if (stale.length) await this._apply(stale);
  }

  async _pull() {
    let cursor = (await req(this.db.transaction('meta').objectStore('meta').get('cursor'))) || 0;
    for (;;) {
      const resp = await this._api('/api/vault/pull?since=' + cursor);
      if (!resp.ok) throw new Error('pull: HTTP ' + resp.status + ' ' + (await resp.text()));
      const page = await resp.json();
      if (page.items.length) await this._apply(page.items);
      cursor = page.cursor;
      const tx = this.db.transaction('meta', 'readwrite');
      tx.objectStore('meta').put(cursor, 'cursor');
      await txDone(tx);
      if (!page.more) break;
    }
  }

  async _apply(remoteItems) {
    const now = Date.now();
    const writes = [];
    for (const r of remoteItems) {
      const remote = { id: r.id, kind: r.kind, updatedAt: r.updatedAt, deleted: r.deleted, data: r.data };
      const { item, dirty, extra } = resolveIncoming(this.items.get(r.id), remote, now);
      writes.push({ ...item, dirty });
      for (const e of extra) writes.push({ ...e, dirty: true });
    }
    await this._write(writes);
    if (writes.some(w => w.dirty)) this._again = true;
    this._emit('change', { ids: writes.map(w => w.id), remote: true });
  }

  _setStatus(state, message) {
    this.status = { state, message };
    this._emit('status', this.status);
  }

  _emit(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }
}
