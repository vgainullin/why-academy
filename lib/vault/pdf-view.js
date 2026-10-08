// Why Academy — PDF view
//
// Continuous vertical scroll of pages rendered by pdf.js. Only pages near the
// viewport hold a canvas (iPad Safari caps total canvas memory), the rest are
// sized placeholders. Each page stacks: page canvas, highlight layer, text
// layer (native selection), ink surface.

import * as pdfjs from 'https://cdn.jsdelivr.net/npm/pdfjs-dist@6.3.289/build/pdf.min.mjs';
import { InkSurface } from './ink.js';

pdfjs.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@6.3.289/build/pdf.worker.min.mjs';

const CSS_UNITS = 96 / 72;
const MAX_RENDERED = 8;
const MAX_CANVAS_PIXELS = 16_000_000;

// Page count and document-info metadata, without rendering.
export async function readPdfInfo(bytes) {
  const task = pdfjs.getDocument({ data: bytes.slice(), isEvalSupported: false });
  const pdf = await task.promise;
  try {
    const { info } = await pdf.getMetadata();
    return { pages: pdf.numPages, title: (info && info.Title) || '', authors: (info && info.Author) || '' };
  } finally {
    await task.destroy();
  }
}

export class PdfView extends EventTarget {
  /**
   * opts.getTool, opts.onInkAdd(page, stroke), opts.onInkErase(page, ids),
   * opts.onRegion(page, rect), opts.onEraseMark(anno): the eraser touched a mark
   */
  constructor(scrollEl, opts) {
    super();
    this.scrollEl = scrollEl;
    this.opts = opts;
    this.pdf = null;
    this.pages = []; // { num, el, w, h (scale-1 CSS px), rendered, task, textLayer, ink }
    this.zoom = 1;
    this.fitWidth = true;
    this.annos = new Map(); // page -> [anno items]
    this.inkByPage = new Map(); // page -> strokes
    this.currentPage = 1;
    this.textCache = new Map();
    this._io = null;
    this._visible = new Set();
  }

  // Opens the document without rendering anything: enough for pageText,
  // contextFor and regionImage when the paper is not on screen.
  async open(bytes) {
    // pdf.js transfers the buffer to its worker; keep the caller's copy intact.
    this.loadingTask = pdfjs.getDocument({ data: bytes.slice(), isEvalSupported: false });
    this.pdf = await this.loadingTask.promise;
    return this.pdf.numPages;
  }

  async load(bytes) {
    const n = await this.open(bytes);
    this._alive();
    const first = await this.pdf.getPage(1);
    this._alive();
    const vp = first.getViewport({ scale: CSS_UNITS });

    this.scrollEl.innerHTML = '';
    this.container = document.createElement('div');
    this.container.className = 'pdf-pages';
    this.scrollEl.appendChild(this.container);

    this.pages = [];
    for (let i = 1; i <= n; i++) {
      const el = document.createElement('div');
      el.className = 'pdf-page';
      el.dataset.page = String(i);
      const num = document.createElement('div');
      num.className = 'pdf-page-num';
      num.textContent = String(i);
      el.appendChild(num);
      this.container.appendChild(el);
      this.pages.push({ num: i, el, w: vp.width, h: vp.height, rendered: false, sizeKnown: i === 1 });
    }
    this.layout();

    this._io = new IntersectionObserver(entries => {
      for (const e of entries) {
        const num = +e.target.dataset.page;
        if (e.isIntersecting) this._visible.add(num);
        else this._visible.delete(num);
      }
      this._renderVisible();
    }, { root: this.scrollEl, rootMargin: '150% 0px' });
    for (const p of this.pages) this._io.observe(p.el);

    this._bindZoomGestures();
    this._onScroll = () => {
      this._trackPage();
      this._scheduleDetail();
    };
    this.scrollEl.addEventListener('scroll', this._onScroll, { passive: true });
    // Re-fit whenever the scroller's width changes: window resize, rotation,
    // or a side panel opening or closing.
    this._width = this.scrollEl.clientWidth;
    this._ro = new ResizeObserver(() => {
      clearTimeout(this._resizeTimer);
      this._resizeTimer = setTimeout(() => {
        const w = this.scrollEl.clientWidth;
        if (w && Math.abs(w - this._width) > 1) {
          this._width = w;
          if (this.fitWidth) this.layout();
        }
      }, 120);
    });
    this._ro.observe(this.scrollEl);
    return n;
  }

  // Throws once destroy() ran: a paper closed while loading must not take
  // over the shared scroll container.
  _alive() {
    if (this.destroyed) {
      const err = new Error('PDF view closed while loading');
      err.closed = true;
      throw err;
    }
  }

  // Aborted on destroy, for listeners the app attaches on this view's behalf.
  get signal() {
    if (!this._abort) this._abort = new AbortController();
    return this._abort.signal;
  }

  destroy() {
    this.destroyed = true;
    if (this._abort) this._abort.abort();
    if (this._io) this._io.disconnect();
    if (this._onScroll) this.scrollEl.removeEventListener('scroll', this._onScroll);
    if (this._ro) this._ro.disconnect();
    clearTimeout(this._detailTimer);
    clearTimeout(this._resizeTimer);
    for (const p of this.pages) this._unrender(p);
    // pdf.js 6 tears a document down through its loading task.
    if (this.loadingTask) this.loadingTask.destroy();
    this.loadingTask = null;
    this.pdf = null;
    this.pages = [];
  }

  get numPages() {
    return this.pdf ? this.pdf.numPages : 0;
  }

  // CSS scale applied to scale-1 (CSS px) page sizes.
  scaleFor(p) {
    if (!this.fitWidth) return this.zoom;
    const avail = this.scrollEl.clientWidth - 32;
    return Math.max(0.3, Math.min(4, avail / p.w)) * this.zoom;
  }

  // Re-sizes every page for the current zoom and keeps the reading position.
  layout() {
    // A jump still in flight (smooth scroll) wins over where the scroll is now.
    const j = this._jump;
    const anchor = j && Date.now() - j.at < 1500 ? { page: j.page, frac: j.yFrac, margin: j.margin } : this.position();
    for (const p of this.pages) {
      const s = this.scaleFor(this.pages[0]);
      p.el.style.width = Math.floor(p.w * s) + 'px';
      p.el.style.height = Math.floor(p.h * s) + 'px';
      if (p.rendered) this._unrender(p);
    }
    this._renderVisible();
    if (anchor) this.goTo(anchor.page, anchor.frac, 'instant', anchor.margin || 0);
  }

  // Top of a page in the scroll container's content coordinates. offsetTop
  // would be relative to the nearest positioned ancestor, which is not
  // necessarily the scroller.
  _top(p) {
    return p.el.getBoundingClientRect().top - this.scrollEl.getBoundingClientRect().top + this.scrollEl.scrollTop;
  }

  // Page and fraction of it at the top of the viewport.
  position() {
    if (!this.pages.length) return null;
    const y = this.scrollEl.scrollTop;
    const p = this.pages[this._pageAt(y) - 1];
    return { page: p.num, frac: Math.max(0, (y - this._top(p)) / p.el.offsetHeight) };
  }

  _pageAt(y) {
    let lo = 0, hi = this.pages.length - 1;
    while (lo < hi) {
      const m = (lo + hi + 1) >> 1;
      if (this._top(this.pages[m]) <= y) lo = m;
      else hi = m - 1;
    }
    return lo + 1;
  }

  // Pinch zoom zooms the PDF, not the whole interface: Safari gesture events
  // (iPad, Mac trackpad in Safari) and ctrl+wheel (trackpad pinch elsewhere).
  // The pages scale with CSS during the gesture and re-render once at the end.
  _bindZoomGestures() {
    const el = this.scrollEl;
    const opts = { passive: false, signal: this.signal };
    let base = 1;
    let origin = null;
    const begin = (x, y) => {
      base = this.zoom;
      const r = this.container.getBoundingClientRect();
      origin = { x: x - r.left, y: y - r.top, cx: x, cy: y };
      this.container.style.transformOrigin = `${origin.x}px ${origin.y}px`;
    };
    const preview = scale => {
      const z = Math.max(0.25, Math.min(4, base * scale));
      this.container.style.transform = `scale(${z / base})`;
      return z;
    };
    el.addEventListener('gesturestart', e => {
      e.preventDefault();
      begin(e.clientX, e.clientY);
    }, opts);
    el.addEventListener('gesturechange', e => {
      e.preventDefault();
      preview(e.scale);
    }, opts);
    el.addEventListener('gestureend', e => {
      e.preventDefault();
      this._commitZoom(preview(e.scale), origin);
    }, opts);

    let wheelScale = 1;
    let wheelTimer = null;
    el.addEventListener('wheel', e => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      if (!wheelTimer) {
        wheelScale = 1;
        begin(e.clientX, e.clientY);
      }
      wheelScale *= Math.exp(-e.deltaY / 100);
      const z = preview(wheelScale);
      clearTimeout(wheelTimer);
      wheelTimer = setTimeout(() => {
        wheelTimer = null;
        this._commitZoom(z, origin);
      }, 180);
    }, opts);
  }

  // Applies a pinch zoom, keeping the point under the fingers in place.
  _commitZoom(zoom, origin) {
    const el = this.scrollEl;
    // Measure on the unscaled layout: the preview transform would skew it.
    this.container.style.transform = '';
    const box = el.getBoundingClientRect();
    const fx = origin ? origin.cx - box.left : el.clientWidth / 2;
    const fy = origin ? origin.cy - box.top : el.clientHeight / 2;
    const y = el.scrollTop + fy;
    const page = this.pages[this._pageAt(y) - 1];
    if (!page) return this.setZoom(zoom, this.fitWidth);
    const pr = page.el.getBoundingClientRect();
    const fracY = (y - this._top(page)) / page.el.offsetHeight;
    const fracX = (origin ? origin.cx - pr.left : pr.width / 2) / pr.width;
    this.setZoom(zoom, this.fitWidth);
    // Put the same point of the page back under the fingers.
    this.goTo(page.num, fracY, 'instant', fy);
    const after = page.el.getBoundingClientRect();
    el.scrollLeft += after.left + fracX * after.width - (box.left + fx);
  }

  setZoom(zoom, fitWidth) {
    this.zoom = Math.max(0.25, Math.min(4, zoom));
    this.fitWidth = fitWidth;
    this.layout();
    this.dispatchEvent(new CustomEvent('zoom', { detail: this.zoom }));
  }

  // Scrolls so that yFrac of the page sits `margin` px below the top.
  goTo(page, yFrac = 0, behavior = 'smooth', margin = 24) {
    const p = this.pages[page - 1];
    if (!p) return;
    const top = this._top(p) + yFrac * p.el.offsetHeight - margin;
    this.scrollEl.scrollTo({ top: Math.max(0, top), behavior });
    this._jump = { page, yFrac, margin, at: Date.now() };
    this._setPage(page);
  }

  _trackPage() {
    this._setPage(this._pageAt(this.scrollEl.scrollTop + this.scrollEl.clientHeight / 3));
  }

  _setPage(page) {
    if (page !== this.currentPage) {
      this.currentPage = page;
      this.dispatchEvent(new CustomEvent('page', { detail: page }));
    }
  }

  _renderVisible() {
    const want = [...this._visible].sort((a, b) => Math.abs(a - this.currentPage) - Math.abs(b - this.currentPage));
    for (const num of want.slice(0, MAX_RENDERED)) {
      const p = this.pages[num - 1];
      this._render(p).catch(e => {
        console.error('Rendering page ' + num + ' failed', e);
        p.rendered = false;
      });
    }
    const rendered = this.pages.filter(p => p.rendered);
    if (rendered.length > MAX_RENDERED) {
      rendered
        .sort((a, b) => Math.abs(b.num - this.currentPage) - Math.abs(a.num - this.currentPage))
        .slice(0, rendered.length - MAX_RENDERED)
        .forEach(p => this._unrender(p));
    }
  }

  async _render(p) {
    if (p.rendered) return;
    p.rendered = true;
    // An unrender + re-render while this one awaits must not let both
    // continue (two canvases, two ink surfaces recording every stroke).
    const token = {};
    p.token = token;
    const current = () => p.rendered && p.token === token && !this.destroyed;
    const page = await this.pdf.getPage(p.num);
    if (!current()) return;

    if (!p.sizeKnown) {
      const vp1 = page.getViewport({ scale: CSS_UNITS });
      p.sizeKnown = true;
      if (Math.abs(vp1.width - p.w) > 0.5 || Math.abs(vp1.height - p.h) > 0.5) {
        p.w = vp1.width;
        p.h = vp1.height;
        const s0 = this.scaleFor(this.pages[0]);
        p.el.style.width = Math.floor(p.w * s0) + 'px';
        p.el.style.height = Math.floor(p.h * s0) + 'px';
      }
    }

    const cssW = p.el.clientWidth;
    const scale = (cssW / p.w) * CSS_UNITS;
    const viewport = page.getViewport({ scale });
    let out = Math.min(window.devicePixelRatio || 1, 2);
    if (viewport.width * viewport.height * out * out > MAX_CANVAS_PIXELS) {
      out = Math.sqrt(MAX_CANVAS_PIXELS / (viewport.width * viewport.height));
    }

    const canvas = document.createElement('canvas');
    canvas.className = 'pdf-canvas';
    canvas.width = Math.floor(viewport.width * out);
    canvas.height = Math.floor(viewport.height * out);
    canvas.style.width = Math.floor(viewport.width) + 'px';
    canvas.style.height = Math.floor(viewport.height) + 'px';

    const annoLayer = document.createElement('div');
    annoLayer.className = 'anno-layer';
    const textDiv = document.createElement('div');
    textDiv.className = 'textLayer';

    p.el.style.setProperty('--total-scale-factor', String(scale));
    p.el.style.setProperty('--scale-round-x', '1px');
    p.el.style.setProperty('--scale-round-y', '1px');
    p.el.append(canvas, annoLayer, textDiv);
    p.canvas = canvas;
    p.annoLayer = annoLayer;
    p.textDiv = textDiv;

    p.task = page.render({
      canvas,
      viewport,
      transform: out !== 1 ? [out, 0, 0, out, 0, 0] : undefined,
    });
    try {
      await p.task.promise;
    } catch (e) {
      if (e && e.name === 'RenderingCancelledException') return;
      throw e;
    }
    if (!current()) return;

    p.textLayer = new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: textDiv, viewport });
    try {
      await p.textLayer.render();
    } catch (e) {
      // cancel() from _unrender rejects render(); anything else is real.
      if (!current()) return;
      throw e;
    }
    if (!current()) return;
    this._applyFind(p);
    this._scheduleDetail();

    p.ink = new InkSurface(p.el, {
      getTool: this.opts.getTool,
      onAdd: s => this.opts.onInkAdd(p.num, s),
      onErase: (ids, gesture) => this.opts.onInkErase(p.num, ids, gesture),
      onRegion: rect => this.opts.onRegion(p.num, rect),
      onTransform: (before, after) => this.opts.onInkTransform && this.opts.onInkTransform(p.num, before, after),
      onEraseAt: (pt, gesture) => {
        if (!this.opts.onEraseMark) return;
        for (const a of this.annos.get(p.num) || []) {
          if (a.data.type !== 'highlight') continue;
          const hit = a.data.rects.some(([x, y, w, h]) => pt.x >= x && pt.x <= x + w && pt.y >= y - 0.004 && pt.y <= y + h + 0.004);
          if (hit) this.opts.onEraseMark(a, gesture);
        }
      },
    });
    p.ink.setStrokes(this.inkByPage.get(p.num) || []);
    this._paintAnnos(p);
  }

  _unrender(p) {
    if (!p.rendered) return;
    p.rendered = false;
    this._dropDetail(p);
    if (p.task) p.task.cancel();
    if (p.textLayer) p.textLayer.cancel();
    if (p.ink) p.ink.destroy();
    for (const k of ['canvas', 'annoLayer', 'textDiv']) {
      if (p[k]) {
        if (k === 'canvas') { p[k].width = 0; p[k].height = 0; }
        p[k].remove();
        p[k] = null;
      }
    }
    p.task = p.textLayer = p.ink = null;
    p.token = null;
  }

  // ── Detail rendering ──
  //
  // iPad Safari caps a canvas at about 16 Mpx, so at high zoom a whole page
  // renders below device resolution. Once scrolling settles, the visible part
  // of each such page is rendered again at full resolution into a canvas
  // laid over it (the approach of pdf.js's own viewer).

  _scheduleDetail() {
    clearTimeout(this._detailTimer);
    this._detailTimer = setTimeout(() => {
      this._renderDetail().catch(e => console.error('Detail rendering failed', e));
    }, 160);
  }

  _dropDetail(p) {
    if (p.detailTask) p.detailTask.cancel();
    p.detailTask = null;
    if (p.detail) {
      p.detail.width = 0;
      p.detail.height = 0;
      p.detail.remove();
    }
    p.detail = null;
  }

  async _renderDetail() {
    if (this.destroyed || !this.pdf) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const view = this.scrollEl.getBoundingClientRect();
    for (const p of this.pages) {
      if (!p.rendered || !p.canvas) continue;
      const r = p.el.getBoundingClientRect();
      const cssW = p.el.clientWidth;
      const sharp = p.canvas.width / cssW >= dpr * 0.9;
      const x0 = Math.max(r.left, view.left), y0 = Math.max(r.top, view.top);
      const x1 = Math.min(r.right, view.right), y1 = Math.min(r.bottom, view.bottom);
      if (sharp || x1 <= x0 || y1 <= y0) {
        this._dropDetail(p);
        continue;
      }
      const x = Math.floor(x0 - r.left), y = Math.floor(y0 - r.top);
      const w = Math.ceil(x1 - x0), h = Math.ceil(y1 - y0);
      const key = [cssW, x, y, w, h].join(',');
      if (p.detail && p.detail.dataset.key === key) continue;

      const token = p.token;
      const page = await this.pdf.getPage(p.num);
      if (p.token !== token || !p.rendered) continue;
      const scale = (cssW / p.w) * CSS_UNITS * dpr;
      const canvas = document.createElement('canvas');
      canvas.className = 'pdf-detail';
      canvas.width = Math.ceil(w * dpr);
      canvas.height = Math.ceil(h * dpr);
      canvas.style.cssText = `left:${x}px;top:${y}px;width:${w}px;height:${h}px`;
      canvas.dataset.key = key;
      const viewport = page.getViewport({ scale, offsetX: -x * dpr, offsetY: -y * dpr });
      if (p.detailTask) p.detailTask.cancel();
      const task = page.render({ canvas, viewport });
      p.detailTask = task;
      try {
        await task.promise;
      } catch (e) {
        if (e && e.name === 'RenderingCancelledException') continue;
        throw e;
      }
      if (p.detailTask !== task || p.token !== token || !p.rendered) continue;
      p.detailTask = null;
      if (p.detail) p.detail.remove();
      p.detail = canvas;
      p.canvas.after(canvas);
    }
  }

  // ── Bookmarks and thumbnails ──

  setBookmarks(pages) {
    const set = new Set(pages);
    for (const p of this.pages) p.el.classList.toggle('bookmarked', set.has(p.num));
  }

  // Renders page num into canvas at cssWidth CSS px wide.
  async renderThumb(num, canvas, cssWidth) {
    const page = await this.pdf.getPage(num);
    const base = page.getViewport({ scale: 1 });
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const viewport = page.getViewport({ scale: (cssWidth / base.width) * dpr });
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    canvas.style.width = cssWidth + 'px';
    canvas.style.height = Math.floor(viewport.height / dpr) + 'px';
    await page.render({ canvas, viewport }).promise;
  }

  // ── Overlays ──

  setInk(page, strokes) {
    this.inkByPage.set(page, strokes);
    const p = this.pages[page - 1];
    if (p && p.ink && !p.ink.penDown) p.ink.setStrokes(strokes);
  }

  setAnnos(annos) {
    this.annos = new Map();
    for (const a of annos) {
      if (!this.annos.has(a.data.page)) this.annos.set(a.data.page, []);
      this.annos.get(a.data.page).push(a);
    }
    for (const p of this.pages) if (p.rendered) this._paintAnnos(p);
  }

  _paintAnnos(p) {
    if (!p.annoLayer) return;
    p.annoLayer.innerHTML = '';
    for (const a of this.annos.get(p.num) || []) {
      for (const [x, y, w, h] of a.data.rects) {
        const d = document.createElement('div');
        d.className = 'anno-mark anno-' + a.data.type;
        d.dataset.anno = a.id;
        d.style.cssText = `left:${x * 100}%;top:${y * 100}%;width:${w * 100}%;height:${h * 100}%;--anno-color:${a.data.color}`;
        p.annoLayer.appendChild(d);
      }
      if (a.data.comment || a.marker || a.data.status) {
        const [x, y] = a.data.rects[0];
        const m = document.createElement('div');
        m.className = 'anno-marker';
        m.dataset.anno = a.id;
        m.style.top = y * 100 + '%';
        m.textContent = a.marker || '•';
        m.title = a.markerTitle || a.data.comment || '';
        if (a.data.status) m.classList.add('anno-' + a.data.status);
        p.annoLayer.appendChild(m);
      }
    }
    const f = this._flash;
    if (f && Date.now() < f.until) {
      for (const el of p.annoLayer.querySelectorAll(`[data-anno="${CSS.escape(f.id)}"]`)) el.classList.add('flash');
    }
  }

  // Annotation under a client point, for taps on highlighted text.
  annoAt(clientX, clientY) {
    for (const p of this.pages) {
      if (!p.rendered) continue;
      const r = p.el.getBoundingClientRect();
      if (clientY < r.top || clientY > r.bottom || clientX < r.left || clientX > r.right) continue;
      const x = (clientX - r.left) / r.width, y = (clientY - r.top) / r.height;
      for (const a of this.annos.get(p.num) || []) {
        for (const [ax, ay, aw, ah] of a.data.rects) {
          if (x >= ax && x <= ax + aw && y >= ay && y <= ay + ah) return a;
        }
      }
    }
    return null;
  }

  // Highlights a mark briefly. The flash survives repaints (a sync can
  // repaint the marks mid-animation) and waits for the page to be painted
  // if the scroll is still on its way.
  flash(annoId) {
    this._flash = { id: annoId, until: Date.now() + 1500 };
    for (const el of this.container.querySelectorAll(`[data-anno="${CSS.escape(annoId)}"]`)) {
      el.classList.remove('flash');
      void el.offsetWidth;
      el.classList.add('flash');
    }
  }

  async showAnno(anno) {
    const [, y] = anno.data.rects[0];
    // A third of the way down, so the passage reads in context.
    this.goTo(anno.data.page, y, 'smooth', this.scrollEl.clientHeight / 3);
    setTimeout(() => this.flash(anno.id), 400);
  }

  pageElement(num) {
    return this.pages[num - 1] && this.pages[num - 1].el;
  }

  // ── Content access ──

  // The table of contents: the PDF's outline (bookmarks) if it has one,
  // otherwise headings detected by font size. Flattened, in reading order:
  // [{ title, depth, page, yFrac }]. Returns { items, source: 'outline' | 'detected' }.
  async contents() {
    if (this._contents) return this._contents;
    const outline = await this.pdf.getOutline();
    const items = [];
    if (outline && outline.length) {
      const walk = async (nodes, depth) => {
        for (const n of nodes) {
          const at = await this._resolveDest(n.dest);
          if (at) items.push({ title: (n.title || '').trim() || 'Untitled', depth, ...at });
          if (n.items && n.items.length) await walk(n.items, depth + 1);
        }
      };
      await walk(outline, 0);
    }
    this._contents = items.length ? { items, source: 'outline' } : { items: await this._detectHeadings(), source: 'detected' };
    return this._contents;
  }

  // { page, yFrac } for an outline destination, or null for links that
  // point outside the document.
  async _resolveDest(dest) {
    try {
      const explicit = typeof dest === 'string' ? await this.pdf.getDestination(dest) : dest;
      if (!Array.isArray(explicit)) return null;
      const ref = explicit[0];
      const index = typeof ref === 'number' ? ref : await this.pdf.getPageIndex(ref);
      let yFrac = 0;
      const top = explicit[1] && explicit[1].name === 'XYZ' ? explicit[3] : explicit[1] && /^FitB?H$/.test(explicit[1].name) ? explicit[2] : null;
      if (typeof top === 'number') {
        const [, y0, , y1] = (await this.pdf.getPage(index + 1)).view;
        yFrac = Math.min(1, Math.max(0, (y1 - top) / (y1 - y0)));
      }
      return { page: index + 1, yFrac };
    } catch (e) {
      console.warn('Outline entry has no usable destination', e);
      return null;
    }
  }

  // Headings in a PDF without an outline: short lines set noticeably larger
  // than the body text. Good enough for most papers; scanned PDFs have none.
  async _detectHeadings(maxPages = 400) {
    const lines = [];
    const sizes = [];
    const n = Math.min(this.numPages, maxPages);
    for (let num = 1; num <= n; num++) {
      const page = await this.pdf.getPage(num);
      const [, y0, , y1] = page.view;
      const tc = await page.getTextContent();
      let cur = null;
      for (const it of tc.items) {
        if (!it.str) continue;
        const size = Math.round(Math.hypot(it.transform[2], it.transform[3]) * 10) / 10;
        const y = it.transform[5];
        sizes.push([size, it.str.length]);
        if (cur && Math.abs(cur.y - y) < size * 0.5 && cur.size === size) cur.text += it.str;
        else {
          cur = { text: it.str, size, y, page: num, yFrac: Math.min(1, Math.max(0, (y1 - y - size) / (y1 - y0))) };
          lines.push(cur);
        }
        if (it.hasEOL) cur = null;
      }
    }
    // Body size: the size carrying the most characters.
    const weight = new Map();
    for (const [size, len] of sizes) weight.set(size, (weight.get(size) || 0) + len);
    const body = [...weight.entries()].sort((a, b) => b[1] - a[1])[0];
    if (!body) return [];
    const headings = lines.filter(l => {
      const t = l.text.trim();
      return l.size >= body[0] * 1.15 && t.length >= 3 && t.length <= 90 && /[A-Za-z]/.test(t);
    });
    const levels = [...new Set(headings.map(h => h.size))].sort((a, b) => b - a);
    return headings.slice(0, 300).map(h => ({ title: h.text.trim(), depth: Math.min(2, levels.indexOf(h.size)), page: h.page, yFrac: h.yFrac }));
  }

  // ── Find ──

  // Every occurrence of query (case-insensitive) in the document text:
  // [{ page, at, text }], where text is the page text and at the offset.
  async find(query, max = 300) {
    const q = query.trim().toLowerCase();
    const out = [];
    if (!q) return out;
    for (let n = 1; n <= this.numPages && out.length < max; n++) {
      const text = await this.pageText(n);
      const low = text.toLowerCase();
      for (let i = low.indexOf(q); i >= 0 && out.length < max; i = low.indexOf(q, i + q.length)) {
        out.push({ page: n, at: i, text });
      }
    }
    return out;
  }

  // Highlights a query on one page (applied when the page paints) and
  // scrolls the first hit into view. null clears it.
  markText(page, query) {
    this._find = query ? { page, q: query.trim().toLowerCase(), scroll: true } : null;
    for (const p of this.pages) if (p.textDiv) this._applyFind(p);
  }

  _applyFind(p) {
    for (const s of p.textDiv.querySelectorAll('.find-hit')) s.classList.remove('find-hit');
    const f = this._find;
    if (!f || f.page !== p.num) return;
    const spans = [...p.textDiv.querySelectorAll('span')];
    let hits = spans.filter(s => s.textContent.toLowerCase().includes(f.q));
    if (!hits.length) {
      // The match spans several text runs: mark the runs holding its words.
      const words = f.q.split(/\s+/).filter(w => w.length > 2);
      hits = spans.filter(s => words.some(w => s.textContent.toLowerCase().includes(w)));
    }
    for (const s of hits) s.classList.add('find-hit');
    if (hits.length && f.scroll) {
      f.scroll = false;
      const r = hits[0].getBoundingClientRect();
      const box = this.scrollEl.getBoundingClientRect();
      this.scrollEl.scrollTo({ top: this.scrollEl.scrollTop + r.top - box.top - this.scrollEl.clientHeight / 3, behavior: 'smooth' });
    }
  }

  async pageText(num) {
    if (this.textCache.has(num)) return this.textCache.get(num);
    const page = await this.pdf.getPage(num);
    const tc = await page.getTextContent();
    let text = '';
    for (const it of tc.items) text += it.str + (it.hasEOL ? '\n' : ' ');
    text = text.replace(/[ \t]+/g, ' ').trim();
    this.textCache.set(num, text);
    return text;
  }

  // Text around a passage: the page plus a bit of the neighbours, capped.
  async contextFor(num, quote, maxChars = 6000) {
    const here = await this.pageText(num);
    let text = here;
    if (num > 1) text = (await this.pageText(num - 1)).slice(-1500) + '\n' + text;
    if (num < this.numPages) text += '\n' + (await this.pageText(num + 1)).slice(0, 1500);
    if (text.length <= maxChars) return text;
    const at = quote ? text.indexOf(quote.slice(0, 40)) : -1;
    const start = Math.max(0, (at < 0 ? text.length / 2 : at) - maxChars / 2);
    return text.slice(start, start + maxChars);
  }

  // PNG of a page region at high resolution, for the vision model.
  async regionImage(num, [x, y, w, h], targetWidth = 1200) {
    const page = await this.pdf.getPage(num);
    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(6, Math.max(1, targetWidth / (w * base.width)));
    const vp = page.getViewport({ scale, offsetX: -x * base.width * scale, offsetY: -y * base.height * scale });
    const canvas = document.createElement('canvas');
    canvas.width = Math.ceil(w * base.width * scale);
    canvas.height = Math.ceil(h * base.height * scale);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvas, viewport: vp }).promise;
    return canvas.toDataURL('image/png');
  }
}
