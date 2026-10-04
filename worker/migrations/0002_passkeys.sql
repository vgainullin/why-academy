-- Passkey (WebAuthn) accounts replace Google sign-in.
-- Additive only: the Google-era users/sessions/settings tables from 0001 are
-- left in place, unused.

CREATE TABLE accounts (
  id            TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  last_login_at INTEGER NOT NULL
);

-- One row per passkey. id and public_key are base64url.
CREATE TABLE passkeys (
  id           TEXT PRIMARY KEY,
  account_id   TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  public_key   TEXT NOT NULL,
  counter      INTEGER NOT NULL,
  transports   TEXT,
  device_type  TEXT NOT NULL,
  backed_up    INTEGER NOT NULL,
  created_at   INTEGER NOT NULL,
  last_used_at INTEGER NOT NULL
);
CREATE INDEX passkeys_account_id ON passkeys(account_id);

-- Single-use WebAuthn challenges. kind: 'register' (new account),
-- 'add' (another passkey for account_id), 'login'.
CREATE TABLE webauthn_challenges (
  challenge    TEXT PRIMARY KEY,
  kind         TEXT NOT NULL,
  account_id   TEXT,
  display_name TEXT,
  expires_at   INTEGER NOT NULL
);
CREATE INDEX webauthn_challenges_expires_at ON webauthn_challenges(expires_at);

-- id is the SHA-256 hex of the cookie token; the raw token is never stored.
CREATE TABLE account_sessions (
  id         TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX account_sessions_account_id ON account_sessions(account_id);
CREATE INDEX account_sessions_expires_at ON account_sessions(expires_at);

CREATE TABLE account_settings (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
  data       TEXT NOT NULL,
  version    INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
