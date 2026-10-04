// Why Academy — site + API Worker
//
// Static files are served by Workers Static Assets; only /api/* reaches this
// code (see run_worker_first in wrangler.toml). Because the API shares the
// site's origin, sessions use a first-party HttpOnly cookie.
//
// Endpoints:
//   POST   /api/auth/register/options  - start creating an account (passkey)
//   POST   /api/auth/register/verify   - finish it; sets the session cookie
//   POST   /api/auth/login/options     - start passkey sign-in
//   POST   /api/auth/login/verify      - finish it; sets the session cookie
//   POST   /api/auth/logout            - end the current session
//   POST   /api/passkeys/options       - signed in: add a passkey (another device)
//   POST   /api/passkeys/verify
//   GET    /api/me                     - current user, or 401
//   GET    /api/settings               - synced settings document
//   PUT    /api/settings               - replace settings (optimistic concurrency)
//   POST   /api/feedback               - allowlisted users: feedback -> GitHub issue

import { json, readJson, isSameOrigin, clientIp } from './http.js';
import {
  PasskeyError,
  registrationOptions,
  verifyRegistration,
  authenticationOptions,
  verifyAuthentication,
  deleteExpiredChallenges,
} from './passkeys.js';
import { createSession, getSession, destroySession, deleteExpiredSessions } from './sessions.js';
import { SettingsSchema, MAX_SETTINGS_BYTES, getSettings, putSettings } from './settings.js';
import { submitFeedback, isUserAllowed } from './feedback.js';

const MAX_AUTH_BYTES = 16 * 1024;
const MAX_FEEDBACK_BYTES = 64 * 1024;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);

    if (request.method !== 'GET' && request.method !== 'HEAD' && !isSameOrigin(request)) {
      return json({ error: 'Cross-origin request rejected' }, 403);
    }

    try {
      const route = request.method + ' ' + url.pathname;
      switch (route) {
        case 'POST /api/auth/register/options': return await handleRegisterOptions(request, env);
        case 'POST /api/auth/register/verify': return await handleRegisterVerify(request, env);
        case 'POST /api/auth/login/options': return await handleLoginOptions(request, env);
        case 'POST /api/auth/login/verify': return await handleLoginVerify(request, env);
        case 'POST /api/auth/logout': return await handleLogout(request, env);
        case 'POST /api/passkeys/options': return await withSession(request, env, handleAddPasskeyOptions);
        case 'POST /api/passkeys/verify': return await withSession(request, env, handleAddPasskeyVerify);
        case 'GET /api/me': return await withSession(request, env, handleMe);
        case 'GET /api/settings': return await withSession(request, env, handleGetSettings);
        case 'PUT /api/settings': return await withSession(request, env, handlePutSettings);
        case 'POST /api/feedback': return await withSession(request, env, handleFeedback);
        default: return json({ error: 'Not found' }, 404);
      }
    } catch (e) {
      if (e instanceof PasskeyError) return json({ error: e.message }, 400);
      console.error('Worker error:', e);
      return json({ error: 'Internal error' }, 500);
    }
  },

  async scheduled(controller, env) {
    const sessions = await deleteExpiredSessions(env.DB);
    const challenges = await deleteExpiredChallenges(env.DB);
    console.log('Expired rows removed: sessions', sessions, 'challenges', challenges);
  },
};

async function withSession(request, env, handler) {
  const session = await getSession(request, env.DB);
  if (!session) return json({ error: 'Not signed in' }, 401);
  const response = await handler(request, env, session.user);
  if (session.setCookie) response.headers.append('Set-Cookie', session.setCookie);
  return response;
}

function publicUser(user, env) {
  return {
    user: { id: user.id, displayName: user.displayName },
    isAllowlisted: isUserAllowed(user.id, env.ALLOWED_USERS),
  };
}

// ── Auth ──

async function rateLimitAuth(request, env) {
  const { success } = await env.AUTH_LIMITER.limit({ key: clientIp(request) });
  return success ? null : json({ error: 'Too many attempts, try again in a minute' }, 429);
}

async function signedIn(request, env, account) {
  // Signing in again replaces, rather than orphans, the current session.
  await destroySession(request, env.DB);
  const { cookie } = await createSession(env.DB, account.id);
  return json(publicUser(account, env), 200, { 'Set-Cookie': cookie });
}

async function handleRegisterOptions(request, env) {
  const limited = await rateLimitAuth(request, env);
  if (limited) return limited;
  const { body, error } = await readJson(request, MAX_AUTH_BYTES);
  if (error) return error;
  return json(await registrationOptions(request, env.DB, { displayName: body && body.displayName }));
}

async function handleRegisterVerify(request, env) {
  const limited = await rateLimitAuth(request, env);
  if (limited) return limited;
  const { body, error } = await readJson(request, MAX_AUTH_BYTES);
  if (error) return error;
  const account = await verifyRegistration(request, env.DB, { credential: body && body.credential });
  return signedIn(request, env, account);
}

async function handleLoginOptions(request, env) {
  const limited = await rateLimitAuth(request, env);
  if (limited) return limited;
  return json(await authenticationOptions(request, env.DB));
}

async function handleLoginVerify(request, env) {
  const limited = await rateLimitAuth(request, env);
  if (limited) return limited;
  const { body, error } = await readJson(request, MAX_AUTH_BYTES);
  if (error) return error;
  const account = await verifyAuthentication(request, env.DB, { credential: body && body.credential });
  return signedIn(request, env, account);
}

async function handleAddPasskeyOptions(request, env, user) {
  return json(await registrationOptions(request, env.DB, { account: user }));
}

async function handleAddPasskeyVerify(request, env, user) {
  const { body, error } = await readJson(request, MAX_AUTH_BYTES);
  if (error) return error;
  await verifyRegistration(request, env.DB, { account: user, credential: body && body.credential });
  return json({ ok: true });
}

async function handleLogout(request, env) {
  const cookie = await destroySession(request, env.DB);
  return json({ ok: true }, 200, { 'Set-Cookie': cookie });
}

async function handleMe(request, env, user) {
  return json(publicUser(user, env));
}

// ── Settings ──

async function handleGetSettings(request, env, user) {
  return json(await getSettings(env.DB, user.id));
}

async function handlePutSettings(request, env, user) {
  const { success } = await env.API_LIMITER.limit({ key: user.id });
  if (!success) return json({ error: 'Too many requests' }, 429);

  const { body, error } = await readJson(request, MAX_SETTINGS_BYTES + 1024);
  if (error) return error;

  const baseVersion = body && body.baseVersion;
  if (!Number.isInteger(baseVersion) || baseVersion < 0) {
    return json({ error: 'baseVersion must be a non-negative integer' }, 400);
  }

  const parsed = SettingsSchema.safeParse(body.data);
  if (!parsed.success) {
    return json({ error: 'Invalid settings', issues: parsed.error.issues.slice(0, 10) }, 400);
  }
  if (new TextEncoder().encode(JSON.stringify(parsed.data)).length > MAX_SETTINGS_BYTES) {
    return json({ error: 'Settings too large' }, 413);
  }

  const result = await putSettings(env.DB, user.id, parsed.data, baseVersion);
  if (!result.ok) return json({ error: 'Version conflict', current: result.current }, 409);
  return json({ version: result.version });
}

// ── Feedback ──

async function handleFeedback(request, env, user) {
  const { body, error } = await readJson(request, MAX_FEEDBACK_BYTES);
  if (error) return error;
  const result = await submitFeedback(env, user, body);
  return json(result.body, result.status);
}
