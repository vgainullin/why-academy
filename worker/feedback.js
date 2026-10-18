// Feedback ingestion: validated student feedback becomes a GitHub issue for
// the evolution agent. Only allowlisted accounts may submit. Anything that gets
// past this gate is agent input, so validation is aggressive.

const MAX_FEEDBACK_ENTRIES = 200;

// ALLOWED_USERS is a comma-separated list of account ids (wrangler.toml).
export function isUserAllowed(userId, allowedUsers) {
  if (!userId || !allowedUsers) return false;
  return allowedUsers.split(',').map(s => s.trim()).includes(userId);
}

// Returns { status, body } for the route to serialize.
export async function submitFeedback(env, user, body) {
  if (!body || !Array.isArray(body.feedback)) {
    return { status: 400, body: { error: 'Missing feedback array' } };
  }
  if (body.feedback.length === 0) {
    return { status: 400, body: { error: 'No feedback entries' } };
  }
  if (body.feedback.length > MAX_FEEDBACK_ENTRIES) {
    return { status: 400, body: { error: 'Too many feedback entries' } };
  }

  if (!isUserAllowed(user.id, env.ALLOWED_USERS)) {
    return { status: 403, body: { error: 'Not on trusted-tester list' } };
  }

  const limit = parseInt(env.RATE_LIMIT_PER_HOUR || '20', 10);
  if (!(await checkRateLimit(env.RATE_LIMIT, user.id, limit))) {
    return { status: 429, body: { error: 'Rate limit exceeded' } };
  }

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
    return { status: 400, body: { error: 'No valid feedback entries after sanitization' } };
  }

  const issue = await createGitHubIssue(env, user, sanitized);
  if (!issue) return { status: 502, body: { error: 'Failed to create issue' } };

  return {
    status: 200,
    body: { ok: true, issueNumber: issue.number, issueUrl: issue.html_url, accepted: sanitized.length },
  };
}

// Fixed one-hour window per account and scope, tracked in KV.
export async function checkRateLimit(kv, userId, limit, scope = 'rl') {
  if (!kv) throw new Error('RATE_LIMIT KV binding missing');
  const key = scope + ':' + userId;
  const current = await kv.get(key);
  const count = current ? parseInt(current, 10) : 0;
  if (count >= limit) return false;
  await kv.put(key, String(count + 1), { expirationTtl: 3600 });
  return true;
}

async function createGitHubIssue(env, user, feedback) {
  if (!env.GITHUB_TOKEN) {
    console.error('GITHUB_TOKEN not set');
    return null;
  }

  const title = '[feedback] ' + feedback.length + ' from ' + user.displayName +
    ' on ' + (feedback[0].lessonId || 'unknown lesson');

  const resp = await fetch('https://api.github.com/repos/' + env.GITHUB_REPO + '/issues', {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer ' + env.GITHUB_TOKEN,
      'Accept': 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'why-academy-worker',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify({
      title,
      body: formatIssueBody(user, feedback),
      labels: ['feedback', 'auto-generated'],
    }),
  });

  if (!resp.ok) {
    console.error('GitHub API error:', resp.status, await resp.text());
    return null;
  }
  return await resp.json();
}

function formatIssueBody(user, feedback) {
  let md = '## Feedback from ' + user.displayName + ' (account `' + user.id + '`)\n\n';
  md += '*Submitted at ' + new Date().toISOString() + '*\n\n';
  md += '---\n\n';

  const byLesson = {};
  for (const e of feedback) {
    const lid = e.lessonId || 'unknown';
    if (!byLesson[lid]) byLesson[lid] = {};
    if (!byLesson[lid][e.blockId]) byLesson[lid][e.blockId] = [];
    byLesson[lid][e.blockId].push(e);
  }

  for (const [lid, blocks] of Object.entries(byLesson)) {
    md += '### Lesson `' + lid + '`\n\n';
    for (const [bid, entries] of Object.entries(blocks)) {
      md += '**Block `' + bid + '`**\n\n';
      for (const e of entries) {
        md += '- **' + e.type + '**: ' + e.content + '\n';
        if (e.selection) md += '  > "' + e.selection + '"\n';
      }
      md += '\n';
    }
  }

  md += '\n---\n\n';
  md += '*This issue was created by the why-academy Worker. The evolution agent will pick this up on its next run.*\n';
  return md;
}
