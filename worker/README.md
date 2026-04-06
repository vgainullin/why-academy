# why-academy-feedback worker

Cloudflare Worker that ingests student feedback from the Why Academy frontend and creates GitHub issues for the evolution agent to process.

## Security model

1. **Origin check** — only requests from `vgainullin.github.io` and localhost
2. **Google ID token verification** — full RS256 signature check against Google's public keys
3. **Allowlist** — only emails in the `ALLOWED_EMAILS` secret can submit feedback
4. **Rate limit** — 20 submissions per email per hour, tracked in KV
5. **Payload validation** — schema check, max 64KB, max 200 entries, sanitized fields

## Endpoints

- `POST /check` — verify ID token, return whether email is allowlisted (UI hint)
- `POST /feedback` — verify, allowlist, rate limit, create GitHub issue

Both endpoints expect `{ idToken: "<jwt>", ... }` in the JSON body.

## Deploy

```bash
cd worker

# 1. Create the KV namespace for rate limiting
npx wrangler kv namespace create RATE_LIMIT
# Copy the id from the output and paste into wrangler.toml

# 2. Set secrets
npx wrangler secret put GITHUB_TOKEN     # fine-grained PAT, repo:public_repo on vgainullin/why-academy
npx wrangler secret put ALLOWED_EMAILS   # comma-separated, e.g. "gainullin@gmail.com"

# 3. Deploy
npx wrangler deploy
```

After deploy, copy the worker URL (`https://why-academy-feedback.<subdomain>.workers.dev`) into `lib/auth.js` as `WORKER_URL`.

## Test

```bash
# Should return 401 (no token)
curl -X POST https://why-academy-feedback.<subdomain>.workers.dev/check \
  -H 'Content-Type: application/json' \
  -d '{}'

# Should return 200 with allowed: true if your token is valid and you're on the allowlist
curl -X POST https://why-academy-feedback.<subdomain>.workers.dev/check \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://vgainullin.github.io' \
  -d '{"idToken": "<paste real ID token from browser>"}'
```
