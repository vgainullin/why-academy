// Passkey (WebAuthn) accounts.
//
// Every ceremony is two requests: /options issues a single-use challenge
// (stored in D1, 5 minute TTL), /verify consumes it. Credentials are
// discoverable, so signing in needs no username. User verification
// (biometric / device PIN) is required because the passkey is the only factor.
//
// The relying party is whatever host served the request: passkeys made on
// one hostname do not work on another.

import {
  generateRegistrationOptions,
  verifyRegistrationResponse,
  generateAuthenticationOptions,
  verifyAuthenticationResponse,
} from '@simplewebauthn/server';
import { isoBase64URL } from '@simplewebauthn/server/helpers';

const RP_NAME = 'Why Academy';
const CHALLENGE_TTL_MS = 5 * 60 * 1000;
const DEFAULT_DISPLAY_NAME = 'Why Academy learner';

export class PasskeyError extends Error {}

function relyingParty(request) {
  const url = new URL(request.url);
  return { rpID: url.hostname, origin: url.origin };
}

export function cleanDisplayName(raw) {
  if (typeof raw !== 'string') return DEFAULT_DISPLAY_NAME;
  const name = raw.replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 64);
  return name || DEFAULT_DISPLAY_NAME;
}

async function saveChallenge(db, challenge, kind, accountId, displayName) {
  await db
    .prepare('INSERT INTO webauthn_challenges (challenge, kind, account_id, display_name, expires_at) VALUES (?, ?, ?, ?, ?)')
    .bind(challenge, kind, accountId, displayName, Date.now() + CHALLENGE_TTL_MS)
    .run();
}

// Deletes and returns the challenge row if it exists, is unexpired and has
// the expected kind; otherwise null. Single use either way.
async function consumeChallenge(db, challenge, kind) {
  const row = await db
    .prepare('DELETE FROM webauthn_challenges WHERE challenge = ? AND expires_at > ? RETURNING kind, account_id, display_name')
    .bind(challenge, Date.now())
    .first();
  return row && row.kind === kind ? row : null;
}

export async function deleteExpiredChallenges(db) {
  const result = await db.prepare('DELETE FROM webauthn_challenges WHERE expires_at <= ?').bind(Date.now()).run();
  return result.meta.changes;
}

// ── Registration: new account, or another passkey for an existing one ──

export async function registrationOptions(request, db, { account, displayName }) {
  const { rpID } = relyingParty(request);
  const kind = account ? 'add' : 'register';
  const accountId = account ? account.id : crypto.randomUUID();
  const name = account ? account.displayName : cleanDisplayName(displayName);

  let excludeCredentials = [];
  if (account) {
    const { results } = await db
      .prepare('SELECT id, transports FROM passkeys WHERE account_id = ?')
      .bind(account.id)
      .all();
    excludeCredentials = results.map(r => ({ id: r.id, transports: r.transports ? JSON.parse(r.transports) : undefined }));
  }

  const options = await generateRegistrationOptions({
    rpName: RP_NAME,
    rpID,
    userID: new TextEncoder().encode(accountId),
    userName: name,
    userDisplayName: name,
    attestationType: 'none',
    excludeCredentials,
    authenticatorSelection: { residentKey: 'required', userVerification: 'required' },
  });

  await saveChallenge(db, options.challenge, kind, accountId, name);
  return options;
}

// Returns the account the new passkey belongs to: { id, displayName }.
export async function verifyRegistration(request, db, { account, credential }) {
  const { rpID, origin } = relyingParty(request);
  const kind = account ? 'add' : 'register';

  let challenge = null;
  let verification;
  try {
    verification = await verifyRegistrationResponse({
      response: credential,
      expectedChallenge: async c => (challenge = await consumeChallenge(db, c, kind)) !== null,
      expectedOrigin: origin,
      expectedRPID: rpID,
      requireUserVerification: true,
    });
  } catch (e) {
    console.warn('Registration rejected:', e.message);
    throw new PasskeyError('Passkey registration failed');
  }
  if (!verification.verified) throw new PasskeyError('Passkey registration failed');
  if (account && challenge.account_id !== account.id) throw new PasskeyError('Passkey registration failed');

  const info = verification.registrationInfo;
  const now = Date.now();
  const statements = [];
  if (kind === 'register') {
    statements.push(
      db.prepare('INSERT INTO accounts (id, display_name, created_at, last_login_at) VALUES (?, ?, ?, ?)')
        .bind(challenge.account_id, challenge.display_name, now, now),
    );
  }
  statements.push(
    db.prepare(
      `INSERT INTO passkeys (id, account_id, public_key, counter, transports, device_type, backed_up, created_at, last_used_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      info.credential.id,
      challenge.account_id,
      isoBase64URL.fromBuffer(info.credential.publicKey),
      info.credential.counter,
      info.credential.transports ? JSON.stringify(info.credential.transports) : null,
      info.credentialDeviceType,
      info.credentialBackedUp ? 1 : 0,
      now,
      now,
    ),
  );
  await db.batch(statements);

  return { id: challenge.account_id, displayName: challenge.display_name };
}

// ── Sign-in ──

export async function authenticationOptions(request, db) {
  const { rpID } = relyingParty(request);
  const options = await generateAuthenticationOptions({ rpID, userVerification: 'required' });
  await saveChallenge(db, options.challenge, 'login', null, null);
  return options;
}

// Returns the signed-in account: { id, displayName }.
export async function verifyAuthentication(request, db, { credential }) {
  const { rpID, origin } = relyingParty(request);
  if (!credential || typeof credential.id !== 'string') throw new PasskeyError('Sign-in failed');

  const row = await db
    .prepare(
      `SELECT p.id, p.public_key, p.counter, p.transports, a.id AS account_id, a.display_name
         FROM passkeys p JOIN accounts a ON a.id = p.account_id
        WHERE p.id = ?`,
    )
    .bind(credential.id)
    .first();
  if (!row) throw new PasskeyError('Unknown passkey');

  // The authenticator reports which account the passkey was made for.
  const userHandle = credential.response && credential.response.userHandle;
  if (userHandle && userHandle !== isoBase64URL.fromBuffer(new TextEncoder().encode(row.account_id))) {
    throw new PasskeyError('Sign-in failed');
  }

  let verification;
  try {
    verification = await verifyAuthenticationResponse({
      response: credential,
      expectedChallenge: async c => (await consumeChallenge(db, c, 'login')) !== null,
      expectedOrigin: origin,
      expectedRPID: rpID,
      credential: {
        id: row.id,
        publicKey: isoBase64URL.toBuffer(row.public_key),
        counter: row.counter,
        transports: row.transports ? JSON.parse(row.transports) : undefined,
      },
      requireUserVerification: true,
    });
  } catch (e) {
    console.warn('Authentication rejected:', e.message);
    throw new PasskeyError('Sign-in failed');
  }
  if (!verification.verified) throw new PasskeyError('Sign-in failed');

  const now = Date.now();
  await db.batch([
    db.prepare('UPDATE passkeys SET counter = ?, last_used_at = ? WHERE id = ?')
      .bind(verification.authenticationInfo.newCounter, now, row.id),
    db.prepare('UPDATE accounts SET last_login_at = ? WHERE id = ?').bind(now, row.account_id),
  ]);

  return { id: row.account_id, displayName: row.display_name };
}
