// Why Academy — ink surface for PDF pages and notebook blocks
//
// Input model (iPad first):
//   - Apple Pencil draws, erases or drags a region, depending on the tool.
//   - Fingers never draw: they scroll, pinch and select text natively.
//   - A mouse draws only when a drawing tool is active.
// Safari scrolls on its own native layer, so a Pencil touch has to cancel its
// touchstart (touchType 'stylus') or the page pans under the pen.
//
// Strokes are stored in coordinates normalized to the surface (0..1), with
// width relative to the surface width, so they survive zoom and resize.

import { newId } from './model.js';

export const INK_COLORS = ['#1f2937', '#2563eb', '#dc2626', '#059669'];
export const HIGHLIGHT_COLORS = ['#fde047', '#86efac', '#f9a8d4', '#93c5fd'];

const DRAW_TOOLS = new Set(['pen', 'highlighter', 'eraser', 'region']);
const MAX_DPR = 2;

function isStylusTouch(e) {
  for (const t of e.changedTouches) if (t.touchType === 'stylus') return true;
  return false;
}

function isPenEraser(e) {
  // Barrel eraser on Surface / Wacom pens.
  return e.pointerType === 'pen' && (e.button === 5 || (e.buttons & 32) === 32);
}

export function drawStroke(ctx, s, w, h) {
  const p = s.points;
  if (p.length < 3) return;
  const base = s.width * w;
  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = s.color;
  if (s.tool === 'highlighter') {
    ctx.globalAlpha = 0.35;
    ctx.globalCompositeOperation = 'multiply';
    ctx.lineCap = 'butt';
    ctx.lineWidth = base;
    ctx.beginPath();
    ctx.moveTo(p[0] * w, p[1] * h);
    for (let i = 3; i < p.length; i += 3) ctx.lineTo(p[i] * w, p[i + 1] * h);
    ctx.stroke();
    ctx.restore();
    return;
  }
  if (p.length === 3) {
    ctx.fillStyle = s.color;
    ctx.beginPath();
    ctx.arc(p[0] * w, p[1] * h, base * (0.6 + p[2] * 0.6) / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    return;
  }
  // Quadratic smoothing through midpoints; width follows pressure per segment.
  let prevX = p[0] * w, prevY = p[1] * h;
  for (let i = 3; i < p.length; i += 3) {
    const x = p[i] * w, y = p[i + 1] * h;
    const nx = i + 3 < p.length ? p[i + 3] * w : x;
    const ny = i + 3 < p.length ? p[i + 4] * h : y;
    const mx = (x + nx) / 2, my = (y + ny) / 2;
    ctx.lineWidth = base * (0.6 + p[i + 2] * 0.8);
    ctx.beginPath();
    ctx.moveTo(prevX, prevY);
    ctx.quadraticCurveTo(x, y, mx, my);
    ctx.stroke();
    prevX = mx;
    prevY = my;
  }
  ctx.restore();
}

function strokeHit(s, x, y, r) {
  const p = s.points;
  const r2 = r * r;
  for (let i = 0; i < p.length; i += 3) {
    const dx = p[i] - x, dy = p[i + 1] - y;
    if (dx * dx + dy * dy <= r2) return true;
    if (i + 3 < p.length) {
      // distance to segment
      const ax = p[i], ay = p[i + 1], bx = p[i + 3], by = p[i + 4];
      const vx = bx - ax, vy = by - ay;
      const len = vx * vx + vy * vy;
      if (len > 0) {
        const t = Math.max(0, Math.min(1, ((x - ax) * vx + (y - ay) * vy) / len));
        const ex = ax + t * vx - x, ey = ay + t * vy - y;
        if (ex * ex + ey * ey <= r2) return true;
      }
    }
  }
  return false;
}

/**
 * InkSurface — draws on a canvas laid over `host`. Pointer events are taken
 * on the host so that layers below (e.g. the PDF text layer) still receive
 * finger and mouse input when no drawing tool is active.
 *
 * opts.getTool()      -> { tool: 'select'|'pen'|'highlighter'|'eraser'|'region', color, width }
 * opts.onAdd(stroke)  -> a stroke was finished
 * opts.onErase(ids)   -> strokes were erased
 * opts.onEraseAt(pt)  -> optional: the eraser passed over pt (normalized), e.g. to erase highlights
 * opts.onRegion(rect) -> region tool: [x, y, w, h] normalized
 * opts.aspect         -> optional fixed height/width ratio (notebook blocks)
 */
export class InkSurface {
  constructor(host, opts) {
    this.host = host;
    this.opts = opts;
    this.strokes = [];
    this.active = null;
    this.erasing = false;
    this.erased = [];
    this.region = null;
    this.penDown = false;

    this.base = document.createElement('canvas');
    this.live = document.createElement('canvas');
    for (const c of [this.base, this.live]) {
      c.className = 'ink-canvas';
      c.setAttribute('aria-hidden', 'true');
      host.appendChild(c);
    }
    this.bctx = this.base.getContext('2d');
    this.lctx = this.live.getContext('2d');

    this._bind();
    this.resize();
  }

  destroy() {
    this._abort.abort();
    this.base.remove();
    this.live.remove();
  }

  setStrokes(strokes) {
    this.strokes = strokes.slice();
    this.redraw();
  }

  resize() {
    const r = this.host.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
    this.w = r.width;
    this.h = r.height;
    for (const c of [this.base, this.live]) {
      c.width = Math.max(1, Math.round(r.width * dpr));
      c.height = Math.max(1, Math.round(r.height * dpr));
      c.style.width = r.width + 'px';
      c.style.height = r.height + 'px';
      c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    this.redraw();
  }

  redraw() {
    this.bctx.clearRect(0, 0, this.w, this.h);
    for (const s of this.strokes) drawStroke(this.bctx, s, this.w, this.h);
  }

  _drawLive() {
    this.lctx.clearRect(0, 0, this.w, this.h);
    if (this.active) drawStroke(this.lctx, this.active, this.w, this.h);
    if (this.region) {
      const [x, y, w, h] = this._regionRect();
      this.lctx.save();
      this.lctx.setLineDash([6, 4]);
      this.lctx.strokeStyle = '#2563eb';
      this.lctx.lineWidth = 1.5;
      this.lctx.fillStyle = 'rgba(37, 99, 235, 0.08)';
      this.lctx.fillRect(x * this.w, y * this.h, w * this.w, h * this.h);
      this.lctx.strokeRect(x * this.w, y * this.h, w * this.w, h * this.h);
      this.lctx.restore();
    }
  }

  // Clamped to the surface: pointer capture keeps reporting positions after
  // the pen leaves it.
  _regionRect() {
    const c = v => Math.min(1, Math.max(0, v));
    const x0 = c(this.region.x0), y0 = c(this.region.y0), x1 = c(this.region.x1), y1 = c(this.region.y1);
    return [Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0)];
  }

  _point(e) {
    const r = this.host.getBoundingClientRect();
    return {
      x: (e.clientX - r.left) / r.width,
      y: (e.clientY - r.top) / r.height,
      p: e.pointerType === 'pen' ? (e.pressure || 0.5) : 0.5,
    };
  }

  // Whether this pointer should ink rather than fall through to the page.
  _claims(e) {
    const { tool } = this.opts.getTool();
    if (e.pointerType === 'touch') return false;
    if (isPenEraser(e)) return true;
    return DRAW_TOOLS.has(tool);
  }

  _bind() {
    this._abort = new AbortController();
    const sig = { signal: this._abort.signal };
    const host = this.host;

    host.addEventListener('touchstart', e => {
      if (isStylusTouch(e) && DRAW_TOOLS.has(this.opts.getTool().tool)) e.preventDefault();
    }, { passive: false, signal: this._abort.signal });
    host.addEventListener('touchmove', e => {
      if (this.penDown && isStylusTouch(e)) e.preventDefault();
    }, { passive: false, signal: this._abort.signal });

    host.addEventListener('pointerdown', e => {
      if (this.penDown && e.pointerType === 'touch') return; // palm while writing
      if (!this._claims(e)) return;
      e.preventDefault();
      e.stopPropagation();
      if (window.getSelection) window.getSelection().removeAllRanges();
      try {
        host.setPointerCapture(e.pointerId);
      } catch (err) {
        // Synthetic events (tests) and pointers that already lifted have no
        // capturable pointer; the stroke still works without capture.
        console.warn('Ink: pointer capture unavailable', err.name);
      }
      this.penDown = true;
      this.pointerId = e.pointerId;

      const t = this.opts.getTool();
      const pt = this._point(e);
      if (isPenEraser(e) || t.tool === 'eraser') {
        this.erasing = true;
        this.erased = [];
        this._eraseAt(pt);
      } else if (t.tool === 'region') {
        this.region = { x0: pt.x, y0: pt.y, x1: pt.x, y1: pt.y };
      } else {
        this.active = {
          id: newId(),
          tool: t.tool === 'highlighter' ? 'highlighter' : 'pen',
          color: t.color,
          width: t.width,
          points: [pt.x, pt.y, pt.p],
        };
      }
      this._drawLive();
    }, sig);

    host.addEventListener('pointermove', e => {
      if (!this.penDown || e.pointerId !== this.pointerId) return;
      e.preventDefault();
      const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
      for (const ev of events.length ? events : [e]) {
        const pt = this._point(ev);
        if (this.erasing) this._eraseAt(pt);
        else if (this.region) {
          this.region.x1 = pt.x;
          this.region.y1 = pt.y;
        } else if (this.active) {
          const p = this.active.points;
          const dx = (pt.x - p[p.length - 3]) * this.w, dy = (pt.y - p[p.length - 2]) * this.h;
          if (dx * dx + dy * dy < 1) continue; // under a CSS pixel
          p.push(pt.x, pt.y, pt.p);
        }
      }
      this._drawLive();
    }, sig);

    const finish = (e, cancelled) => {
      if (!this.penDown || e.pointerId !== this.pointerId) return;
      this.penDown = false;
      if (this.erasing) {
        this.erasing = false;
        if (this.erased.length) this.opts.onErase(this.erased);
      } else if (this.region) {
        const rect = this._regionRect();
        this.region = null;
        if (!cancelled && rect[2] * this.w > 8 && rect[3] * this.h > 8) this.opts.onRegion(rect);
      } else if (this.active) {
        const s = this.active;
        this.active = null;
        if (!cancelled) {
          // The vault accepts -0.5..1.5; strokes that run off the edge are
          // kept, but clamped just outside it.
          s.points = s.points.map(v => Math.round(Math.min(1.4, Math.max(-0.4, v)) * 100000) / 100000);
          this.strokes.push(s);
          drawStroke(this.bctx, s, this.w, this.h);
          this.opts.onAdd(s);
        }
      }
      this._drawLive();
    };
    host.addEventListener('pointerup', e => finish(e, false), sig);
    host.addEventListener('pointercancel', e => finish(e, true), sig);
  }

  _eraseAt(pt) {
    if (this.opts.onEraseAt) this.opts.onEraseAt(pt);
    const r = 10 / this.w;
    const hit = this.strokes.filter(s => strokeHit(s, pt.x, pt.y, r + s.width / 2));
    if (!hit.length) return;
    const ids = new Set(hit.map(s => s.id));
    this.strokes = this.strokes.filter(s => !ids.has(s.id));
    this.erased.push(...ids);
    this.redraw();
  }

  // PNG of the ink (white background) for handwriting recognition.
  toPng(maxWidth = 1400) {
    const scale = Math.min(1, maxWidth / this.w) * 2;
    const c = document.createElement('canvas');
    c.width = Math.round(this.w * scale);
    c.height = Math.round(this.h * scale);
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, c.width, c.height);
    for (const s of this.strokes) drawStroke(ctx, s, c.width, c.height);
    return c.toDataURL('image/png');
  }
}
