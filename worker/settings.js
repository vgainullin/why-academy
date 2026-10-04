// Synced user settings: one JSON document per user, guarded by a version
// number so concurrent writers from two devices cannot silently clobber each
// other. The client merges and retries on 409.
//
// Must stay in sync with the blob produced by lib/sync.js.

import { z } from 'zod';

export const MAX_SETTINGS_BYTES = 32 * 1024;

// Device preferences synced with per-key last-write-wins timestamps.
// The OpenRouter API key is deliberately absent: it never leaves the device.
const PREF_KEYS = [
  'handwriteBackend',
  'handwriteEndpoint',
  'handwriteModel',
  'openrouterModel',
  'handwriteStrokeWidth',
];

const Timestamp = z.number().int().nonnegative();

const Pref = z.strictObject({
  value: z.string().max(500).nullable(),
  t: Timestamp,
});

const PlaygroundEntry = z.strictObject({
  completed: z.boolean(),
  firstCompleted: Timestamp.optional(),
  lastCompleted: Timestamp.optional(),
});

export const SettingsSchema = z.strictObject({
  v: z.literal(1),
  prefs: z.strictObject(Object.fromEntries(PREF_KEYS.map(k => [k, Pref.optional()]))),
  playground: z
    .record(z.string().regex(/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/), PlaygroundEntry)
    .refine(o => Object.keys(o).length <= 500, 'too many playground entries'),
  rootlock: z.strictObject({
    bestStreak: z.number().int().min(0).max(1_000_000),
  }),
});

export async function getSettings(db, userId) {
  const row = await db
    .prepare('SELECT data, version, updated_at FROM account_settings WHERE account_id = ?')
    .bind(userId)
    .first();
  if (!row) return { data: null, version: 0, updatedAt: null };
  return { data: JSON.parse(row.data), version: row.version, updatedAt: row.updated_at };
}

// Writes data if the stored version still equals baseVersion.
// Returns { ok: true, version } or { ok: false, current }.
export async function putSettings(db, userId, data, baseVersion) {
  const now = Date.now();
  const text = JSON.stringify(data);

  const result = baseVersion === 0
    ? await db
        .prepare(
          `INSERT INTO account_settings (account_id, data, version, updated_at) VALUES (?, ?, 1, ?)
           ON CONFLICT(account_id) DO NOTHING`,
        )
        .bind(userId, text, now)
        .run()
    : await db
        .prepare('UPDATE account_settings SET data = ?, version = version + 1, updated_at = ? WHERE account_id = ? AND version = ?')
        .bind(text, now, userId, baseVersion)
        .run();

  if (result.meta.changes === 1) return { ok: true, version: baseVersion + 1 };
  return { ok: false, current: await getSettings(db, userId) };
}
