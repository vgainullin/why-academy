// Why Academy — bug reports from debug mode
//
// Takes a screenshot of the page, lets you draw on it (pen) and black out
// anything private (Redact), collects diagnostics, and files a GitHub issue
// through /api/bugs. If filing fails, the report can be downloaded instead.
//
// The repo is public: the form says so, and both the screenshot and the
// diagnostics can be left out.

import { InkSurface, drawStroke } from './ink.js';

const H2C = 'https://cdn.jsdelivr.net/npm/html2canvas-pro@2.4.4/dist/html2canvas-pro.esm.js';
const MAX_SHOT_WIDTH = 1400;

// The visible page as a canvas, at most MAX_SHOT_WIDTH wide.
export async function captureScreen() {
  const { default: html2canvas } = await import(H2C);
  const scale = Math.min(window.devicePixelRatio || 1, MAX_SHOT_WIDTH / innerWidth, 2);
  return html2canvas(document.body, {
    scale,
    useCORS: true,
    logging: false,
    backgroundColor: getComputedStyle(document.body).backgroundColor || '#ffffff',
    x: window.scrollX,
    y: window.scrollY,
    width: innerWidth,
    height: innerHeight,
    windowWidth: innerWidth,
    windowHeight: innerHeight,
    // The report UI itself is not part of the picture.
    ignoreElements: el => el.id === 'dialog' || el.id === 'toast' || el.classList.contains('bug-fab'),
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/**
 * Opens the report dialog. opts: {
 *   dialog: <dialog> element, diagnostics(): object, toast(msg, isError, action),
 *   accountId: string | null, allowlisted: boolean
 * }
 */
export async function openBugReport(opts) {
  const { dialog: dlg, toast } = opts;
  let shot = null;
  try {
    shot = await captureScreen();
  } catch (e) {
    console.error('Screenshot failed', e);
    toast('Could not take a screenshot (' + e.message + '); you can still file the report.', true);
  }
  const diagnostics = opts.diagnostics();

  dlg.innerHTML = `<form method="dialog" class="dialog-form bug-form">
      <h3>Report a bug</h3>
      ${shot ? `<div class="bug-tools" role="toolbar" aria-label="Annotate">
        <button type="button" class="tool active" data-btool="pen">Draw</button>
        <button type="button" class="tool" data-btool="redact">Redact</button>
        <button type="button" class="tool" data-btool="eraser">Erase</button>
        <button type="button" class="btn-small" data-bact="undo">Undo</button>
        <span class="muted bug-hint">Circle the problem. Redact hides anything private.</span>
      </div>
      <div class="bug-shot"><img alt="Screenshot of the page"><div class="bug-ink"></div><canvas class="bug-redactions"></canvas></div>` : ''}
      <label>What went wrong? <input type="text" name="title" maxlength="120" required placeholder="Short summary, e.g. Explain shows no text"></label>
      <label>Details <textarea name="description" rows="4" placeholder="What you did, what you expected, what happened instead"></textarea></label>
      <label class="bug-check"><input type="checkbox" name="withShot" ${shot ? 'checked' : 'disabled'}> Attach the annotated screenshot</label>
      <label class="bug-check"><input type="checkbox" name="withDiag" checked> Attach diagnostics (errors, failed requests, AI calls, device)</label>
      <details class="bug-diag"><summary>See the diagnostics</summary><pre></pre></details>
      <p class="muted bug-public">This becomes an issue in the public GitHub repo. Redact anything you do not want to share.</p>
      ${opts.allowlisted ? '' : `<p class="dialog-status error">Filing needs your account on the testers list (account id <code>${escapeHtml(opts.accountId || 'not signed in')}</code>). You can still download the report.</p>`}
      <p class="dialog-status bug-status" role="status"></p>
      <div class="dialog-actions">
        <button type="button" class="btn btn-secondary" data-bact="download">Download instead</button>
        <span class="spacer"></span>
        <button value="cancel" class="btn btn-secondary" formnovalidate>Cancel</button>
        <button type="button" class="btn btn-primary" data-bact="file" ${opts.allowlisted ? '' : 'disabled'}>File on GitHub</button>
      </div>
    </form>`;
  dlg.querySelector('.bug-diag pre').textContent = JSON.stringify(diagnostics, null, 2);
  const status = dlg.querySelector('.bug-status');

  // ── Annotation ──
  const strokes = [];
  const redactions = []; // [x, y, w, h] normalized
  const history = []; // 'stroke' | 'redact'
  let surface = null;
  let tool = 'pen';
  const redactCanvas = dlg.querySelector('.bug-redactions');
  const paintRedactions = () => {
    if (!redactCanvas) return;
    const r = redactCanvas.getBoundingClientRect();
    redactCanvas.width = r.width;
    redactCanvas.height = r.height;
    const ctx = redactCanvas.getContext('2d');
    ctx.fillStyle = '#000';
    for (const [x, y, w, h] of redactions) ctx.fillRect(x * r.width, y * r.height, w * r.width, h * r.height);
  };
  if (shot) {
    const img = dlg.querySelector('.bug-shot img');
    img.src = shot.toDataURL('image/png');
    const box = dlg.querySelector('.bug-shot');
    // Keep the screenshot's proportions within the dialog's height budget.
    box.style.aspectRatio = `${shot.width} / ${shot.height}`;
    box.style.width = `min(100%, calc(52vh * ${shot.width / shot.height}))`;
    dlg.querySelector('.bug-tools').addEventListener('click', e => {
      const t = e.target.closest('[data-btool]');
      if (t) {
        tool = t.dataset.btool;
        dlg.querySelectorAll('[data-btool]').forEach(b => b.classList.toggle('active', b === t));
      }
      if (e.target.closest('[data-bact="undo"]')) {
        const last = history.pop();
        if (last === 'stroke') {
          strokes.pop();
          surface.setStrokes(strokes);
        } else if (last === 'redact') {
          redactions.pop();
          paintRedactions();
        }
      }
    });
    requestAnimationFrame(() => {
      surface = new InkSurface(dlg.querySelector('.bug-ink'), {
        allowTouch: true,
        getTool: () => ({ tool: tool === 'redact' ? 'region' : tool, color: '#dc2626', width: 0.004 }),
        onAdd: s => {
          strokes.push(s);
          history.push('stroke');
        },
        onErase: ids => {
          const gone = new Set(ids);
          for (let i = strokes.length - 1; i >= 0; i--) if (gone.has(strokes[i].id)) strokes.splice(i, 1);
        },
        onRegion: rect => {
          redactions.push(rect);
          history.push('redact');
          paintRedactions();
        },
      });
      paintRedactions();
    });
  }

  // The screenshot with drawings and redactions burned in.
  const composed = () => {
    if (!shot) return null;
    const c = document.createElement('canvas');
    c.width = shot.width;
    c.height = shot.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(shot, 0, 0);
    ctx.fillStyle = '#000';
    for (const [x, y, w, h] of redactions) ctx.fillRect(x * c.width, y * c.height, w * c.width, h * c.height);
    for (const s of strokes) drawStroke(ctx, s, c.width, c.height);
    return c.toDataURL('image/png');
  };

  const report = () => {
    const form = dlg.querySelector('form');
    return {
      title: form.title.value.trim(),
      description: form.description.value.trim(),
      area: 'reader',
      screenshot: form.withShot.checked ? composed() : null,
      diagnostics: form.withDiag.checked ? diagnostics : null,
    };
  };

  const download = () => {
    const r = report();
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const md = `# ${r.title || 'Bug report'}\n\n${r.description}\n\n` +
      (r.diagnostics ? '```json\n' + JSON.stringify(r.diagnostics, null, 2) + '\n```\n' : '');
    const save = (href, name) => {
      const a = document.createElement('a');
      a.href = href;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    };
    const mdUrl = URL.createObjectURL(new Blob([md], { type: 'text/markdown' }));
    save(mdUrl, `bug-${stamp}.md`);
    setTimeout(() => URL.revokeObjectURL(mdUrl), 30_000);
    if (r.screenshot) save(r.screenshot, `bug-${stamp}.png`);
  };

  dlg.querySelector('[data-bact="download"]').addEventListener('click', download);
  dlg.querySelector('[data-bact="file"]').addEventListener('click', async () => {
    const r = report();
    if (!r.title) {
      status.textContent = 'Give the bug a short title first.';
      status.classList.add('error');
      dlg.querySelector('[name=title]').focus();
      return;
    }
    const btn = dlg.querySelector('[data-bact="file"]');
    btn.disabled = true;
    status.classList.remove('error');
    status.textContent = 'Filing...';
    try {
      const resp = await fetch('/api/bugs', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(r),
      });
      const out = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(out.error || 'HTTP ' + resp.status);
      dlg.close('ok');
      toast(`Filed as issue #${out.issueNumber}`, false, { label: 'Open', run: () => window.open(out.issueUrl, '_blank', 'noopener') });
    } catch (e) {
      console.error('Filing the bug report failed', e);
      status.textContent = 'Could not file it: ' + e.message + '. Use "Download instead" to keep the report.';
      status.classList.add('error');
      btn.disabled = false;
    }
  });

  dlg.onclose = () => {
    if (surface) surface.destroy();
  };
  dlg.showModal();
  dlg.querySelector('[name=title]').focus();
}
