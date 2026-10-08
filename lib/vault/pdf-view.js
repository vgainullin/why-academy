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
   * opts.onRegion(page, rect), opts.onAnnoTap(annoId, event)
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
    const first = await this.pdf.getPage(1);
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

    this._onScroll = () => this._trackPage();
    this.scrollEl.addEventListener('scroll', this._onScroll, { passive: true });
    this._onResize = () => { if (this.fitWidth) this.layout(); };
    window.addEventListener('resize', this._onResize);
    return n;
  }

  destroy() {
    if (this._io) this._io.disconnect();
    if (this._onScroll) this.scrollEl.removeEventListener('scroll', this._onScroll);
    if (this._onResize) window.removeEventListener('resize', this._onResize);
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
    const anchor = this.position();
    for (const p of this.pages) {
      const s = this.scaleFor(this.pages[0]);
      p.el.style.width = Math.floor(p.w * s) + 'px';
      p.el.style.height = Math.floor(p.h * s) + 'px';
      if (p.rendered) this._unrender(p);
    }
    this._renderVisible();
    if (anchor) this.goTo(anchor.page, anchor.frac, 'instant', 0);
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

  setZoom(zoom, fitWidth) {
    this.zoom = Math.max(0.25, Math.min(4, zoom));
    this.fitWidth = fitWidth;
    this.layout();
  }

  // Scrolls so that yFrac of the page sits `margin` px below the top.
  goTo(page, yFrac = 0, behavior = 'smooth', margin = 24) {
    const p = this.pages[page - 1];
    if (!p) return;
    const top = this._top(p) + yFrac * p.el.offsetHeight - margin;
    this.scrollEl.scrollTo({ top: Math.max(0, top), behavior });
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
    for (const num of want.slice(0, MAX_RENDERED)) this._render(this.pages[num - 1]);
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
    const page = await this.pdf.getPage(p.num);
    if (!p.rendered) return;

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
    if (!p.rendered) return;

    p.textLayer = new pdfjs.TextLayer({ textContentSource: page.streamTextContent(), container: textDiv, viewport });
    await p.textLayer.render();

    p.ink = new InkSurface(p.el, {
      getTool: this.opts.getTool,
      onAdd: s => this.opts.onInkAdd(p.num, s),
      onErase: ids => this.opts.onInkErase(p.num, ids),
      onRegion: rect => this.opts.onRegion(p.num, rect),
    });
    p.ink.setStrokes(this.inkByPage.get(p.num) || []);
    this._paintAnnos(p);
  }

  _unrender(p) {
    if (!p.rendered) return;
    p.rendered = false;
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
