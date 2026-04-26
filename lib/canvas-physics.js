// Canvas Physics Engine: Draw-to-Simulate
// Turns freeform drawings into interactive physics simulations.
// A student draws a curve, the system fits a Catmull-Rom spline,
// and objects move along it under gravity.

// ── Spline Math ──

function catmullRomPoint(p0, p1, p2, p3, t) {
  const t2 = t * t, t3 = t2 * t;
  return {
    x: 0.5 * ((-p0.x + 3*p1.x - 3*p2.x + p3.x)*t3
            + (2*p0.x - 5*p1.x + 4*p2.x - p3.x)*t2
            + (-p0.x + p2.x)*t
            + 2*p1.x),
    y: 0.5 * ((-p0.y + 3*p1.y - 3*p2.y + p3.y)*t3
            + (2*p0.y - 5*p1.y + 4*p2.y - p3.y)*t2
            + (-p0.y + p2.y)*t
            + 2*p1.y)
  };
}

function catmullRomTangent(p0, p1, p2, p3, t) {
  const t2 = t * t;
  return {
    x: 0.5 * (3*(-p0.x + 3*p1.x - 3*p2.x + p3.x)*t2
            + 2*(2*p0.x - 5*p1.x + 4*p2.x - p3.x)*t
            + (-p0.x + p2.x)),
    y: 0.5 * (3*(-p0.y + 3*p1.y - 3*p2.y + p3.y)*t2
            + 2*(2*p0.y - 5*p1.y + 4*p2.y - p3.y)*t
            + (-p0.y + p2.y))
  };
}

function buildSpline(rawPoints, minDist) {
  // Subsample: keep points at least minDist apart
  const pts = [rawPoints[0]];
  for (let i = 1; i < rawPoints.length; i++) {
    const prev = pts[pts.length - 1];
    const dx = rawPoints[i].x - prev.x, dy = rawPoints[i].y - prev.y;
    if (dx*dx + dy*dy >= minDist * minDist) pts.push(rawPoints[i]);
  }
  // Always include last point
  const last = rawPoints[rawPoints.length - 1];
  const plast = pts[pts.length - 1];
  if (last.x !== plast.x || last.y !== plast.y) pts.push(last);

  if (pts.length < 2) return null;

  // Add phantom endpoints for Catmull-Rom boundary
  const first = pts[0], end = pts[pts.length - 1];
  const controlPoints = [
    { x: 2*first.x - pts[1].x, y: 2*first.y - pts[1].y },
    ...pts,
    { x: 2*end.x - pts[pts.length - 2].x, y: 2*end.y - pts[pts.length - 2].y }
  ];

  // Build arc-length lookup table
  const numSegments = controlPoints.length - 3;
  const samplesPerSeg = 50;
  const totalSamples = numSegments * samplesPerSeg;
  const table = new Float64Array(totalSamples + 1); // table[i] = arc length at sample i
  let cumLen = 0;
  let prevPt = catmullRomPoint(controlPoints[0], controlPoints[1], controlPoints[2], controlPoints[3], 0);
  table[0] = 0;

  for (let i = 1; i <= totalSamples; i++) {
    const globalT = i / totalSamples;
    const seg = Math.min(Math.floor(globalT * numSegments), numSegments - 1);
    const localT = globalT * numSegments - seg;
    const pt = catmullRomPoint(controlPoints[seg], controlPoints[seg+1], controlPoints[seg+2], controlPoints[seg+3], localT);
    const dx = pt.x - prevPt.x, dy = pt.y - prevPt.y;
    cumLen += Math.sqrt(dx*dx + dy*dy);
    table[i] = cumLen;
    prevPt = pt;
  }

  const totalLength = cumLen;

  // Arc-length to global parameter (binary search)
  function paramAtArcLength(s) {
    if (s <= 0) return 0;
    if (s >= totalLength) return 1;
    let lo = 0, hi = totalSamples;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (table[mid] < s) lo = mid; else hi = mid;
    }
    const frac = (s - table[lo]) / (table[hi] - table[lo] || 1);
    return (lo + frac) / totalSamples;
  }

  function evalAt(globalT) {
    const clamped = Math.max(0, Math.min(1, globalT));
    const seg = Math.min(Math.floor(clamped * numSegments), numSegments - 1);
    const localT = clamped * numSegments - seg;
    return catmullRomPoint(controlPoints[seg], controlPoints[seg+1], controlPoints[seg+2], controlPoints[seg+3], localT);
  }

  function tangentAt(globalT) {
    const clamped = Math.max(0, Math.min(1, globalT));
    const seg = Math.min(Math.floor(clamped * numSegments), numSegments - 1);
    const localT = clamped * numSegments - seg;
    return catmullRomTangent(controlPoints[seg], controlPoints[seg+1], controlPoints[seg+2], controlPoints[seg+3], localT);
  }

  return {
    controlPoints,
    totalLength,
    numSegments,
    positionAt(s) { return evalAt(paramAtArcLength(s)); },
    tangentAt(s) { return tangentAt(paramAtArcLength(s)); },
    slopeAngleAt(s) {
      const t = tangentAt(paramAtArcLength(s));
      return Math.atan2(t.y, t.x);
    },
    // Render helper: sample N points along the spline
    samplePoints(n) {
      const pts = [];
      for (let i = 0; i <= n; i++) {
        pts.push(evalAt(i / n));
      }
      return pts;
    }
  };
}

// ── Main API ──

window.createTrackSimulation = function createTrackSimulation(canvas, opts = {}) {
  const ctx = canvas.getContext('2d');
  const {
    gravity = 500,          // px/s^2 (scaled for screen, not 9.8 m/s^2)
    friction = 0.3,         // damping coefficient
    ballRadius = 10,
    drawColor = '#334155',
    drawWidth = 4,
    ballColor = '#3b82f6',
    showSpeed = true,
    showTangent = false,
    minPointDist = 12,      // px between control points
    onUpdate = null
  } = opts;

  let mode = 'draw'; // 'draw' | 'simulate' | 'interact'
  let rawPoints = [];
  let spline = null;
  let animId = null;
  let lastTime = 0;

  // Ball state
  let ballS = 0;   // arc-length position
  let ballV = 0;   // velocity along track

  // Speed history for trail
  const trail = [];
  const TRAIL_MAX = 40;

  // ── Drawing ──

  function pointFromEvent(e) {
    const rect = canvas.getBoundingClientRect();
    const cx = (e.touches ? e.touches[0].clientX : e.clientX);
    const cy = (e.touches ? e.touches[0].clientY : e.clientY);
    return {
      x: (cx - rect.left) * (canvas.width / rect.width),
      y: (cy - rect.top) * (canvas.height / rect.height)
    };
  }

  let drawing = false;

  function onPointerDown(e) {
    if (mode !== 'draw') return;
    e.preventDefault();
    drawing = true;
    rawPoints = [pointFromEvent(e)];
    canvas.setPointerCapture(e.pointerId);
    render();
  }

  function onPointerMove(e) {
    if (!drawing) return;
    e.preventDefault();
    rawPoints.push(pointFromEvent(e));
    render();
  }

  function onPointerUp(e) {
    if (!drawing) return;
    drawing = false;
    if (rawPoints.length >= 3) {
      spline = buildSpline(rawPoints, minPointDist);
    }
    render();
  }

  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointercancel', onPointerUp);
  canvas.style.touchAction = 'none';

  // ── Rendering ──

  function render() {
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Background grid
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 0.5;
    const gridSize = 40;
    for (let x = gridSize; x < w; x += gridSize) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for (let y = gridSize; y < h; y += gridSize) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    if (spline) {
      // Draw track from spline
      const pts = spline.samplePoints(200);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.strokeStyle = drawColor;
      ctx.lineWidth = drawWidth;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.stroke();
    } else if (rawPoints.length > 1) {
      // Draw live preview while user is drawing
      ctx.beginPath();
      ctx.moveTo(rawPoints[0].x, rawPoints[0].y);
      for (let i = 1; i < rawPoints.length; i++) ctx.lineTo(rawPoints[i].x, rawPoints[i].y);
      ctx.strokeStyle = drawColor;
      ctx.lineWidth = drawWidth;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.stroke();
    }

    // Draw prompt text if no track yet
    if (!spline && rawPoints.length === 0 && mode === 'draw') {
      ctx.fillStyle = '#94a3b8';
      ctx.font = '18px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Draw a track for the ball to roll along', w/2, h/2);
      ctx.font = '14px system-ui, sans-serif';
      ctx.fillText('Use your finger, stylus, or mouse', w/2, h/2 + 28);
    }

    if (mode === 'simulate' && spline) {
      // Trail
      ctx.globalAlpha = 0.15;
      for (let i = 0; i < trail.length; i++) {
        const alpha = (i + 1) / trail.length;
        ctx.globalAlpha = alpha * 0.2;
        ctx.beginPath();
        ctx.arc(trail[i].x, trail[i].y, ballRadius * 0.6, 0, Math.PI * 2);
        ctx.fillStyle = ballColor;
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // Ball
      const pos = spline.positionAt(ballS);
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, ballRadius, 0, Math.PI * 2);
      ctx.fillStyle = ballColor;
      ctx.fill();
      ctx.strokeStyle = '#1e40af';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Tangent line
      if (showTangent) {
        const tan = spline.tangentAt(ballS);
        const mag = Math.sqrt(tan.x*tan.x + tan.y*tan.y) || 1;
        const nx = tan.x / mag * 40, ny = tan.y / mag * 40;
        ctx.beginPath();
        ctx.moveTo(pos.x - nx, pos.y - ny);
        ctx.lineTo(pos.x + nx, pos.y + ny);
        ctx.strokeStyle = '#dc2626';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Speed readout
      if (showSpeed) {
        const speed = Math.abs(ballV);
        ctx.fillStyle = '#1e293b';
        ctx.font = 'bold 15px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText('Speed: ' + speed.toFixed(0) + ' px/s', 12, 24);

        // Slope angle in degrees
        const angle = spline.slopeAngleAt(ballS) * 180 / Math.PI;
        ctx.font = '13px system-ui, sans-serif';
        ctx.fillStyle = '#64748b';
        ctx.fillText('Slope: ' + angle.toFixed(1) + '\u00b0', 12, 44);
      }
    }
  }

  // ── Physics ──

  function physicsStep(dt) {
    if (!spline || dt <= 0 || dt > 0.1) return;

    const theta = spline.slopeAngleAt(ballS);
    const a = gravity * Math.sin(theta) - friction * ballV;

    // Semi-implicit Euler
    ballV += a * dt;
    ballS += ballV * dt;

    // Endpoint bounce
    if (ballS <= 0) { ballS = 0; ballV = Math.abs(ballV) * 0.3; }
    if (ballS >= spline.totalLength) { ballS = spline.totalLength; ballV = -Math.abs(ballV) * 0.3; }

    // Kill tiny oscillations at endpoints
    if (Math.abs(ballV) < 2 && (ballS < 1 || ballS > spline.totalLength - 1)) {
      ballV = 0;
    }

    // Trail
    const pos = spline.positionAt(ballS);
    trail.push({ x: pos.x, y: pos.y });
    if (trail.length > TRAIL_MAX) trail.shift();

    if (onUpdate) {
      onUpdate({
        position: pos,
        velocity: ballV,
        speed: Math.abs(ballV),
        slopeAngle: theta,
        arcLength: ballS,
        parameter: ballS / spline.totalLength
      });
    }
  }

  function animationLoop(timestamp) {
    if (mode !== 'simulate') return;
    const dt = lastTime ? (timestamp - lastTime) / 1000 : 0.016;
    lastTime = timestamp;

    physicsStep(dt);
    render();
    animId = requestAnimationFrame(animationLoop);
  }

  // ── Public API ──

  const api = {
    setMode(newMode) {
      mode = newMode;
      if (mode === 'simulate' && spline) {
        ballS = 0;
        ballV = 0;
        trail.length = 0;
        lastTime = 0;
        animId = requestAnimationFrame(animationLoop);
      } else {
        if (animId) { cancelAnimationFrame(animId); animId = null; }
      }
      render();
    },

    reset() {
      if (animId) { cancelAnimationFrame(animId); animId = null; }
      rawPoints = [];
      spline = null;
      ballS = 0;
      ballV = 0;
      trail.length = 0;
      mode = 'draw';
      render();
    },

    getTrackData() {
      return spline ? spline.controlPoints.slice() : null;
    },

    setTrackData(points) {
      if (points && points.length >= 4) {
        rawPoints = points;
        spline = buildSpline(points, minPointDist);
        render();
      }
    },

    hasTrack() { return !!spline; },

    getSpeedAt(s) {
      // Instantaneous speed requires simulation state; return current
      return Math.abs(ballV);
    },

    getSlopeAt(s) {
      if (!spline) return 0;
      return spline.slopeAngleAt(s);
    },

    getSpline() { return spline; },

    render,

    destroy() {
      if (animId) cancelAnimationFrame(animId);
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('pointercancel', onPointerUp);
    }
  };

  // Initial render
  render();
  return api;
}

// ── Loop-the-loop preset ──
// A pre-loaded ramp + circular loop track. The student picks a drop height
// (in units of R) and watches the ball roll. Frictionless: minimum height
// for loop completion is exactly 2.5 R, derivable by combining energy
// conservation with the centripetal-force-at-loop-top constraint.

window.createLoopSimulation = function createLoopSimulation(canvas, opts) {
  opts = opts || {};
  const ctx = canvas.getContext('2d');
  const gravity = opts.gravity || 600;
  const ballRadius = opts.ballRadius || 11;
  const trackColor = opts.trackColor || '#334155';
  const trackWidth = opts.trackWidth || 4;
  const ballColor = opts.ballColor || '#3b82f6';
  const onResult = opts.onResult || null;

  // Geometry — keep canvas at 800 × 480 for these constants to read well.
  const cx = 560, cy = 240, R = 80;
  const rampTopX = 50, rampTopY = 50;
  const entryAngleDeg = 135;
  const entryRad = entryAngleDeg * Math.PI / 180;
  const rampEndX = cx + R * Math.cos(entryRad);
  const rampEndY = cy + R * Math.sin(entryRad);
  const loopBottomY = cy + R;            // largest visual y on the loop
  const loopArcDeg = 345;                // leave a small visible gap
  const loopSegments = 24;
  const exitEndX = 760, exitEndY = 470;

  let mode = 'idle';   // 'idle' | 'simulate' | 'success' | 'fail'
  let heightR = 1.5;
  let spline = null;
  let dropPos = null;
  let loopStartS = 0;
  let loopEndS = 0;
  let ballS = 0;
  let ballV = 0;
  let trail = [];
  let animId = null;
  let lastTime = 0;
  let failReason = '';

  function buildTrack(h) {
    const dropY = loopBottomY - h * R;
    const t = (dropY - rampTopY) / (rampEndY - rampTopY);
    const dropX = rampTopX + t * (rampEndX - rampTopX);
    dropPos = { x: dropX, y: dropY };

    const points = [];
    const rampSegs = 5;
    for (let i = 0; i <= rampSegs; i++) {
      const tt = i / rampSegs;
      points.push({
        x: dropX + tt * (rampEndX - dropX),
        y: dropY + tt * (rampEndY - dropY)
      });
    }
    const rampLen = Math.hypot(rampEndX - dropX, rampEndY - dropY);

    for (let i = 1; i <= loopSegments; i++) {
      const angleDeg = entryAngleDeg - (i * loopArcDeg / loopSegments);
      const rad = angleDeg * Math.PI / 180;
      points.push({ x: cx + R * Math.cos(rad), y: cy + R * Math.sin(rad) });
    }

    const lastLoopP = points[points.length - 1];
    const exitSegs = 4;
    for (let i = 1; i <= exitSegs; i++) {
      const tt = i / exitSegs;
      points.push({
        x: lastLoopP.x + tt * (exitEndX - lastLoopP.x),
        y: lastLoopP.y + tt * (exitEndY - lastLoopP.y)
      });
    }

    spline = buildSpline(points, 8);
    loopStartS = rampLen;
    loopEndS = loopStartS + R * loopArcDeg * Math.PI / 180;
  }

  function setHeight(h) {
    heightR = Math.max(0.5, Math.min(3.5, h));
    if (mode === 'simulate') return;
    mode = 'idle';
    failReason = '';
    buildTrack(heightR);
    ballS = 0; ballV = 0; trail = [];
    render();
  }

  function start() {
    if (mode === 'simulate') return;
    mode = 'simulate';
    failReason = '';
    buildTrack(heightR);
    ballS = 0; ballV = 0; trail = []; lastTime = 0;
    animId = requestAnimationFrame(step);
  }

  function reset() {
    if (animId) { cancelAnimationFrame(animId); animId = null; }
    mode = 'idle';
    failReason = '';
    buildTrack(heightR);
    ballS = 0; ballV = 0; trail = [];
    render();
  }

  function step(timestamp) {
    if (mode !== 'simulate') return;
    const dt = lastTime ? Math.min((timestamp - lastTime) / 1000, 0.04) : 0.016;
    lastTime = timestamp;

    const theta = spline.slopeAngleAt(ballS);
    const a = gravity * Math.sin(theta);
    ballV += a * dt;
    ballS += ballV * dt;

    if (ballS < 0) {
      ballS = 0; ballV = 0;
      finish(false, 'Ball rolled back without reaching the loop.');
      return;
    }
    if (ballS > spline.totalLength) {
      ballS = spline.totalLength;
      finish(true, 'Loop completed!');
      return;
    }

    // Loss-of-contact check on the upper half of the loop.
    if (ballS > loopStartS && ballS < loopEndS) {
      const pos = spline.positionAt(ballS);
      const dx = pos.x - cx, dy = pos.y - cy;
      const angle = Math.atan2(dy, dx);
      const sinT = Math.sin(angle);
      if (sinT < 0) {
        const required = -sinT * gravity * R;
        if (ballV * ballV < required) {
          finish(false, 'Ball fell off at the top of the loop.');
          return;
        }
      }
    }

    const pos = spline.positionAt(ballS);
    trail.push({ x: pos.x, y: pos.y });
    if (trail.length > 80) trail.shift();

    render();
    animId = requestAnimationFrame(step);
  }

  function finish(success, reason) {
    mode = success ? 'success' : 'fail';
    failReason = reason;
    if (animId) { cancelAnimationFrame(animId); animId = null; }
    render();
    if (onResult) onResult({ success, reason, heightR });
  }

  function render() {
    const w = canvas.width, h = canvas.height;
    ctx.fillStyle = '#fafafa';
    ctx.fillRect(0, 0, w, h);

    // Loop center crosshair (faint)
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(cx, cy, R, 0, Math.PI * 2); ctx.stroke();

    // Full-ramp guide (dashed, even when track is shorter)
    ctx.strokeStyle = '#cbd5e1';
    ctx.setLineDash([5, 5]);
    ctx.beginPath();
    ctx.moveTo(rampTopX, rampTopY);
    ctx.lineTo(rampEndX, rampEndY);
    ctx.stroke();
    ctx.setLineDash([]);

    if (!spline) return;

    // Track
    const pts = spline.samplePoints(200);
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
    ctx.strokeStyle = trackColor;
    ctx.lineWidth = trackWidth;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.stroke();

    // Drop indicator at start of track
    if (mode !== 'simulate') {
      ctx.beginPath();
      ctx.arc(dropPos.x, dropPos.y, ballRadius + 3, 0, Math.PI * 2);
      ctx.fillStyle = '#fde68a';
      ctx.fill();
      ctx.strokeStyle = '#d97706';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Loop top reference line
    ctx.strokeStyle = '#e2e8f0';
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    ctx.moveTo(0, cy - R); ctx.lineTo(w, cy - R);
    ctx.stroke();
    ctx.setLineDash([]);

    // Trail
    for (let i = 0; i < trail.length; i++) {
      ctx.globalAlpha = ((i + 1) / trail.length) * 0.35;
      ctx.beginPath();
      ctx.arc(trail[i].x, trail[i].y, ballRadius * 0.55, 0, Math.PI * 2);
      ctx.fillStyle = ballColor;
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Ball
    if (mode === 'simulate' || mode === 'success' || mode === 'fail') {
      const pos = spline.positionAt(ballS);
      ctx.beginPath();
      ctx.arc(pos.x, pos.y, ballRadius, 0, Math.PI * 2);
      ctx.fillStyle = ballColor;
      ctx.fill();
      ctx.strokeStyle = '#1e3a8a';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Labels
    ctx.fillStyle = '#1e293b';
    ctx.font = 'bold 16px system-ui, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('Drop height: ' + heightR.toFixed(2) + ' × R', 14, 26);
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillStyle = '#64748b';
    ctx.fillText('Loop radius R = ' + R + 'px', 14, 44);

    if (mode === 'success' || mode === 'fail') {
      const color = mode === 'success' ? '#16a34a' : '#dc2626';
      ctx.fillStyle = color;
      ctx.fillRect(0, h - 36, w, 36);
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 16px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(failReason, w / 2, h - 13);
      ctx.textAlign = 'left';
    }
  }

  canvas.style.touchAction = 'none';
  buildTrack(heightR);
  render();

  return {
    setHeight,
    start,
    reset,
    getHeight: function () { return heightR; },
    getMode: function () { return mode; },
    destroy: function () { if (animId) cancelAnimationFrame(animId); }
  };
};
