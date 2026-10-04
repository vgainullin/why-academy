// Shared response/request helpers for the API routes.

export function json(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
      ...extraHeaders,
    },
  });
}

// Reads a JSON body, enforcing a byte cap on the actual bytes received
// (Content-Length can be absent or wrong). Returns { body } or { error }.
export async function readJson(request, maxBytes) {
  const declared = parseInt(request.headers.get('Content-Length') || '0', 10);
  if (declared > maxBytes) return { error: json({ error: 'Payload too large' }, 413) };
  const text = await request.text();
  if (new TextEncoder().encode(text).length > maxBytes) {
    return { error: json({ error: 'Payload too large' }, 413) };
  }
  try {
    return { body: JSON.parse(text) };
  } catch {
    return { error: json({ error: 'Invalid JSON' }, 400) };
  }
}

// CSRF guard for state-changing requests. The session cookie is SameSite=Lax,
// which already blocks cross-site POST/PUT; this rejects anything that does
// not come from our own origin (or omits Origin entirely) as a second layer.
export function isSameOrigin(request) {
  const origin = request.headers.get('Origin');
  return !!origin && origin === new URL(request.url).origin;
}

export function clientIp(request) {
  return request.headers.get('CF-Connecting-IP') || 'unknown';
}
