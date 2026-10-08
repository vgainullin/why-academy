// Feature-test kit, injected into every page by Playwright MCP (--init-script).
// The runner prepends: const __WA_CONFIG = { token, openrouterKey, origin };
//
// Signs the browser into the seeded test account and exposes window.__wa:
// helpers for what browser automation cannot do directly (Apple Pencil input,
// precise text selection) and read-only views of the vault for checking
// results. The tester reports bugs; it never edits app code.

(function () {
  if (location.origin !== __WA_CONFIG.origin) return;

  // Session cookie for the seeded account. The server only needs the cookie
  // sent; it does not have to be HttpOnly in the test browser.
  if (!document.cookie.includes('__Host-wa_session=')) {
    document.cookie = `__Host-wa_session=${__WA_CONFIG.token}; path=/; secure; samesite=lax`;
  }
  try {
    if (__WA_CONFIG.openrouterKey && !localStorage.getItem('openrouterApiKey')) {
      localStorage.setItem('handwriteBackend', 'openrouter');
      localStorage.setItem('openrouterApiKey', __WA_CONFIG.openrouterKey);
    }
  } catch (e) {
    console.error('testkit: localStorage unavailable', e);
  }

  let nextPointerId = 1000;

  function pageBox(page) {
    const el = document.querySelector(`.pdf-page[data-page="${page}"]`);
    if (!el) throw new Error(`PDF page ${page} is not in the DOM (scroll to it first)`);
    return el.getBoundingClientRect();
  }

  // Dispatches a pointer sequence like an Apple Pencil (pointerType 'pen') or
  // a finger ('touch'). points: [[x, y], ...] in client pixels.
  function stroke(points, pointerType = 'pen') {
    const pointerId = nextPointerId++;
    const fire = (type, [x, y], i) => {
      const target = document.elementFromPoint(x, y);
      if (!target) throw new Error(`No element at ${x},${y}`);
      target.dispatchEvent(new PointerEvent(type, {
        bubbles: true, cancelable: true, composed: true,
        pointerId, pointerType, isPrimary: true,
        clientX: x, clientY: y,
        pressure: type === 'pointerup' ? 0 : 0.4 + 0.3 * Math.sin(i / 3) ** 2,
        button: type === 'pointermove' ? -1 : 0,
        buttons: type === 'pointerup' ? 0 : 1,
      }));
    };
    fire('pointerdown', points[0], 0);
    points.slice(1).forEach((p, i) => fire('pointermove', p, i + 1));
    fire('pointerup', points[points.length - 1], points.length);
  }

  // Coordinates as fractions (0..1) of a PDF page.
  function onPage(page, fracPoints) {
    const r = pageBox(page);
    return fracPoints.map(([fx, fy]) => [r.left + fx * r.width, r.top + fy * r.height]);
  }

  window.__wa = {
    // Pencil stroke across a PDF page: a gentle wave from (x0,y) to (x1,y).
    penOnPage(page, x0 = 0.2, x1 = 0.6, y = 0.5, pointerType = 'pen') {
      const pts = [];
      for (let i = 0; i <= 24; i++) pts.push([x0 + (x1 - x0) * i / 24, y + 0.01 * Math.sin(i / 2)]);
      stroke(onPage(page, pts), pointerType);
      return 'stroke dispatched';
    },
    // Rectangle drag (Region tool) on a PDF page, in page fractions.
    dragOnPage(page, x0, y0, x1, y1, pointerType = 'pen') {
      const pts = [];
      for (let i = 0; i <= 10; i++) pts.push([x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * i / 10]);
      stroke(onPage(page, pts), pointerType);
      return 'drag dispatched';
    },
    // Pencil stroke inside a notebook ink pad (nth pad on screen, 0-based).
    // pointerType 'touch' makes it a finger, which must not draw.
    penInPad(n = 0, fracPoints = [[0.1, 0.3], [0.3, 0.4], [0.5, 0.3], [0.7, 0.45]], pointerType = 'pen') {
      const pad = document.querySelectorAll('.ink-pad')[n];
      if (!pad) throw new Error('No ink pad #' + n);
      const r = pad.getBoundingClientRect();
      const pts = [];
      for (let i = 0; i < fracPoints.length - 1; i++) {
        for (let t = 0; t < 6; t++) {
          const [ax, ay] = fracPoints[i], [bx, by] = fracPoints[i + 1];
          pts.push([r.left + (ax + (bx - ax) * t / 6) * r.width, r.top + (ay + (by - ay) * t / 6) * r.height]);
        }
      }
      stroke(pts, pointerType);
      return 'stroke dispatched';
    },
    // Selects the first occurrence of `text` in a page's text layer, like a
    // long-press drag. The text may span several text runs; whitespace in
    // `text` matches any whitespace (or none) between runs.
    selectText(page, text) {
      const layer = document.querySelector(`.pdf-page[data-page="${page}"] .textLayer`);
      if (!layer) throw new Error(`Text layer of page ${page} not rendered`);
      const nodes = [];
      const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
      let node;
      let flat = '';
      while ((node = walker.nextNode())) {
        nodes.push({ node, start: flat.length });
        flat += node.data;
      }
      const pattern = new RegExp(text.trim().split(/\s+/).map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s*'));
      const m = pattern.exec(flat);
      if (!m) throw new Error(`"${text}" not found on page ${page}`);
      const locate = offset => {
        let i = nodes.length - 1;
        while (i > 0 && nodes[i].start > offset) i--;
        return { node: nodes[i].node, offset: Math.min(offset - nodes[i].start, nodes[i].node.data.length) };
      };
      const a = locate(m.index), b = locate(m.index + m[0].length);
      const r = document.createRange();
      r.setStart(a.node, a.offset);
      r.setEnd(b.node, b.offset);
      getSelection().removeAllRanges();
      getSelection().addRange(r);
      return getSelection().toString();
    },
    // Server copy of the vault, optionally filtered by kind.
    async serverItems(kind) {
      const items = [];
      let since = 0;
      for (;;) {
        const page = await (await fetch('/api/vault/pull?since=' + since)).json();
        items.push(...page.items);
        since = page.cursor;
        if (!page.more) break;
      }
      return items.filter(i => !kind || i.kind === kind).map(i => ({ id: i.id, kind: i.kind, deleted: i.deleted, data: i.data }));
    },
    syncStatus() {
      const el = document.querySelector('#sync-status');
      return el ? { state: el.dataset.state, text: el.textContent } : null;
    },
  };
})();
