# why-academy worker

One Cloudflare Worker serves the whole site and its API. Static files come from Workers Static Assets. Only `/api/*` runs Worker code. The API shares the site's origin, so sessions use a first-party cookie.

## Accounts

- **Passkeys (WebAuthn), no identity provider.** "Create account" makes a discoverable passkey in the device or password manager (iCloud Keychain, Google Password Manager, 1Password, ...). "Sign in" uses it without a username. The Worker verifies it with `@simplewebauthn/server` and sets a session cookie. Page scripts never hold a token.
- **Ceremonies:** each one is `options` then `verify`. The challenge is stored in D1, single use, with a 5-minute TTL. User verification (biometric or device PIN) is required. Origin and RP ID must match the host that served the request.
- **Relying party = hostname.** Passkeys made on `why-academy.gainullin.workers.dev` do not work on any other host, including `localhost` or a future custom domain.
- **More devices:** passkeys usually sync within one ecosystem. For a device outside it, sign in on a device that has the passkey and click "Add passkey". Cross-device sign-in by phone QR also works.
- **Recovery:** none beyond your passkeys. If every passkey for an account is lost, the account is unreachable.
- **Session cookie:** `__Host-wa_session` is `HttpOnly; Secure; SameSite=Lax`. It holds 256 random bits. D1 stores only the token's SHA-256, so a leaked database contains no usable sessions. Sessions last 30 days and renew when used in their second half. Logout deletes the row. A daily cron removes expired rows.
- **CSRF:** `SameSite=Lax`, plus every non-GET request must carry an `Origin` header equal to the site's origin.
- **Who can sign up:** anyone. `ALLOWED_USERS` in `wrangler.toml` lists the account ids allowed to submit feedback. `/api/me` returns your id, which also shows as a tooltip on your name in the header.
- **Rate limits:** passkey requests are limited to 20/min per IP (each ceremony is 2 requests). Settings writes are limited to 60/min per account. Feedback is limited to 20/hour per account (KV).

## Settings sync

`lib/sync.js` mirrors selected localStorage keys into one JSON document per user, `GET`/`PUT /api/settings`:

| Data | Merge rule |
|---|---|
| Handwriting prefs (backend, endpoint, model, OpenRouter model, stroke width) | per-key last write wins, by timestamp |
| Playground progress | union; completed if completed anywhere |
| ROOTLOCK best streak | max |

Writes carry `baseVersion`. A stale write gets `409` with the current document. The client merges, then retries. The server validates every document against `SettingsSchema` (`worker/settings.js`) and caps it at 32 KB.

**The OpenRouter API key is never synced.** It stays in the browser that entered it, and the server schema rejects it.

## Study vault (reader)

`reader.html` keeps notes, PDF marks, ink, cards and tasks as items in `vault_items` (D1) and the PDFs in R2 (`pdf/<account_id>/<sha256>`). The browser writes to IndexedDB first, so reading and annotating work offline; `lib/vault/store.js` pushes dirty items and pulls newer ones.

| Data | Merge rule |
|---|---|
| Notes, marks, cards, tasks, paper metadata | last write wins per item, by client edit time; a losing note edit is kept as a "(conflict copy)" note |
| Ink (one item per PDF page) | stroke union minus erased strokes, merged on the server, so two devices inking offline both keep their strokes |

Every accepted write gets the next per-account `seq`; clients pull with `seq > cursor`. A push that loses returns the stored copy (`stale`) so the client can resolve it. The server validates each kind (`worker/vault.js`) and caps item sizes, PDFs at 64 MB and storage at 4 GB per account. An upload must hash to the SHA-256 in its URL.

AI actions (equation to LaTeX, explanations, card drafts, handwriting to text) call the backend from Settings directly from the browser; the Worker never sees the API key.

## Endpoints

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/auth/register/options`, `.../verify` | none | create account + passkey, then session |
| `POST /api/auth/login/options`, `.../verify` | passkey | create session |
| `POST /api/passkeys/options`, `.../verify` | session | add a passkey to the current account |
| `POST /api/auth/logout` | session | end session |
| `GET /api/me` | session | current user + feedback allowlist flag |
| `GET /api/settings` | session | synced settings |
| `PUT /api/settings` | session | replace settings (`{ data, baseVersion }`) |
| `POST /api/feedback` | session + allowlist | feedback -> GitHub issue |
| `POST /api/vault/push` | session | write vault items (`{ items }`, up to 200) |
| `GET /api/vault/pull?since=N` | session | vault items with `seq > N`, paged |
| `HEAD/GET/PUT/DELETE /api/vault/files/:sha256` | session | PDF bytes in R2 |

## Public files

`scripts/build-site.mjs` copies the git-tracked (or staged) files under an allowlist of paths into `dist/`: the HTML pages, their scripts and styles, `lib/` and `lessons/`. New files must be `git add`ed before they deploy. Only `dist/` is uploaded. Wrangler runs the build before every deploy and on changes during `wrangler dev`. A new top-level public file must be added to that list.

## Local development

```bash
npm install
npm run db:migrate:local
npm run dev        # http://localhost:8787
```

WebAuthn and the `Secure` cookie both work on `http://localhost` in Chrome and Firefox. Local passkeys are separate from production ones.

To test feedback locally, put `ALLOWED_USERS=<your local account id>` in `worker/.dev.vars`.

## Deploy

```bash
npx wrangler login

# 1. Create the database, paste its id into wrangler.toml (database_id)
npx wrangler d1 create why-academy
npm run db:migrate:remote

# 2. R2 bucket for vault PDFs
npx wrangler r2 bucket create why-academy-vault

# 3. Secret for feedback issues
npx wrangler secret put GITHUB_TOKEN -c worker/wrangler.toml   # fine-grained PAT, issues on vgainullin/why-academy

# 4. Deploy
npm run deploy
```

There is no identity-provider setup. To enable feedback for an account, add its id to `ALLOWED_USERS` in `wrangler.toml` and deploy.
