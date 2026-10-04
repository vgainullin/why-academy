// Cookie sessions backed by D1.
//
// The browser holds a random 256-bit token in an HttpOnly cookie. D1 stores
// only its SHA-256, so a database leak does not yield usable sessions.
// Sessions last 30 days and slide forward when used in the second half.

const COOKIE_NAME = '__Host-wa_session';
const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000;
const RENEW_BELOW_MS = 15 * 24 * 60 * 60 * 1000;

export async function createSession(db, accountId) {
  const token = randomToken();
  const now = Date.now();
  const expiresAt = now + SESSION_TTL_MS;
  await db
    .prepare('INSERT INTO account_sessions (id, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)')
    .bind(await hashToken(token), accountId, now, expiresAt)
    .run();
  return { cookie: sessionCookie(token, expiresAt - now) };
}

// Returns { user, setCookie } for a valid session, or null.
// setCookie is non-null when the session was renewed.
export async function getSession(request, db) {
  const token = readCookie(request, COOKIE_NAME);
  if (!token) return null;

  const id = await hashToken(token);
  const now = Date.now();
  const row = await db
    .prepare(
      `SELECT s.expires_at, a.id, a.display_name
         FROM account_sessions s JOIN accounts a ON a.id = s.account_id
        WHERE s.id = ? AND s.expires_at > ?`,
    )
    .bind(id, now)
    .first();
  if (!row) return null;

  let setCookie = null;
  if (row.expires_at - now < RENEW_BELOW_MS) {
    const expiresAt = now + SESSION_TTL_MS;
    await db.prepare('UPDATE account_sessions SET expires_at = ? WHERE id = ?').bind(expiresAt, id).run();
    setCookie = sessionCookie(token, SESSION_TTL_MS);
  }

  return {
    user: { id: row.id, displayName: row.display_name },
    setCookie,
  };
}

export async function destroySession(request, db) {
  const token = readCookie(request, COOKIE_NAME);
  if (token) {
    await db.prepare('DELETE FROM account_sessions WHERE id = ?').bind(await hashToken(token)).run();
  }
  return clearedCookie();
}

export async function deleteExpiredSessions(db) {
  const result = await db.prepare('DELETE FROM account_sessions WHERE expires_at <= ?').bind(Date.now()).run();
  return result.meta.changes;
}

export function clearedCookie() {
  return `${COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
}

function sessionCookie(token, maxAgeMs) {
  return `${COOKIE_NAME}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${Math.floor(maxAgeMs / 1000)}`;
}

function readCookie(request, name) {
  const header = request.headers.get('Cookie');
  if (!header) return null;
  for (const part of header.split(';')) {
    const eq = part.indexOf('=');
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === name) return part.slice(eq + 1).trim();
  }
  return null;
}

function randomToken() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function hashToken(token) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(token));
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}
