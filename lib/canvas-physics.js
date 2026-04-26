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

  // Curvature vector at arc-length s, computed by *symmetric* central second-
  // difference of the arc-length-parameterized position. Magnitude is κ;
  // direction is the unit normal pointing toward the center of curvature.
  // Returns zero near endpoints, where a symmetric stencil isn't available
  // (a one-sided difference would estimate the tangent, not the curvature).
  // The δ scale is chosen large enough to average over Catmull-Rom's seam
  // wiggles between control points but small enough to localize within a
  // typical track feature.
  function curvatureAt(s) {
    const delta = 4.0; // px — large enough to be stable, small enough to localize
    if (s < delta || s > totalLength - delta) return { kappa: 0, nx: 0, ny: 0 };
    const pm = evalAt(paramAtArcLength(s - delta));
    const pc = evalAt(paramAtArcLength(s));
    const pp = evalAt(paramAtArcLength(s + delta));
    const ax = (pp.x - 2 * pc.x + pm.x) / (delta * delta);
    const ay = (pp.y - 2 * pc.y + pm.y) / (delta * delta);
    const kappa = Math.hypot(ax, ay);
    if (kappa < 1e-6) return { kappa: 0, nx: 0, ny: 0 };
    return { kappa, nx: ax / kappa, ny: ay / kappa };
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
    curvatureAt,
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

// ── Track builder: ramp + circular loop ──
// Generates control points for a straight ramp leading *tangentially* into a
// (nearly) closed circular loop, plus a short exit ramp. The tangent match at
// the entry is essential: without it the spline kinks at the seam and the
// curvature primitive reports a spurious wrong-direction spike. Pure geometry
// — no physics, no UI, no DOM. The simulator consumes whatever points come
// back.
//
// Returns: { points, dropPos } — drop position is the first control point
// (the simulator starts the ball at s = 0 by convention).
window.buildRampLoopTrack = function buildRampLoopTrack(opts) {
  opts = opts || {};
  const cx = opts.cx != null ? opts.cx : 560;
  const cy = opts.cy != null ? opts.cy : 240;
  const R = opts.R != null ? opts.R : 80;
  const heightR = opts.heightR != null ? opts.heightR : 1.5;
  const entryAngleDeg = opts.entryAngleDeg != null ? opts.entryAngleDeg : 135;
  const loopArcDeg = opts.loopArcDeg != null ? opts.loopArcDeg : 345;
  const loopSegments = opts.loopSegments != null ? opts.loopSegments : 48;
  const exitLen = opts.exitLen != null ? opts.exitLen : 240;

  // Entry point on the loop and the tangent direction at that point. Going
  // CCW visually (math θ decreasing), the velocity at angle θ on the circle
  // is proportional to (sin θ, −cos θ); the entry tangent matches this and
  // the ramp must arrive along it.
  const entryRad = entryAngleDeg * Math.PI / 180;
  const entryX = cx + R * Math.cos(entryRad);
  const entryY = cy + R * Math.sin(entryRad);
  const tanX = Math.sin(entryRad);   // unit vector
  const tanY = -Math.cos(entryRad);

  // Drop point: walk back from the entry along −tangent until the y-component
  // is at the target height above the loop bottom.
  const loopBottomY = cy + R;
  const dropY = loopBottomY - heightR * R;
  const rampLen = (entryY - dropY) / tanY; // tanY > 0 for CCW traversal
  const dropX = entryX - rampLen * tanX;

  const points = [];
  const rampSegs = 5;
  for (let i = 0; i <= rampSegs; i++) {
    const tt = i / rampSegs;
    points.push({
      x: dropX + tt * (entryX - dropX),
      y: dropY + tt * (entryY - dropY)
    });
  }
  for (let i = 1; i <= loopSegments; i++) {
    const angleDeg = entryAngleDeg - (i * loopArcDeg / loopSegments);
    const rad = angleDeg * Math.PI / 180;
    points.push({ x: cx + R * Math.cos(rad), y: cy + R * Math.sin(rad) });
  }
  // Exit ramp: continue along the *outgoing* tangent at the loop exit point so
  // the seam there is also smooth.
  const exitAngleDeg = entryAngleDeg - loopArcDeg;
  const exitRad = exitAngleDeg * Math.PI / 180;
  const exitX = cx + R * Math.cos(exitRad);
  const exitY = cy + R * Math.sin(exitRad);
  const exitTanX = Math.sin(exitRad);
  const exitTanY = -Math.cos(exitRad);
  const exitSegs = 4;
  for (let i = 1; i <= exitSegs; i++) {
    const tt = i / exitSegs;
    points.push({
      x: exitX + tt * exitLen * exitTanX,
      y: exitY + tt * exitLen * exitTanY
    });
  }

  return { points, dropPos: { x: dropX, y: dropY } };
};

// ── Loop-the-loop preset ──
// Spline-based simulator with realistic loss-of-contact: when the locally
// required centripetal force exceeds what gravity can supply, the ball
// detaches and follows projectile motion. The detach physics is generic —
// it uses only the spline's curvature primitive — so this same simulator
// would work on any track shape (parabolic well, brachistochrone, custom
// scribble) without modification.

window.createLoopSimulation = function createLoopSimulation(canvas, opts) {
  opts = opts || {};
  const ctx = canvas.getContext('2d');
  const gravity = opts.gravity || 600;
  const ballRadius = opts.ballRadius || 11;
  const trackColor = opts.trackColor || '#334155';
  const trackWidth = opts.trackWidth || 4;
  const ballColor = opts.ballColor || '#3b82f6';
  const onResult = opts.onResult || null;
  const trackBuilder = opts.trackBuilder || window.buildRampLoopTrack;
  const successLabel = opts.successLabel != null ? opts.successLabel : 'Loop completed!';
  // Detach safety factor: contact is lost only when v²·κ falls below
  // (g·n_y) · (1 − safety). The exact boundary case (e.g. h = 2.5 R) is a
  // measure-zero set; numerical noise plus the κ-from-Catmull-Rom under-
  // estimate would otherwise flip it randomly. A small margin (~1%) keeps
  // the boundary well-defined and reflects that any real-world track has
  // tiny dissipation, so "exactly h_min" still completes.
  const detachSafety = opts.detachSafety != null ? opts.detachSafety : 0.01;

  let mode = 'idle';   // 'idle' | 'simulate' | 'freefall' | 'success' | 'fail'
  let wasFreefall = false; // true if 'fail' state was reached via freefall
  let heightR = 1.5;
  let spline = null;
  let dropPos = null;
  // Detach threshold: anywhere with curvature below this fraction of the
  // spline's *peak* curvature is treated as "essentially straight" — i.e.
  // numerical noise from the Catmull-Rom seams. Anywhere above is a real
  // curved feature where loss-of-contact physics applies.
  let kappaDetachThreshold = 0;
  let ballS = 0;
  let ballV = 0;
  // Free-flight state (used after the ball loses contact with the rail)
  let ballX = 0, ballY = 0, ballVx = 0, ballVy = 0;
  let trail = [];
  let animId = null;
  let lastTime = 0;

  function buildTrack(h) {
    const built = trackBuilder({ heightR: h });
    spline = buildSpline(built.points, 8);
    dropPos = built.dropPos;
    // Scan for peak curvature once so the detach check has a sensible scale.
    let maxK = 0;
    const N = 200;
    for (let i = 0; i <= N; i++) {
      const c = spline.curvatureAt((i / N) * spline.totalLength);
      if (c.kappa > maxK) maxK = c.kappa;
    }
    kappaDetachThreshold = 0.3 * maxK;
  }

  function setHeight(h) {
    heightR = Math.max(0.5, Math.min(3.5, h));
    if (mode === 'simulate' || mode === 'freefall') return;
    mode = 'idle';
    buildTrack(heightR);
    ballS = 0; ballV = 0; ballX = 0; ballY = 0; ballVx = 0; ballVy = 0; trail = []; wasFreefall = false;
    render();
  }

  function start() {
    if (mode === 'simulate' || mode === 'freefall') return;
    mode = 'simulate';
    buildTrack(heightR);
    ballS = 0; ballV = 0; ballX = 0; ballY = 0; ballVx = 0; ballVy = 0; trail = []; wasFreefall = false; lastTime = 0;
    animId = requestAnimationFrame(step);
  }

  function reset() {
    if (animId) { cancelAnimationFrame(animId); animId = null; }
    mode = 'idle';
    buildTrack(heightR);
    ballS = 0; ballV = 0; ballX = 0; ballY = 0; ballVx = 0; ballVy = 0; trail = []; wasFreefall = false;
    render();
  }

  function step(timestamp) {
    const frameDt = lastTime ? Math.min((timestamp - lastTime) / 1000, 0.04) : 0.016;
    lastTime = timestamp;

    // Subdivide each animation frame into smaller fixed-size physics steps.
    // The marginal h ≈ 2.5R case requires sub-frame accuracy to track the
    // exactly-on-threshold conditions at the top of the loop.
    const SUB_DT = 0.004;
    const subSteps = Math.max(1, Math.ceil(frameDt / SUB_DT));
    const dt = frameDt / subSteps;

    for (let i = 0; i < subSteps; i++) {
      if (!stepOnce(dt)) break;
    }

    render();
    if (mode === 'simulate' || mode === 'freefall') {
      animId = requestAnimationFrame(step);
    }
  }

  // Returns false if the simulation finished (success/fail) or stopped.
  function stepOnce(dt) {
    if (mode === 'freefall') {
      ballVy += gravity * dt;
      ballX += ballVx * dt;
      ballY += ballVy * dt;
      trail.push({ x: ballX, y: ballY });
      if (trail.length > 250) trail.shift();
      if (ballY > canvas.height + 20 || ballX < -20 || ballX > canvas.width + 20) {
        wasFreefall = true;
        finish(false, '');
        return false;
      }
      return true;
    }

    if (mode !== 'simulate') return false;

    const theta = spline.slopeAngleAt(ballS);
    const a = gravity * Math.sin(theta);
    ballV += a * dt;
    ballS += ballV * dt;

    if (ballS < 0) { ballS = 0; ballV = 0; finish(false, ''); return false; }
    if (ballS > spline.totalLength) {
      ballS = spline.totalLength;
      finish(true, successLabel);
      return false;
    }

    // Loss-of-contact check, generic for any spline shape. The unit centripetal
    // direction n̂ at this point comes from the spline's curvature primitive.
    // Required centripetal force (per unit mass) is v²·κ in the +n̂ direction.
    // Gravity contributes g·n̂_y in that direction (canvas y is +down). When
    // n̂_y > 0 the ball is on a section that curves "ceiling-down" relative to
    // gravity, and if v²·κ falls below g·n̂_y the rail would have to pull
    // outward — which a one-sided rail can't, so contact is lost.
    const c = spline.curvatureAt(ballS);
    if (c.kappa > kappaDetachThreshold && c.ny > 0) {
      if (ballV * ballV * c.kappa < gravity * c.ny * (1 - detachSafety)) {
        const pos = spline.positionAt(ballS);
        const tan = spline.tangentAt(ballS);
        const tmag = Math.hypot(tan.x, tan.y) || 1;
        ballX = pos.x;
        ballY = pos.y;
        ballVx = ballV * tan.x / tmag;
        ballVy = ballV * tan.y / tmag;
        mode = 'freefall';
        return true;
      }
    }

    const pos = spline.positionAt(ballS);
    trail.push({ x: pos.x, y: pos.y });
    if (trail.length > 80) trail.shift();
    return true;
  }

  function finish(success, reason) {
    mode = success ? 'success' : 'fail';
    if (animId) { cancelAnimationFrame(animId); animId = null; }
    render();
    if (onResult) onResult({ success, reason, heightR });
  }

  function render() {
    const w = canvas.width, h = canvas.height;
    ctx.fillStyle = '#fafafa';
    ctx.fillRect(0, 0, w, h);

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

    // Drop indicator at start of track (start of spline)
    if (mode !== 'simulate' && mode !== 'freefall' && dropPos) {
      ctx.beginPath();
      ctx.arc(dropPos.x, dropPos.y, ballRadius + 3, 0, Math.PI * 2);
      ctx.fillStyle = '#fde68a';
      ctx.fill();
      ctx.strokeStyle = '#d97706';
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Trail
    for (let i = 0; i < trail.length; i++) {
      ctx.globalAlpha = ((i + 1) / trail.length) * 0.35;
      ctx.beginPath();
      ctx.arc(trail[i].x, trail[i].y, ballRadius * 0.55, 0, Math.PI * 2);
      ctx.fillStyle = ballColor;
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    // Ball — use freefall coords when in freefall or after a freefall-induced
    // fail. Skip the ball entirely once it has gone off the canvas (the trail
    // alone tells the story).
    if (mode === 'simulate' || mode === 'success' || mode === 'fail' || mode === 'freefall') {
      const useFree = mode === 'freefall' || (mode === 'fail' && wasFreefall);
      const pos = useFree ? { x: ballX, y: ballY } : spline.positionAt(ballS);
      const offCanvas = pos.x < -ballRadius || pos.x > canvas.width + ballRadius
                    || pos.y < -ballRadius || pos.y > canvas.height + ballRadius;
      if (!offCanvas) {
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, ballRadius, 0, Math.PI * 2);
        ctx.fillStyle = ballColor;
        ctx.fill();
        ctx.strokeStyle = '#1e3a8a';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }

    if (mode === 'success' && successLabel) {
      ctx.fillStyle = '#16a34a';
      ctx.fillRect(0, h - 36, w, 36);
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 16px system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(successLabel, w / 2, h - 13);
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
