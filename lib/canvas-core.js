// Why Academy — Canvas Core
// Unified DrawingCanvas class that encapsulates stroke rendering, pointer
// events, eraser handling, and iOS Safari touch fixes. Used by handwrite,
// canvas-derive, playground, and canvas-physics.
(function () {
  'use strict';

  const C = window.WhyCommon;

  /**
   * DrawingCanvas — a drawing surface with pressure-sensitive strokes,
   * stylus eraser support, keyboard eraser toggle, and undo/clear.
   *
   * @param {HTMLCanvasElement} canvas
   * @param {object} opts
   * @param {string}  [opts.inkColor='#1f2937']    Stroke color
   * @param {string}  [opts.bgColor='#fff']        Initial background color
   * @param {boolean} [opts.transparentBg=false]   If true, no initial fill
   * @param {function} [opts.onStrokeChange]       Called after any stroke add/remove/undo/clear
   * @param {function} [opts.onEraseStart]         Called when eraser mode activates
   * @param {function} [opts.onEraseEnd]           Called when eraser mode deactivates
   */
  function DrawingCanvas(canvas, opts) {
    opts = opts || {};
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ctx.lineCap = 'round';
    this.ctx.lineJoin = 'round';
    this.ctx.strokeStyle = opts.inkColor || '#1f2937';

    this._onStrokeChange = opts.onStrokeChange || null;
    this._onEraseStart = opts.onEraseStart || null;
    this._onEraseEnd = opts.onEraseEnd || null;

    this.strokes = [];
    this.active = null;
    this.eraserMode = false;
    this._activeErasing = false;
    this._erasedSinceDown = false;

    // Keyboard eraser toggle
    this._keyHandler = null;

    this._initCanvas(opts);
  }

  DrawingCanvas.prototype._initCanvas = function (opts) {
    var self = this;
    var canvas = this.canvas;

    canvas.style.touchAction = 'none';
    canvas.style.userSelect = 'none';
    canvas.style.webkitUserSelect = 'none';
    canvas.style.webkitTouchCallout = 'none';
    canvas.style.webkitTapHighlightColor = 'transparent';

    if (!opts.transparentBg) {
      this.ctx.fillStyle = opts.bgColor || '#fff';
      this.ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    canvas.addEventListener('touchstart', function (e) {
      e.preventDefault();
      if (window.getSelection) window.getSelection().removeAllRanges();
    }, { passive: false });
    canvas.addEventListener('touchmove', function (e) {
      e.preventDefault();
    }, { passive: false });

    canvas.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      if (window.getSelection) window.getSelection().removeAllRanges();
      canvas.setPointerCapture(e.pointerId);
      var p = self._pointFromEvent(e);

      if (C.isEraserPointerEvent(e, self.eraserMode)) {
        self._activeErasing = true;
        self._erasedSinceDown = false;
        self._eraseAtPoint(p);
        if (self._onEraseStart) self._onEraseStart();
        return;
      }

      var baseW = C.getStrokeWidth();
      var w = e.pointerType === 'pen'
        ? baseW * (0.65 + (p.pressure || 0.5) * 0.7)
        : baseW;
      self.active = { points: [p], width: w };
      self._repaint();
    });

    canvas.addEventListener('pointermove', function (e) {
      if (self._activeErasing) {
        self._eraseAtPoint(self._pointFromEvent(e));
        return;
      }
      if (!self.active) return;
      self.active.points.push(self._pointFromEvent(e));
      self._repaint();
    });

    canvas.addEventListener('pointerup', function () {
      if (self._activeErasing) {
        self._activeErasing = false;
        if (self._erasedSinceDown && self._onEraseEnd) self._onEraseEnd();
        return;
      }
      if (!self.active) return;
      self.strokes.push(self.active);
      self.active = null;
      self._repaint();
      if (self._onStrokeChange) self._onStrokeChange();
    });

    canvas.addEventListener('pointercancel', function () {
      self._activeErasing = false;
      self.active = null;
      self._repaint();
    });
  };

  DrawingCanvas.prototype._pointFromEvent = function (e) {
    var rect = this.canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (this.canvas.width / rect.width),
      y: (e.clientY - rect.top) * (this.canvas.height / rect.height),
      pressure: e.pressure || 0.5
    };
  };

  DrawingCanvas.prototype._eraseAtPoint = function (p) {
    var idx = C.findStrokeHitByPoint(this.strokes, p, 12);
    if (idx >= 0) {
      this.strokes.splice(idx, 1);
      this._erasedSinceDown = true;
      this._repaint();
      if (this._onStrokeChange) this._onStrokeChange();
    }
  };

  DrawingCanvas.prototype._repaint = function () {
    var ctx = this.ctx;
    var canvas = this.canvas;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (var i = 0; i < this.strokes.length; i++) {
      this._drawStroke(this.strokes[i]);
    }
    if (this.active) this._drawStroke(this.active);
  };

  DrawingCanvas.prototype._drawStroke = function (stroke) {
    var ctx = this.ctx;
    if (stroke.points.length < 2) {
      if (stroke.points.length === 1) {
        var p = stroke.points[0];
        ctx.beginPath();
        ctx.arc(p.x, p.y, stroke.width / 2, 0, Math.PI * 2);
        ctx.fillStyle = ctx.strokeStyle;
        ctx.fill();
      }
      return;
    }
    ctx.lineWidth = stroke.width;
    ctx.beginPath();
    ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
    for (var i = 1; i < stroke.points.length - 1; i++) {
      var p0 = stroke.points[i];
      var p1 = stroke.points[i + 1];
      ctx.quadraticCurveTo(p0.x, p0.y, (p0.x + p1.x) / 2, (p0.y + p1.y) / 2);
    }
    var last = stroke.points[stroke.points.length - 1];
    ctx.lineTo(last.x, last.y);
    ctx.stroke();
  };

  // ── Public API ──

  DrawingCanvas.prototype.paint = function () {
    this._repaint();
  };

  DrawingCanvas.prototype.undo = function () {
    this.strokes.pop();
    this._repaint();
    if (this._onStrokeChange) this._onStrokeChange();
  };

  DrawingCanvas.prototype.clear = function () {
    this.strokes = [];
    this._repaint();
    if (this._onStrokeChange) this._onStrokeChange();
  };

  DrawingCanvas.prototype.isEmpty = function () {
    return this.strokes.length === 0 && this.active === null;
  };

  DrawingCanvas.prototype.strokeCount = function () {
    return this.strokes.length;
  };

  DrawingCanvas.prototype.getDataUrl = function (pad) {
    pad = pad || 24;
    var canvas = this.canvas;
    var ctx = this.ctx;
    var img = ctx.getImageData(0, 0, canvas.width, canvas.height);
    var minX = canvas.width, minY = canvas.height, maxX = 0, maxY = 0;
    var found = false;

    for (var y = 0; y < canvas.height; y++) {
      for (var x = 0; x < canvas.width; x++) {
        var i = (y * canvas.width + x) * 4;
        if (img.data[i + 3] > 0 && img.data[i] < 200) {
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
          found = true;
        }
      }
    }
    if (!found) return null;

    minX = Math.max(0, minX - pad);
    minY = Math.max(0, minY - pad);
    maxX = Math.min(canvas.width, maxX + pad);
    maxY = Math.min(canvas.height, maxY + pad);
    var w = maxX - minX, h = maxY - minY;

    var out = document.createElement('canvas');
    out.width = w;
    out.height = h;
    var octx = out.getContext('2d');
    octx.fillStyle = '#fff';
    octx.fillRect(0, 0, w, h);
    octx.drawImage(canvas, minX, minY, w, h, 0, 0, w, h);
    return out.toDataURL('image/png');
  };

  DrawingCanvas.prototype.enableKeyboardEraser = function () {
    var self = this;
    if (this._keyHandler) return;
    this._keyHandler = function (e) {
      if (e.key !== 'e' && e.key !== 'E') return;
      var tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      self.eraserMode = !self.eraserMode;
      self.canvas.classList.toggle('eraser-active', self.eraserMode);
    };
    document.addEventListener('keydown', this._keyHandler);
  };

  DrawingCanvas.prototype.disableKeyboardEraser = function () {
    if (this._keyHandler) {
      document.removeEventListener('keydown', this._keyHandler);
      this._keyHandler = null;
    }
  };

  DrawingCanvas.prototype.destroy = function () {
    this.disableKeyboardEraser();
  };

  // ── Exports ──
  window.DrawingCanvas = DrawingCanvas;
})();