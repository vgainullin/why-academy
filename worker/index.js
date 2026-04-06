// Why Academy — Feedback Ingestion Worker
//
// Endpoints:
//   POST /check     - verify ID token + return whether email is allowlisted (UI hint)
//   POST /feedback  - verify ID token + allowlist + rate limit + create GitHub issue
//
// All requests require a valid Google ID token in the body.
// "AI proposes, SymPy disposes" — this worker is a strict gatekeeper. Any
// content that gets past it becomes input for the evolution agent, so we
// validate aggressively here.

const ALLOWED_ORIGINS = [
  'https://vgainullin.github.io',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
];

const MAX_PAYLOAD_BYTES = 64 * 1024; // 64KB
const MAX_FEEDBACK_ENTRIES = 200;

// ── Entry point ──
export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get('Origin') || '';
    const corsHeaders = makeCorsHeaders(origin);

    // Reject disallowed origins (except for direct curl tests with no Origin)
    if (origin && !ALLOWED_ORIGINS.includes(origin)) {
      return json({ error: 'Origin not allowed' }, 403, corsHeaders);
    }

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders });
    }

    const url = new URL(request.url);

    try {
      if (request.method === 'POST' && url.pathname === '/check') {
        return await handleCheck(request, env, corsHeaders);
      }
      if (request.method === 'POST' && url.pathname === '/feedback') {
        return await handleFeedback(request, env, corsHeaders);
      }
      return json({ error: 'Not found' }, 404, corsHeaders);
    } catch (e) {
      console.error('Worker error:', e);
      return json({ error: 'Internal error' }, 500, corsHeaders);
    }
  }
};

// ── /check ──
// Verify the ID token and tell the client whether the user is allowlisted.
// This is a UX hint — clients can lie about it; the real enforcement is in
// /feedback. But since we're doing the work to verify the token anyway,
// might as well return the answer.
async function handleCheck(request, env, corsHeaders) {
  const body = await safeJson(request);
  if (!body || !body.idToken) {
    return json({ error: 'Missing idToken' }, 400, corsHeaders);
  }

  const claims = await verifyGoogleIdToken(body.idToken, env.OAUTH_CLIENT_ID);
  if (!claims) {
    return json({ error: 'Invalid token' }, 401, corsHeaders);
  }

  const allowed = isEmailAllowed(claims.email, env.ALLOWED_EMAILS);
  return json({
    allowed: allowed,
    email: claims.email,
  }, 200, corsHeaders);
}

// ── /feedback ──
async function handleFeedback(request, env, corsHeaders) {
  // Size check before parsing
  const contentLength = parseInt(request.headers.get('Content-Length') || '0', 10);
  if (contentLength > MAX_PAYLOAD_BYTES) {
    return json({ error: 'Payload too large' }, 413, corsHeaders);
  }

  const body = await safeJson(request);
  if (!body || !body.idToken || !Array.isArray(body.feedback)) {
    return json({ error: 'Missing idToken or feedback array' }, 400, corsHeaders);
  }

  if (body.feedback.length === 0) {
    return json({ error: 'No feedback entries' }, 400, corsHeaders);
  }

  if (body.feedback.length > MAX_FEEDBACK_ENTRIES) {
    return json({ error: 'Too many feedback entries' }, 400, corsHeaders);
  }

  // Verify token
  const claims = await verifyGoogleIdToken(body.idToken, env.OAUTH_CLIENT_ID);
  if (!claims) {
    return json({ error: 'Invalid token' }, 401, corsHeaders);
  }

  // Allowlist check
  if (!isEmailAllowed(claims.email, env.ALLOWED_EMAILS)) {
    return json({ error: 'Not on trusted-tester list' }, 403, corsHeaders);
  }

  // Rate limit
  const limit = parseInt(env.RATE_LIMIT_PER_HOUR || '20', 10);
  const rateOk = await checkRateLimit(env.RATE_LIMIT, claims.email, limit);
  if (!rateOk) {
    return json({ error: 'Rate limit exceeded' }, 429, corsHeaders);
  }

  // Validate and sanitize each entry
  const sanitized = [];
  for (const entry of body.feedback) {
    if (!entry || typeof entry !== 'object') continue;
    if (!entry.blockId || !entry.type || !entry.content) continue;
    if (!['flag', 'question', 'comment'].includes(entry.type)) continue;
    sanitized.push({
      blockId: String(entry.blockId).slice(0, 64),
      lessonId: String(entry.lessonId || '').slice(0, 64),
      type: entry.type,
      content: String(entry.content).slice(0, 4000),
      selection: entry.selection ? String(entry.selection).slice(0, 1000) : null,
      timestamp: String(entry.timestamp || new Date().toISOString()).slice(0, 32),
    });
  }

  if (sanitized.length === 0) {
    return json({ error: 'No valid feedback entries after sanitization' }, 400, corsHeaders);
  }

  // Create GitHub issue
  const issue = await createGitHubIssue(env, claims, sanitized);
  if (!issue) {
    return json({ error: 'Failed to create issue' }, 502, corsHeaders);
  }

  return json({
    ok: true,
    issueNumber: issue.number,
    issueUrl: issue.html_url,
    accepted: sanitized.length,
  }, 200, corsHeaders);
}

// ── Google ID token verification ──
// Verifies cryptographic signature, audience, expiration, issuer.
// Returns parsed claims on success, null on failure.
async function verifyGoogleIdToken(idToken, expectedAudience) {
  if (!idToken || typeof idToken !== 'string') return null;

  const parts = idToken.split('.');
  if (parts.length !== 3) return null;

  let header, payload;
  try {
    header = JSON.parse(b64urlDecode(parts[0]));
    payload = JSON.parse(b64urlDecode(parts[1]));
  } catch {
    return null;
  }

  // Audience check
  if (payload.aud !== expectedAudience) {
    console.warn('aud mismatch:', payload.aud, '!=', expectedAudience);
    return null;
  }

  // Issuer check
  if (payload.iss !== 'https://accounts.google.com' && payload.iss !== 'accounts.google.com') {
    console.warn('iss mismatch:', payload.iss);
    return null;
  }

  // Expiration check (with 30s clock skew)
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp + 30 < now) {
    console.warn('Token expired:', payload.exp, '<', now);
    return null;
  }

  // Email verified check
  if (!payload.email_verified) {
    console.warn('Email not verified');
    return null;
  }

  // Signature verification
  const verified = await verifySignature(idToken, header.kid);
  if (!verified) {
    console.warn('Signature verification failed');
    return null;
  }

  return {
    email: payload.email,
    name: payload.name,
    sub: payload.sub,
  };
}

// Fetch Google's public keys and verify RS256 signature.
async function verifySignature(idToken, kid) {
  try {
    const certsResp = await fetch('https://www.googleapis.com/oauth2/v3/certs', {
      cf: { cacheTtl: 3600, cacheEverything: true }
    });
    if (!certsResp.ok) return false;
    const certs = await certsResp.json();
    const key = certs.keys.find(k => k.kid === kid);
    if (!key) return false;

    // Import JWK
    const cryptoKey = await crypto.subtle.importKey(
      'jwk',
      key,
      { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' },
      false,
      ['verify']
    );

    const parts = idToken.split('.');
    const data = new TextEncoder().encode(parts[0] + '.' + parts[1]);
    const sig = b64urlToUint8(parts[2]);

    return await crypto.subtle.verify('RSASSA-PKCS1-v1_5', cryptoKey, sig, data);
  } catch (e) {
    console.error('Signature verification error:', e);
    return false;
  }
}

// ── Allowlist ──
function isEmailAllowed(email, allowedEmails) {
  if (!email || !allowedEmails) return false;
  const list = allowedEmails.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  return list.includes(email.toLowerCase());
}

// ── Rate limiting ──
// Simple sliding window via KV: key per email, value = count, TTL = 1 hour
async function checkRateLimit(kv, email, limit) {
  if (!kv) return true; // No KV bound, skip rate limiting
  const key = 'rl:' + email.toLowerCase();
  const current = await kv.get(key);
  const count = current ? parseInt(current, 10) : 0;
  if (count >= limit) return false;
  // Increment with 1-hour TTL
  await kv.put(key, String(count + 1), { expirationTtl: 3600 });
  return true;
}

// ── GitHub issue creation ──
async function createGitHubIssue(env, claims, feedback) {
  const repo = env.GITHUB_REPO;
  const token = env.GITHUB_TOKEN;
  if (!token) {
    console.error('GITHUB_TOKEN not set');
    return null;
  }

  const title = '[feedback] ' + feedback.length + ' from ' + claims.email +
    ' on ' + (feedback[0].lessonId || 'unknown lesson');

  const body = formatIssueBody(claims, feedback);

  const resp = await fetch('https://api.github.com/repos/' + repo + '/issues', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + token,
      'Accept': 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'why-academy-feedback-worker',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify({
      title: title,
      body: body,
      labels: ['feedback', 'auto-generated'],
    }),
  });

  if (!resp.ok) {
    const errText = await resp.text();
    console.error('GitHub API error:', resp.status, errText);
    return null;
  }
  return await resp.json();
}

function formatIssueBody(claims, feedback) {
  let md = '## Feedback from ' + claims.name + ' (' + claims.email + ')\n\n';
  md += '*Submitted at ' + new Date().toISOString() + '*\n\n';
  md += '---\n\n';

  // Group by lesson, then by block
  const byLesson = {};
  for (const e of feedback) {
    const lid = e.lessonId || 'unknown';
    if (!byLesson[lid]) byLesson[lid] = {};
    const bid = e.blockId;
    if (!byLesson[lid][bid]) byLesson[lid][bid] = [];
    byLesson[lid][bid].push(e);
  }

  for (const [lid, blocks] of Object.entries(byLesson)) {
    md += '### Lesson `' + lid + '`\n\n';
    for (const [bid, entries] of Object.entries(blocks)) {
      md += '**Block `' + bid + '`**\n\n';
      for (const e of entries) {
        const icon = e.type === 'flag' ? '🚩' : e.type === 'question' ? '❓' : '✏️';
        md += '- ' + icon + ' **' + e.type + '**: ' + e.content + '\n';
        if (e.selection) {
          md += '  > "' + e.selection + '"\n';
        }
      }
      md += '\n';
    }
  }

  md += '\n---\n\n';
  md += '*This issue was created by the why-academy-feedback Worker. The evolution agent will pick this up on its next run.*\n';
  return md;
}

// ── Helpers ──
function makeCorsHeaders(origin) {
  const headers = {
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
  };
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Vary'] = 'Origin';
  }
  return headers;
}

function json(body, status, extraHeaders) {
  return new Response(JSON.stringify(body), {
    status: status,
    headers: {
      'Content-Type': 'application/json',
      ...(extraHeaders || {}),
    },
  });
}

async function safeJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function b64urlDecode(str) {
  // base64url -> base64 -> string
  let s = str.replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  return atob(s);
}

function b64urlToUint8(str) {
  const bin = b64urlDecode(str);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}
