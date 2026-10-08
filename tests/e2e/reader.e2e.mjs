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
const OUT = process.env.E2E_OUT || '.';
if (!B || !token || !FIXTURE) throw new Error('Run through scripts/e2e_reader.sh');
const kit = `const __WA_CONFIG = ${JSON.stringify({ token, origin: B, openrouterKey: 'sk-or-test' })};\n` + readFileSync(ROOT + 'scripts/feature_test/testkit.js', 'utf8');

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const ctx = await browser.newContext({ viewport: { width: 834, height: 1194 }, hasTouch: true, deviceScaleFactor: 2 });
await ctx.addInitScript(kit);
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
  else if (text.includes('FRONT:')) reply = 'FRONT:\nWhy is $\\operatorname{Var}(q \\cdot k / \\sqrt{d_k}) = 1$ with $\\delta_{ij}$?\nBACK:\nVar scales by $1/d_k$.';
  else if (text.includes('not yet understood')) reply = '1. **In plain terms** - saturation.';
  await route.fulfill({ json: { choices: [{ message: { content: reply } }] } });
});

const page = await ctx.newPage();
const errors = [];
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
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
  check('done screen says when cards come back', /back in|came due/.test(await page.textContent('.review-next')), await page.textContent('.review-next'));

  // labels
  await page.goto(B + '/reader#doc=' + docId);
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
