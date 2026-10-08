// Reader regression suite: deterministic browser checks at iPad portrait
// size against an isolated server (see scripts/e2e_reader.sh). Each check
// pins a bug or feature found by the LLM feature tester. OpenRouter is
// stubbed, so no key or network access is needed.
//
// Env: E2E_ORIGIN, E2E_TOKEN, E2E_FIXTURE (PDF path), E2E_OUT (screenshots).

import { chromium } from 'playwright-core';
import { readFileSync } from 'node:fs';

const ROOT = new URL('../..', import.meta.url).pathname;
const B = process.env.E2E_ORIGIN;
const token = process.env.E2E_TOKEN;
const FIXTURE = process.env.E2E_FIXTURE;
const FIXTURE_PLAIN = process.env.E2E_FIXTURE_PLAIN;
const OUT = process.env.E2E_OUT || '.';
if (!B || !token || !FIXTURE) throw new Error('Run through scripts/e2e_reader.sh');
const kit = `const __WA_CONFIG = ${JSON.stringify({ token, origin: B, openrouterKey: 'sk-or-test' })};\n` + readFileSync(ROOT + 'scripts/feature_test/testkit.js', 'utf8');

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await browser.newContext({ viewport: { width: 834, height: 1194 }, hasTouch: true, deviceScaleFactor: 2 });
await ctx.addInitScript(kit);
let slowDraft = false;
let streamed = 0;
let failExplain = true;
await ctx.route('https://openrouter.ai/**', async route => {
  const body = JSON.parse(route.request().postData());
  const last = body.messages[body.messages.length - 1].content;
  const text = typeof last === 'string' ? last : last.find(p => p.type === 'text').text;
  if (text.includes('not yet understood') && failExplain) {
    failExplain = false;
    return route.fulfill({ status: 500, body: 'upstream overloaded' });
  }
  let reply = 'UNEXPECTED';
  if (text.startsWith('Transcribe the mathematics')) reply = 'Var( q .k / \\text{sqrt}(d\\_k) ) = d\\_k / d\\_k = 1';
  else if (text.includes('FRONT:') && slowDraft) {
    await new Promise(r => setTimeout(r, 2500));
    reply = 'FRONT:\nDrafted question?\nBACK:\nDrafted answer.';
  } else if (text.includes('FRONT:')) reply = 'FRONT:\nWhy is $\\operatorname{Var}(q \\cdot k / \\sqrt{d_k}) = 1$ with $\\delta_{ij}$?\nBACK:\nVar scales by $1/d_k$.';
  else if (text.includes('not yet understood')) reply = '1. **In plain terms** - saturation.';
  if (body.stream) {
    // Server-sent events, in pieces, like OpenRouter.
    const pieces = reply.match(/.{1,6}/gs) || [''];
    const sse = pieces.map(p => `data: ${JSON.stringify({ choices: [{ delta: { content: p } }] })}\n\n`).join('') + 'data: [DONE]\n\n';
    streamed++;
    return route.fulfill({ status: 200, headers: { 'Content-Type': 'text/event-stream' }, body: sse });
  }
  await route.fulfill({ json: { choices: [{ message: { content: reply } }] } });
});

const page = await ctx.newPage();
const errors = [];
page.on('pageerror', e => errors.push('pageerror: ' + e.message + ' @ ' + ((e.stack || '').split('\n').find(l => /reader\.js|lib\//.test(l)) || '').trim()));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
page.on('dialog', d => d.accept());
const shot = n => page.screenshot({ path: `${OUT}/${n}.png` });
let failures = 0;
const check = (name, ok, extra = '') => {
  if (!ok) failures++;
  console.log((ok ? 'PASS ' : 'FAIL ') + name + (extra ? ' -- ' + extra : ''));
};
const wait = ms => page.waitForTimeout(ms);
const visibleAt = sel => page.evaluate(sel => {
  const el = document.querySelector(sel);
  if (!el) return 'missing';
  const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return hit && (hit === el || el.contains(hit) || hit.closest('.pdf-page') === el.closest('.pdf-page')) ? 'visible' : 'covered by ' + (hit ? hit.className || hit.tagName : 'nothing');
}, sel);

try {
  await page.goto(B + '/reader');
  await page.waitForFunction(() => document.querySelector('#sync-status').dataset.state === 'synced');
  check('empty view shows the library', await page.evaluate(() => !document.body.classList.contains('sidebar-closed')));
  check('sync status visible in portrait', await page.evaluate(() => {
    const r = document.querySelector('#sync-status').getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }));

  await page.setInputFiles('#file-input', FIXTURE);
  await page.waitForSelector('.pdf-page[data-page="1"] .textLayer span');
  check('import logs no console error', !errors.some(e => /404/.test(e)), errors.join(' | '));
  const toolbarRows = await page.evaluate(() => {
    const t = document.querySelector('.doc-toolbar');
    return Math.round(t.getBoundingClientRect().height);
  });
  check('toolbar is one row', toolbarRows < 60, toolbarRows + 'px');

  // Contents from the PDF outline: lists sections, jumps, tracks the current one
  await page.click('#toggle-contents');
  await page.waitForSelector('#panel .toc li');
  const toc = await page.locator('#panel .toc-title').allTextContents();
  check('contents lists the outline', toc.length === 6 && toc[2].includes('Why saturation hurts'), toc.join(' | '));
  await page.locator('#panel .toc-item', { hasText: 'Why saturation hurts' }).click();
  await wait(1200);
  check('contents entry jumps to its section', (await page.inputValue('#page-input')) === '2', 'page ' + await page.inputValue('#page-input'));
  await page.click('#toggle-contents');
  await page.waitForSelector('#panel .toc li.current');
  check('current section highlighted', (await page.textContent('#panel .toc li.current .toc-title')).includes('Why saturation hurts'), await page.textContent('#panel .toc li.current .toc-title'));
  await page.click('#panel .panel-close');
  await page.fill('#page-input', '1');
  await page.dispatchEvent('#page-input', 'change');
  await wait(500);

  // panel closable
  await page.click('#toggle-panel');
  await page.waitForSelector('#panel:not(.hidden)');
  await shot('panel');
  await page.click('#panel .panel-close');
  check('panel closes from inside', await page.evaluate(() => document.querySelector('#panel').classList.contains('hidden')));
  await page.click('#toggle-panel');
  await page.keyboard.press('Escape');
  check('Escape closes panel', await page.evaluate(() => document.querySelector('#panel').classList.contains('hidden')));

  // reload returns to last page
  await page.fill('#page-input', '3');
  await page.dispatchEvent('#page-input', 'change');
  await wait(800);
  await page.reload();
  await page.waitForSelector('.pdf-page .textLayer span');
  await wait(800);
  check('reload reopens at the last page', (await page.inputValue('#page-input')) === '3', 'page ' + await page.inputValue('#page-input'));
  check('reload resumes the paper', (await page.evaluate(() => location.hash)).startsWith('#doc='));

  // Cross-span selection + Explain (first attempt fails) -> unclear status
  await page.fill('#page-input', '1');
  await page.dispatchEvent('#page-input', 'change');
  await wait(600);
  await page.click('.tool[data-tool="select"]');
  const sel = await page.evaluate(() => __wa.selectText(1, 'softmax saturates, and gradients vanish'));
  check('kit selects across text runs', sel.includes('gradients vanish'), JSON.stringify(sel));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Explain")');
  await page.waitForSelector('#toast.error');
  await wait(300);
  await page.click('#toggle-panel');
  await page.waitForSelector('#panel .tag-unclear');
  check('explained passage is marked "Not clear yet"', true);
  await page.click('#panel [data-filter="unclear"]');
  check('filter shows unclear marks', (await page.locator('#panel .mark').count()) === 1);
  await page.click('#panel .panel-close');

  // Question with context
  await page.fill('#page-input', '3');
  await page.dispatchEvent('#page-input', 'change');
  await wait(800);
  await page.evaluate(() => __wa.selectText(3, 'does the argument still hold when q and k are correlated'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Question")');
  await page.waitForSelector('dialog[open] .dialog-context');
  check('question dialog shows the passage', (await page.textContent('dialog .dialog-context')).includes('correlated'));
  await page.fill('dialog textarea', 'Does it hold after training?');
  await page.click('dialog button[value="ok"]');

  // equation LaTeX tidy
  await page.click('.tool[data-tool="region"]');
  await page.fill('#page-input', '2');
  await page.dispatchEvent('#page-input', 'change');
  await wait(600);
  await page.evaluate(() => __wa.dragOnPage(2, 0.12, 0.3, 0.9, 0.36));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Equation card")');
  await page.waitForFunction(() => document.querySelector('dialog [name=front]')?.value.length > 0);
  check('card draft with raw LaTeX parsed', (await page.inputValue('dialog [name=front]')).includes('\\delta_{ij}'), await page.inputValue('dialog [name=front]'));
  // empty front keeps the editor open
  await page.fill('dialog [name=front]', '');
  await page.click('dialog button[value="ok"]');
  check('empty front keeps the card editor open', await page.evaluate(() => document.querySelector('#dialog').open));
  await page.fill('dialog [name=front]', 'Why unit variance?');
  await page.click('dialog button[value="ok"]');
  const serverAnnos = async n => {
    for (let i = 0; i < 20; i++) {
      const list = (await page.evaluate(() => __wa.serverItems('anno'))).filter(a => !a.deleted);
      if (list.length >= n) return list;
      await wait(500);
    }
    return (await page.evaluate(() => __wa.serverItems('anno'))).filter(a => !a.deleted);
  };
  const withLatex = (await serverAnnos(3)).map(a => a.data.latex).filter(Boolean)[0] || '';
  check('LaTeX tidied', withLatex && !withLatex.includes('\\_') && withLatex.includes('\\sqrt{d_k}'), withLatex);

  // Region over the same equation reuses the mark; cancel leaves nothing
  const annosBefore = (await serverAnnos(3)).length;
  await page.evaluate(() => __wa.dragOnPage(2, 0.12, 0.3, 0.9, 0.36));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Comment")');
  await page.click('dialog button[value="cancel"]');
  await page.click('.tool[data-tool="select"]');
  await page.evaluate(() => __wa.selectText(2, 'little gradient reaches'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Comment")');
  await page.click('dialog button[value="cancel"]');
  await wait(2500);
  const annosAfter = (await page.evaluate(() => __wa.serverItems('anno'))).filter(a => !a.deleted).length;
  check('cancelled actions leave no marks', annosAfter === annosBefore, `${annosBefore} -> ${annosAfter}`);

  // (dialogs) close on navigation
  await page.evaluate(() => __wa.selectText(2, 'little gradient reaches'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Question")');
  await page.waitForSelector('dialog[open]');
  await page.evaluate(() => { location.hash = '#study'; });
  await wait(500);
  check('dialog closes on navigation', !(await page.evaluate(() => document.querySelector('#dialog').open)));
  await page.goBack();
  await page.waitForSelector('.pdf-page .textLayer span');

  // notebook ink with Select tool
  await page.click('.tool[data-tool="select"]');
  await page.click('#toggle-notebook');
  await page.waitForSelector('#doc-notebook .note-add');
  await page.click('#doc-notebook [data-add="ink"]');
  await page.waitForSelector('#doc-notebook .ink-pad');
  await wait(300);
  await page.evaluate(() => __wa.penInPad(0));
  await page.evaluate(() => __wa.penInPad(0, [[0.1, 0.7], [0.6, 0.8]], 'touch'));
  let nbStrokes = 0;
  for (let i = 0; i < 16 && !nbStrokes; i++) {
    await wait(500);
    nbStrokes = await page.evaluate(async () => (await __wa.serverItems('note')).filter(n => n.data.notebookFor)
      .flatMap(n => n.data.blocks).filter(b => b.type === 'ink').reduce((k, b) => k + b.strokes.length, 0));
  }
  await wait(1500);
  nbStrokes = await page.evaluate(async () => (await __wa.serverItems('note')).filter(n => n.data.notebookFor)
    .flatMap(n => n.data.blocks).filter(b => b.type === 'ink').reduce((k, b) => k + b.strokes.length, 0));
  check('pen draws in notebook with Select tool; finger does not', nbStrokes === 1, nbStrokes + ' strokes');

  // A stroke that runs far off the pad (pointer capture keeps reporting) still syncs
  await page.evaluate(() => __wa.penInPad(0, [[0.3, 0.5], [0.35, 1.2], [0.4, 3.5]]));
  let offPad = 0;
  for (let i = 0; i < 16 && offPad < 2; i++) {
    await wait(500);
    offPad = await page.evaluate(async () => (await __wa.serverItems('note')).filter(n => n.data.notebookFor)
      .flatMap(n => n.data.blocks).filter(b => b.type === 'ink').reduce((k, b) => k + b.strokes.length, 0));
  }
  check('stroke dragged off the pad syncs (clamped)', offPad === 2 && !/rejected/.test(await page.textContent('#sync-status')), `${offPad} strokes, status "${await page.textContent('#sync-status')}"`);
  // portrait panel overlays instead of squeezing the toolbar
  await page.click('#toggle-panel');
  await wait(400);
  const tb = await page.evaluate(() => ({ w: document.querySelector('.doc-toolbar').clientWidth, vw: innerWidth }));
  check('panel overlays in portrait (toolbar keeps full width)', tb.w >= tb.vw - 2, JSON.stringify(tb));
  const reachable = await page.evaluate(() => ['#toggle-panel', '#toggle-contents', '#open-brief', '#zoom-in'].map(sel => {
    const b = document.querySelector(sel).getBoundingClientRect();
    const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return hit && hit.closest(sel) ? 'ok' : sel;
  }).filter(x => x !== 'ok'));
  check('toolbar stays reachable with the panel open', reachable.length === 0, reachable.join(', '));
  await page.click('#panel .panel-close');

  // page re-fits when the panel opens and closes (landscape, side by side)
  await page.setViewportSize({ width: 1194, height: 834 });
  await wait(600);
  const pageW = () => page.evaluate(() => Math.round(document.querySelector('.pdf-page').getBoundingClientRect().width));
  const scrollW = () => page.evaluate(() => document.querySelector('#pdf-scroll').clientWidth);
  const w0 = await pageW();
  await page.click('#toggle-panel');
  await wait(900);
  const w1 = await pageW(), s1 = await scrollW();
  await page.click('#toggle-panel');
  await wait(900);
  const w2 = await pageW();
  check('page re-fits with the panel', w1 < w0 && w1 <= s1 && Math.abs(w2 - w0) < 3, `${w0} -> ${w1} (pane ${s1}) -> ${w2}`);
  await page.setViewportSize({ width: 834, height: 1194 });
  await wait(600);
  await page.click('#toggle-notebook');

  // jump to a passage lands visibly
  await page.goto(B + '/reader#study');
  await page.waitForSelector('.task-row .source');
  await page.locator('.task-row .source').first().click();
  await page.waitForSelector('.anno-mark.flash', { timeout: 5000 }).catch(() => {});
  await wait(900);
  check('jumped-to mark is visible', (await visibleAt('.anno-mark.flash')) === 'visible', await visibleAt('.anno-mark.flash'));
  await shot('jump');

  // Retry explain from Study without opening the paper
  await page.goto(B + '/reader#study');
  await page.waitForSelector('.task-row [data-gen]');
  const failedRow = await page.locator('#study-ready .task-row .task-error').textContent().catch(() => '');
  check('failed explanation listed with explanations, friendly error', /AI service/.test(failedRow), failedRow);
  await page.click('.task-row [data-gen]');
  await page.waitForSelector('.explain-card', { timeout: 15000 });
  check('explain retried from Study without leaving it', (await page.evaluate(() => location.hash)) === '#study');
  await page.click('.explain-card [data-act="note"]');
  await page.fill('dialog input', 'Saturation');
  await page.click('dialog button[value="ok"]');
  await wait(500);
  check('Save as note keeps the explanation to read', (await page.locator('.explain-card').count()) === 1);

  // Brief
  const docId = (await page.evaluate(() => __wa.serverItems('doc')))[0].id;
  await page.goto(B + '/reader#brief=' + docId);
  await page.waitForSelector('.brief-body h2');
  const headings = await page.locator('.brief-body h2').allTextContents();
  check('brief has its sections', headings.some(h => h.startsWith('Questions')) && headings.some(h => h.startsWith('Not clear')) && headings.some(h => h.startsWith('Key equations')), headings.join(' | '));
  check('brief question shows its passage', (await page.textContent('.brief-body')).includes('correlated'));
  await shot('brief');

  // page links in the Brief land visibly with the notebook open
  await page.goto(B + '/reader#doc=' + docId);
  await page.waitForSelector('.pdf-page .textLayer span');
  if (!(await page.evaluate(() => document.querySelector('#toggle-notebook').classList.contains('active')))) await page.click('#toggle-notebook');
  await page.waitForSelector('#doc-notebook .note-title');
  await page.goto(B + '/reader#brief=' + docId);
  await page.waitForSelector('.brief-body a.wl-anno');
  await page.locator('.brief-body a.wl-anno', { hasText: 'p. 2' }).first().click();
  await page.waitForSelector('.pdf-page .textLayer span');
  await wait(1800);
  check('brief link jumps visibly with the notebook open', (await visibleAt('.anno-mark.flash')) === 'visible', await visibleAt('.anno-mark.flash'));
  await shot('jump-notebook');
  await page.click('#toggle-notebook');
  await page.goto(B + '/reader#brief=' + docId);
  await page.waitForSelector('.brief-body h2');

  // New note + reload leaves nothing
  const notesBefore = (await page.evaluate(() => __wa.serverItems('note'))).filter(n => !n.deleted).length;
  const openSidebar = async () => {
    if (await page.evaluate(() => document.body.classList.contains('sidebar-closed'))) await page.click('#sidebar-toggle');
  };
  // Clicks New note and waits until the new, empty editor is on screen.
  const newNote = async () => {
    await openSidebar();
    const before = await page.evaluate(() => location.hash);
    await page.click('#new-note');
    await page.waitForFunction(h => location.hash !== h && location.hash.startsWith('#note=')
      && document.querySelector('#note-root .note-title')?.value === '', before);
  };
  await newNote();
  await page.waitForSelector('#note-root .note-title');
  await page.reload();
  await wait(2500);
  const untitledOnServer = (await page.evaluate(() => __wa.serverItems('note'))).filter(n => !n.deleted && !n.data.title && !n.data.notebookFor).length;
  const untitled = await page.locator('#note-list .side-item-title:text-is("Untitled")').count();
  check('abandoned new note leaves nothing', untitledOnServer === 0 && untitled === 0, `server ${untitledOnServer}, list ${untitled}`);
  // ...but typing creates it
  await newNote();
  await page.fill('#note-root .note-title', 'Kept note');
  await wait(1500);
  let kept = false;
  for (let i = 0; i < 16 && !kept; i++) {
    await wait(500);
    kept = (await page.evaluate(() => __wa.serverItems('note'))).some(n => n.data.title === 'Kept note');
  }
  check('typed new note is saved', kept);

  // an edit followed by an immediate reload survives
  await newNote();
  await page.fill('#note-root .note-title', 'Quick reload');
  await page.waitForTimeout(150);
  await page.reload();
  await page.waitForSelector('#note-root .note-title, .pdf-page, .drop-zone');
  await wait(800);
  let quick = false;
  for (let i = 0; i < 16 && !quick; i++) {
    await wait(500);
    quick = (await page.evaluate(() => __wa.serverItems('note'))).some(n => n.data.title === 'Quick reload');
  }
  const shown = await page.inputValue('#note-root .note-title', { timeout: 2000 }).catch(e => 'no editor: ' + e.message.split('\n')[0]);
  check('edit survives an immediate reload', quick && shown === 'Quick reload', `server ${quick}, editor "${shown}", hash ${await page.evaluate(() => location.hash)}`);

  // reloading an abandoned new note resumes the last paper
  await newNote();
  await page.waitForSelector('#note-root .note-title');
  await page.reload();
  await wait(1500);
  check('reload on an abandoned note resumes the last item', !(await page.isVisible('.drop-zone')), await page.evaluate(() => location.hash));

  // untitled note shows its first line
  await newNote();
  await page.click('#note-root .md-view');
  await page.keyboard.type('Ask about learned temperature');
  await page.click('#note-root .note-title');
  await wait(1500);
  check('untitled note listed by its first line', (await page.locator('#note-list .side-item-title').allTextContents()).includes('Ask about learned temperature'));

  // review continues; B2 labels match the saved schedule
  await page.goto(B + '/reader#study');
  await page.click('#start-review');
  await page.click('#reveal');
  const label = await page.textContent('[data-grade="1"] small');
  const cardId = await page.evaluate(async () => {
    const cards = await __wa.serverItems('card');
    return cards.sort((a, b) => a.data.srs.due - b.data.srs.due)[0].id;
  });
  await page.click('[data-grade="1"]');
  await wait(2500);
  const due = await page.evaluate(async id => (await __wa.serverItems('card')).find(c => c.id === id).data.srs.due, cardId);
  const mins = Math.round((due - Date.now()) / 60000);
  const labelMins = label.endsWith('m') ? +label.slice(0, -1) : label.endsWith('h') ? +label.slice(0, -1) * 60 : +label.slice(0, -1) * 1440;
  check('review label matches the saved interval', Math.abs(mins - labelMins) <= Math.max(1, labelMins * 0.1), `label ${label}, saved ${mins} min`);
  if (await page.isVisible('#reveal')) {
    await page.click('#reveal');
    await page.click('[data-grade="0"]');
  }
  await page.waitForSelector('.review-next');
  check('done screen says when cards come back', /due again|came due/.test(await page.textContent('.review-next')), await page.textContent('.review-next'));

  // Contents for a PDF without an outline: detected headings
  await page.goto(B + '/reader');
  await page.setInputFiles('#file-input', FIXTURE_PLAIN);
  await page.waitForSelector('.pdf-page[data-page="1"] .textLayer span');
  await page.click('#toggle-contents');
  await page.waitForSelector('#panel .toc li');
  const detected = await page.locator('#panel .toc-title').allTextContents();
  check('contents detects headings without an outline',
    (await page.textContent('#panel .toc-note')).includes('detected') && detected.some(t => t.includes('Variance of a dot product')) && detected.some(t => t.includes('References')),
    detected.join(' | '));
  await page.click('#panel .panel-close');

  // Undo/redo, eraser on highlights, clear page, pen sizes, pinch zoom
  await page.goto(B + '/reader#doc=' + docId);
  await page.waitForSelector('.pdf-page[data-page="1"] .textLayer span');
  await page.fill('#page-input', '1');
  await page.dispatchEvent('#page-input', 'change');
  await wait(600);
  // Strokes on page 1 on the server; waits until it equals `expect` if given.
  const inkOnPage1 = async expect => {
    let n = -1;
    for (let i = 0; i < 25; i++) {
      n = await page.evaluate(async () => {
        const it = (await __wa.serverItems('ink')).find(x => x.data.page === 1 && !x.deleted);
        return it ? it.data.strokes.length : 0;
      });
      if (expect === undefined || n === expect) return n;
      await wait(400);
    }
    return n;
  };
  await page.click('.tool[data-tool="pen"]');
  await wait(2500);
  const base = await inkOnPage1();
  await page.evaluate(() => __wa.penOnPage(1, 0.2, 0.6, 0.62));
  const afterDraw = await inkOnPage1(base + 1);
  await page.click('[data-history="undo"] >> nth=0');
  const afterUndo = await inkOnPage1(base);
  await page.keyboard.press('Meta+Shift+z');
  const afterRedo = await inkOnPage1(base + 1);
  check('undo and redo a pen stroke (button and keyboard)', afterDraw === base + 1 && afterUndo === base && afterRedo === base + 1, `${base} -> ${afterDraw} -> ${afterUndo} -> ${afterRedo}`);

  // Pen size
  await page.click('#color-group .swatch.active');
  await page.click('#color-group .size-thick');
  await page.evaluate(() => __wa.penOnPage(1, 0.2, 0.6, 0.68));
  await page.click('#color-group .swatch.active');
  await page.click('#color-group .size-fine');
  await page.evaluate(() => __wa.penOnPage(1, 0.2, 0.6, 0.72));
  await inkOnPage1(base + 3);
  const widths = await page.evaluate(async () => {
    const it = (await __wa.serverItems('ink')).find(x => x.data.page === 1);
    return it.data.strokes.slice(-2).map(s => s.width);
  });
  check('pen size changes stroke width', widths.length === 2 && widths[0] > widths[1] * 2, widths.join(' vs '));
  await page.click('#color-group .swatch.active');
  await page.click('#color-group .size-medium');

  // Clear page, then undo it
  await page.click('.tool[data-tool="eraser"]');
  check('clear page shows with the eraser', await page.isVisible('#clear-page'));
  await page.click('#clear-page');
  const cleared = await inkOnPage1(0);
  await page.click('[data-history="undo"] >> nth=0');
  const restored = await inkOnPage1(base + 3);
  check('clear page, then undo restores the ink', cleared === 0 && restored === base + 3, `${cleared} -> ${restored}`);

  // A plain highlight: undo removes it, redo brings it back, the eraser erases it
  await page.click('.tool[data-tool="select"]');
  await page.evaluate(() => __wa.selectText(1, 'An attention layer maps'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  const marksNow = async () => { await wait(300); return page.locator('.pdf-page[data-page="1"] .anno-highlight').count(); };
  const m0 = await marksNow();
  await page.click('#action-bar .action-btn:text-is("Highlight")');
  const m1 = await marksNow();
  await page.click('[data-history="undo"] >> nth=0');
  const m2 = await marksNow();
  await page.click('[data-history="redo"] >> nth=0');
  const m3 = await marksNow();
  check('undo and redo a highlight', m1 === m0 + 1 && m2 === m0 && m3 === m0 + 1, `${m0} -> ${m1} -> ${m2} -> ${m3}`);
  await page.click('.tool[data-tool="eraser"]');
  const hl = await page.evaluate(() => {
    const el = [...document.querySelectorAll('.pdf-page[data-page="1"] .anno-highlight')].pop();
    const r = el.getBoundingClientRect();
    const p = el.closest('.pdf-page').getBoundingClientRect();
    return { x0: (r.left - p.left + 4) / p.width, x1: (r.right - p.left - 4) / p.width, y: (r.top + r.height / 2 - p.top) / p.height };
  });
  await page.evaluate(h => __wa.penOnPage(1, h.x0, h.x1, h.y), hl);
  const m4 = await marksNow();
  check('eraser erases a plain highlight', m4 === m0, `${m3} -> ${m4}`);
  await page.click('.tool[data-tool="select"]');

  // Explain on a passage marked Understood flags it Not clear yet again
  await page.evaluate(() => __wa.selectText(1, 'keys K and values V'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Not clear yet")');
  await wait(400);
  const tapMark = async () => {
    const pt = await page.evaluate(() => {
      const el = [...document.querySelectorAll('.pdf-page[data-page="1"] .anno-highlight')].pop();
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    });
    await page.mouse.click(pt.x, pt.y);
    await page.waitForSelector('#action-bar:not(.hidden)');
  };
  await tapMark();
  await page.click('#action-bar .action-btn:text-is("Understood")');
  await wait(400);
  await tapMark();
  await page.click('#action-bar .action-btn:text-is("Explain")');
  let reflagged;
  for (let i = 0; i < 20 && reflagged !== 'unclear'; i++) {
    await wait(500);
    reflagged = await page.evaluate(async () => (await __wa.serverItems('anno')).find(a => !a.deleted && /keys K\s*and values V/.test(a.data.quote))?.data.status);
  }
  check('explain re-flags an understood passage as not clear', reflagged === 'unclear', String(reflagged));

  // Pinch zoom (trackpad pinch arrives as ctrl+wheel) zooms the page only
  const w0z = await page.evaluate(() => document.querySelector('.pdf-page').getBoundingClientRect().width);
  const box = await page.locator('#pdf-scroll').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + 300);
  await page.keyboard.down('Control');
  for (let i = 0; i < 10; i++) await page.mouse.wheel(0, -40);
  await page.keyboard.up('Control');
  await wait(900);
  const w1z = await page.evaluate(() => document.querySelector('.pdf-page').getBoundingClientRect().width);
  const tbw = await page.evaluate(() => document.querySelector('.doc-toolbar').getBoundingClientRect().width);
  await wait(1200);
  const sharpness = await page.evaluate(() => {
    const p = [...document.querySelectorAll('.pdf-page')].find(el => {
      const r = el.getBoundingClientRect();
      return r.bottom > 100 && r.top < innerHeight;
    });
    const base = p.querySelector('.pdf-canvas');
    const d = p.querySelector('.pdf-detail');
    return {
      base: base.width / p.clientWidth,
      detail: d ? d.width / d.getBoundingClientRect().width : 0,
    };
  });
  check('high zoom renders the visible area at full resolution', sharpness.base < 1.8 && sharpness.detail >= 1.8,
    `page canvas ${sharpness.base.toFixed(2)}x, detail ${sharpness.detail.toFixed(2)}x`);
  check('pinch zoom enlarges the page, not the interface', w1z > w0z * 1.3 && Math.abs(tbw - 834) < 2, `${Math.round(w0z)} -> ${Math.round(w1z)}, toolbar ${Math.round(tbw)}`);
  await page.click('#zoom-fit').catch(() => {});

  // Rename and remove a paper (the outline-less copy, not the main one)
  await page.goto(B + '/reader');
  const plainId = (await page.evaluate(() => __wa.serverItems('doc'))).map(d => d.id).find(id => id !== docId);
  const row = () => page.locator(`#doc-list .side-row:has(a[href="#doc=${plainId}"])`);
  await page.waitForFunction(() => document.querySelector('#sync-status').dataset.state === 'synced');
  const library = async () => {
    if (await page.evaluate(() => document.body.classList.contains('sidebar-closed'))) await page.click('#sidebar-toggle');
  };
  await library();
  await row().locator('.side-more').click();
  await page.fill('dialog [name=title]', 'Renamed paper');
  await page.click('dialog button[value="ok"]');
  await wait(500);
  check('rename a paper', (await row().locator('.side-item-title').textContent()) === 'Renamed paper');
  await library();
  await row().locator('.side-more').click();
  await page.click('dialog button[value="remove"]');
  await wait(1500);
  let gone = false;
  for (let i = 0; i < 16 && !gone; i++) {
    await wait(500);
    gone = (await page.evaluate(() => __wa.serverItems('doc'))).some(d => d.id === plainId && d.data.trashedAt);
  }
  check('remove a paper (to Recently deleted)', (await row().count()) === 0 && gone);

  // Find in paper (Contents panel), highlighted on the page
  await page.click(`#doc-list a[href="#doc=${docId}"]`).catch(() => {});
  await page.goto(B + '/reader#doc=' + docId + '&p=1');
  await page.waitForSelector('.pdf-page[data-page="1"] .textLayer span');
  if (!(await page.evaluate(() => document.querySelector('#toggle-contents').classList.contains('active')))) await page.click('#toggle-contents');
  await page.fill('#panel .find-box', 'Glorot');
  await page.waitForSelector('#panel .find-hit-item');
  const findHits = await page.locator('#panel .find-hit-item').count();
  await page.locator('#panel .find-hit-item').first().click();
  await page.waitForSelector('.pdf-page[data-page="3"] .textLayer span.find-hit', { timeout: 8000 }).catch(() => {});
  check('find in paper jumps to and highlights the match', findHits === 1 && (await page.inputValue('#page-input')) === '3'
    && (await page.locator('.pdf-page[data-page="3"] .textLayer span.find-hit').count()) > 0, `${findHits} hit(s), page ${await page.inputValue('#page-input')}`);
  await page.keyboard.press('Escape');
  await page.keyboard.press('Meta+f');
  await wait(300);
  await page.keyboard.type('variance');
  await page.waitForFunction(() => /variance/i.test(document.querySelector('#panel .find-results mark')?.textContent || ''));
  check('Cmd+F selects the previous query so typing replaces it', (await page.inputValue('#panel .find-box')) === 'variance', await page.inputValue('#panel .find-box'));
  const snip = await page.locator('#panel .find-snippet').first().textContent();
  check('find snippets keep the spaces around the match', /\s(the )?variance\s/.test(snip), JSON.stringify(snip));
  await page.click('#panel .panel-close').catch(() => {});

  // Library search finds the paper's own text
  await library();
  await page.fill('#search', 'numeric check');
  await page.waitForSelector('#search-results .search-section', { timeout: 8000 }).catch(() => {});
  const textHits = await page.locator('#search-results a[href*="&q="]').allTextContents();
  check('library search finds text inside papers', textHits.some(t => t.startsWith('p. 3')), textHits.join(' | '));
  await page.fill('#search', '');

  // Renaming a paper rewrites [[links]] to it
  await page.evaluate(() => { location.hash = ''; });
  await newNote();
  await page.fill('#note-root .note-title', 'Rename probe');
  await page.click('#note-root .md-view');
  await page.keyboard.type('See [[Scaled Dot-Product Attention: A Short Derivation|the paper]] and [[Scaled Dot-Product Attention: A Short Derivation]].');
  await page.click('#note-root .note-title');
  await wait(1200);
  await library();
  await page.locator(`#doc-list .side-row:has(a[href="#doc=${docId}"]) .side-more`).click();
  await page.fill('dialog [name=title]', 'Attention note');
  await page.click('dialog button[value="ok"]');
  await wait(1500);
  const noteText = n => (n ? n.data.blocks.map(b => b.text || '').join(' ') : '');
  let probe = null;
  for (let i = 0; i < 24; i++) {
    probe = (await page.evaluate(() => __wa.serverItems('note'))).find(n => n.data.title === 'Rename probe');
    if (probe && noteText(probe).includes('[[Attention note')) break;
    await wait(500);
  }
  const probeText = noteText(probe);
  const nbTitle = (await page.evaluate(() => __wa.serverItems('note'))).find(n => n.data.notebookFor)?.data.title;
  check('renaming a paper renames its notebook', nbTitle === 'Notes: Attention note', nbTitle);
  check('renaming a paper updates links to it', probeText.includes('[[Attention note|the paper]]') && probeText.includes('[[Attention note]]'), probeText);
  // ...and the rename undoes as one step (title and links)
  await library();
  await page.click(`#note-list a[href="#note=${probe.id}"]`);
  await page.waitForSelector('#note-root .note-title');
  await page.click('[data-history="undo"] >> nth=1');
  let undone = '';
  for (let i = 0; i < 24; i++) {
    await wait(500);
    undone = noteText((await page.evaluate(() => __wa.serverItems('note'))).find(n => n.id === probe.id));
    if (undone.includes('[[Scaled Dot-Product Attention: A Short Derivation|the paper]]')) break;
  }
  check('undo restores the paper title and its links', undone.includes('[[Scaled Dot-Product Attention: A Short Derivation|the paper]]'), undone);

  // A card draft that arrives after the user typed does not overwrite it
  await page.goto(B + '/reader#doc=' + docId + '&p=1');
  await page.waitForSelector('.pdf-page[data-page="1"] .textLayer span');
  slowDraft = true;
  await page.click('.tool[data-tool="select"]');
  await page.evaluate(() => __wa.selectText(1, 'The factor 1/sqrt(d_k) is the subject'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Card")');
  await page.waitForSelector('dialog[open] .card-form');
  await page.fill('dialog [name=front]', 'MY OWN QUESTION');
  await wait(3500);
  const frontNow = await page.inputValue('dialog [name=front]');
  const offered = await page.locator('dialog .dialog-status button').count();
  check('card draft does not overwrite typed text', frontNow === 'MY OWN QUESTION' && offered === 1, `front "${frontNow}", offer buttons ${offered}`);
  slowDraft = false;
  await page.click('dialog button[value="cancel"]');

  check('explanations stream (SSE) and are saved', streamed > 0, streamed + ' streamed request(s)');

  // Find steps through matches with Enter and shows "i of n"
  await page.goto(B + '/reader#doc=' + docId + '&p=1');
  await page.waitForSelector('.pdf-page[data-page="1"] .textLayer span');
  if (!(await page.evaluate(() => document.querySelector('#toggle-contents').classList.contains('active')))) await page.click('#toggle-contents');
  await page.fill('#panel .find-box', 'variance');
  await page.waitForFunction(() => /found/.test(document.querySelector('#panel .find-count')?.textContent || ''));
  await page.focus('#panel .find-box');
  await page.keyboard.press('Enter');
  await page.keyboard.press('Enter');
  const counter = await page.textContent('#panel .find-count');
  await page.keyboard.press('Shift+Enter');
  const counterBack = await page.textContent('#panel .find-count');
  check('Enter and Shift+Enter step through matches', /^2 of \d+/.test(counter) && /^1 of \d+/.test(counterBack) && await page.isVisible('#panel'), `${counter} -> ${counterBack}`);
  await page.fill('#panel .find-box', '');
  await page.click('#panel .panel-close');

  // Tapping a mark keeps the Marks panel open and finds its row
  await page.click('.tool[data-tool="select"]');
  await page.click('#toggle-panel');
  await page.waitForSelector('#panel .mark');
  const tapPt = await page.evaluate(() => {
    const el = document.querySelector('.pdf-page[data-page="1"] .anno-highlight');
    const r = el.getBoundingClientRect();
    return { x: r.left + 6, y: r.top + r.height / 2 };
  });
  await page.mouse.click(tapPt.x, tapPt.y);
  await wait(400);
  check('tapping a mark keeps the Marks panel open on its row', await page.isVisible('#panel') && (await page.locator('#panel .mark.current').count()) === 1);
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');

  // Pin a passage to the Brief
  await page.evaluate(() => __wa.selectText(1, 'It is easy to overlook'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Add to Brief")');
  await wait(400);
  await page.goto(B + '/reader#brief=' + docId);
  await page.waitForSelector('.brief-body h2');
  const briefHeads = await page.locator('.brief-body h2').allTextContents();
  check('pinned passages and explained points appear in the Brief', briefHeads.some(h => h.startsWith('Key passages')) && (await page.textContent('.brief-body')).includes('It is easy to overlook'), briefHeads.join(' | '));

  // Search hit on an explanation opens it in Study
  await library();
  await page.fill('#search', 'In plain terms');
  await page.waitForSelector('#search-results a[href*="#study&t="]');
  await page.locator('#search-results a[href*="#study&t="]').first().click();
  await page.waitForSelector('#view-study [data-task].flash', { timeout: 4000 }).catch(() => {});
  check('explanation search hit opens it in Study', (await page.evaluate(() => location.hash)).startsWith('#study&t=') && (await page.locator('#view-study [data-task].flash').count()) === 1);
  // The library closed with the tap (portrait); clear the query directly.
  await page.evaluate(() => {
    const box = document.querySelector('#search');
    box.value = '';
    box.dispatchEvent(new Event('input'));
  });

  // Deleting a mark keeps the passage on its follow-up
  await page.evaluate(id => { location.hash = '#doc=' + id + '&p=1'; }, docId);
  await page.waitForSelector('#view-doc:not(.hidden) .pdf-page[data-page="1"] .textLayer span');
  await page.click('.tool[data-tool="select"]');
  await page.evaluate(() => __wa.selectText(1, 'weighted sum of the values'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Follow-up")');
  await page.fill('dialog textarea', 'Check the weighting');
  await page.click('dialog button[value="ok"]');
  await wait(500);
  const fuPt = await page.evaluate(() => {
    const els = [...document.querySelectorAll('.pdf-page[data-page="1"] .anno-highlight')];
    const el = els.find(e => e.getBoundingClientRect().width > 0 && e.dataset.anno);
    const all = els.map(e => e.getBoundingClientRect());
    const r = all.sort((a, b) => b.top - a.top)[0];
    return { x: r.left + 6, y: r.top + r.height / 2 };
  });
  await page.mouse.click(fuPt.x, fuPt.y);
  await page.waitForSelector('#action-bar:not(.hidden)');
  await page.click('#action-bar .action-btn:text-is("Delete")');
  await wait(600);
  await page.goto(B + '/reader#study');
  await page.waitForSelector('.task-row');
  const orphan = page.locator('.task-row', { hasText: 'Check the weighting' });
  check('a follow-up keeps its passage after the mark is deleted', (await orphan.locator('.task-quote').textContent().catch(() => '')).includes('weighted sum') && (await orphan.locator('.source').textContent()).includes('p. 1'));

  // Resize the notebook with the handle
  await page.goto(B + '/reader#doc=' + docId);
  await page.waitForSelector('.pdf-page .textLayer span');
  if (!(await page.evaluate(() => document.querySelector('#toggle-notebook').classList.contains('active')))) await page.click('#toggle-notebook');
  await page.waitForSelector('#split-handle:not(.hidden)');
  const h0 = await page.evaluate(() => document.querySelector('#doc-notebook').getBoundingClientRect().height);
  const hb = await page.locator('#split-handle').boundingBox();
  await page.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x + hb.width / 2, hb.y - 200, { steps: 8 });
  await page.mouse.up();
  await wait(300);
  const h1 = await page.evaluate(() => document.querySelector('#doc-notebook').getBoundingClientRect().height);
  await page.reload();
  await page.waitForSelector('#doc-notebook:not(.hidden)');
  await wait(500);
  const h2 = await page.evaluate(() => document.querySelector('#doc-notebook').getBoundingClientRect().height);
  check('notebook resizes with the handle and keeps its size', h1 > h0 + 150 && Math.abs(h2 - h1) < 4, `${Math.round(h0)} -> ${Math.round(h1)} -> ${Math.round(h2)}`);
  await page.click('#toggle-notebook');

  // Recently deleted: remove, restore, delete for good
  await page.goto(B + '/reader');
  await page.setInputFiles('#file-input', FIXTURE_PLAIN);
  await page.waitForSelector('.pdf-page[data-page="1"] .textLayer span');
  let plain2Id;
  for (let i = 0; i < 16 && !plain2Id; i++) {
    await wait(500);
    plain2Id = (await page.evaluate(() => __wa.serverItems('doc'))).find(d => !d.deleted && d.id !== docId)?.id;
  }
  const prow = () => page.locator(`#doc-list .side-row:has(a[href="#doc=${plain2Id}"])`);
  await library();
  await prow().locator('.side-more').click();
  await page.click('dialog button[value="remove"]');
  await wait(600);
  await library();
  const inTrash = await page.locator(`#trash li[data-doc="${plain2Id}"]`).count();
  const inList = await prow().count();
  await page.click('#trash summary');
  await page.click('#trash [data-act="restore"]');
  await wait(600);
  const restoredRow = await prow().count();
  check('removed papers go to Recently deleted and can be restored', inTrash === 1 && inList === 0 && restoredRow === 1, `trash ${inTrash}, list ${inList}, restored ${restoredRow}`);
  await prow().locator('.side-more').click();
  await page.click('dialog button[value="remove"]');
  await wait(600);
  await library();
  if (!(await page.evaluate(() => document.querySelector('#trash').open))) await page.click('#trash summary');
  await page.click('#trash [data-act="purge"]');
  let purged = false;
  for (let i = 0; i < 16 && !purged; i++) {
    await wait(500);
    purged = (await page.evaluate(() => __wa.serverItems('doc'))).some(d => d.id === plain2Id && d.deleted);
  }
  check('Delete now removes a paper for good', purged && !(await page.isVisible('#trash')));

  // Tapping the open paper in the library puts the library away
  await library();
  await page.click(`#doc-list a[href="#doc=${docId}"]`);
  await wait(300);
  check('tapping the open paper closes the library', await page.evaluate(() => document.body.classList.contains('sidebar-closed')));

  // labels
  await page.waitForSelector('.pdf-page .textLayer span');
  await page.click('.tool[data-tool="select"]');
  await page.evaluate(() => __wa.selectText(1, 'An attention layer'));
  await page.waitForSelector('#action-bar:not(.hidden)');
  const labels = await page.locator('#action-bar .swatch').evaluateAll(els => els.map(e => e.getAttribute('aria-label')));
  check('highlight colors are named', new Set(labels).size === labels.length, labels.join(', '));
} catch (e) {
  failures++;
  const at = (e.stack || '').split('\n').find(l => l.includes('reader.e2e.mjs')) || '';
  console.log('ERROR', e.message.split('\n')[0], at.trim());
  await shot('error');
}
const unexpected = errors.filter(e => !/upstream overloaded|500|Explanation failed|pointer capture/.test(e));
if (unexpected.length) failures++;
console.log('console errors:', unexpected.join(' | ') || '(none)');
await browser.close();
console.log(failures ? `${failures} failure(s)` : 'All checks passed');
process.exit(failures ? 1 : 0);
