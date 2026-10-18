// Bug reports from the app's debug mode: a title, a description, an
// annotated screenshot and diagnostics become a GitHub issue. Only
// allowlisted accounts may file (ALLOWED_USERS), since the repo is public.
//
// Screenshots are stored in R2 under an unguessable id and served without a
// session at /api/bugshots/<id>.png, so GitHub can show them in the issue.

import { isUserAllowed, checkRateLimit } from './feedback.js';

export const MAX_REPORT_BYTES = 6 * 1024 * 1024;
const MAX_SHOT_BYTES = 4 * 1024 * 1024;
const MAX_DIAGNOSTICS_CHARS = 60_000;
export const SHOT_ID = /^[0-9a-f]{32}$/;
const PNG_MAGIC = [0x89, 0x50, 0x4e, 0x47];

export function shotKey(id) {
  return 'bugshots/' + id + '.png';
}

function randomId() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return [...b].map(x => x.toString(16).padStart(2, '0')).join('');
}

function decodeBase64(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// Validates a report body. Returns { report } or { error }.
export function validateReport(body) {
  if (!body || typeof body !== 'object') return { error: 'Missing report' };
  const title = String(body.title || '').trim();
  if (!title) return { error: 'A title is required' };
  const report = {
    title: title.slice(0, 120),
    description: String(body.description || '').slice(0, 8000),
    area: String(body.area || 'reader').replace(/[^a-z0-9-]/gi, '').slice(0, 32) || 'reader',
    diagnostics: null,
    screenshot: null,
  };
  if (body.diagnostics !== undefined && body.diagnostics !== null) {
    const text = JSON.stringify(body.diagnostics, null, 2);
    report.diagnostics = text.length > MAX_DIAGNOSTICS_CHARS ? text.slice(0, MAX_DIAGNOSTICS_CHARS) + '\n... (truncated)' : text;
  }
  if (body.screenshot) {
    const m = /^data:image\/png;base64,([A-Za-z0-9+/=]+)$/.exec(String(body.screenshot));
    if (!m) return { error: 'Screenshot must be a PNG data URL' };
    const bytes = decodeBase64(m[1]);
    if (bytes.length > MAX_SHOT_BYTES) return { error: 'Screenshot too large' };
    if (!PNG_MAGIC.every((v, i) => bytes[i] === v)) return { error: 'Screenshot is not a PNG' };
    report.screenshot = bytes;
  }
  return { report };
}

// Markdown for the issue. Diagnostics go in a collapsed block. The fence is
// longer than any backtick run inside, so the JSON cannot break out of it.
export function formatReport(report, user, shotUrl) {
  let md = '';
  md += report.description.trim() ? report.description.trim() + '\n\n' : '_No description._\n\n';
  if (shotUrl) md += `![Annotated screenshot](${shotUrl})\n\n`;
  md += `Reported from the app (${report.area}) by account \`${user.id}\` at ${new Date().toISOString()}.\n`;
  if (report.diagnostics) {
    const longest = Math.max(2, ...(report.diagnostics.match(/`+/g) || []).map(r => r.length));
    const fence = '`'.repeat(longest + 1);
    md += `\n<details><summary>Diagnostics</summary>\n\n${fence}json\n${report.diagnostics}\n${fence}\n\n</details>\n`;
  }
  return md;
}

// Returns { status, body }.
export async function fileBugReport(env, request, user, body) {
  if (!isUserAllowed(user.id, env.ALLOWED_USERS)) {
    return { status: 403, body: { error: 'Bug reports are limited to trusted testers. Your account id: ' + user.id } };
  }
  if (!(await checkRateLimit(env.RATE_LIMIT, user.id, 30, 'bugs'))) {
    return { status: 429, body: { error: 'Too many reports this hour' } };
  }
  const { report, error } = validateReport(body);
  if (error) return { status: 400, body: { error } };
  if (!env.GITHUB_TOKEN) return { status: 502, body: { error: 'GitHub token not configured on the server' } };

  let shotUrl = null;
  if (report.screenshot) {
    const id = randomId();
    await env.VAULT_FILES.put(shotKey(id), report.screenshot, { httpMetadata: { contentType: 'image/png' } });
    shotUrl = new URL('/api/bugshots/' + id + '.png', request.url).href;
  }

  const resp = await fetch('https://api.github.com/repos/' + env.GITHUB_REPO + '/issues', {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + env.GITHUB_TOKEN,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'why-academy-worker',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify({
      title: '[bug] ' + report.title,
      body: formatReport(report, user, shotUrl),
      labels: ['bug', 'from-app', report.area],
    }),
  });
  if (!resp.ok) {
    const detail = (await resp.text()).slice(0, 300);
    console.error('GitHub issue creation failed', resp.status, detail);
    return { status: 502, body: { error: 'GitHub refused the issue (HTTP ' + resp.status + ')', detail } };
  }
  const issue = await resp.json();
  return { status: 200, body: { ok: true, issueNumber: issue.number, issueUrl: issue.html_url } };
}
