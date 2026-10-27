// Computer-vision helpers (canvas-only, no ML libs).

export function getCanvasFromVideo(video, scale = 0.4) {
  const w = Math.max(1, Math.floor(video.videoWidth * scale));
  const h = Math.max(1, Math.floor(video.videoHeight * scale));
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(video, 0, 0, w, h);
  return { canvas: c, ctx, w, h };
}

export function estimateBrightness(imageData) {
  const d = imageData.data;
  let sum = 0;
  for (let i = 0; i < d.length; i += 64) sum += (d[i] + d[i + 1] + d[i + 2]) / 3;
  return sum / (d.length / 64);
}

// ---------------------------------------------------------------------------
// Yad-tip detection
// ---------------------------------------------------------------------------
//
// The yad (pointer stick) and the hand holding it form a single connected
// "non-parchment" mass that enters the frame from one edge and extends
// inward across the parchment. The TIP is the endpoint farthest from any
// frame edge.
//
// Pipeline:
//   1. Build a mask of "warm-dark" pixels (R>G>B, R-G >= 18, V < 195).
//      Parchment is too bright; pure Hebrew text is achromatic (R≈G≈B);
//      both are excluded. Hand + yad-shadow + yad-reflective surface all
//      qualify.
//   2. 1-step dilation to bridge gaps in the yad shaft.
//   3. Connected-components flood fill.
//   4. Keep blobs that touch a frame edge but DO NOT span > 85% of either
//      dimension (rejects scroll rollers spanning top→bottom).
//   5. PCA on the best candidate → principal axis.
//   6. Project blob extrema onto the axis. Tip = endpoint with the LARGER
//      distance to the nearest frame edge (handle/grip exits the frame).
//
// Returns { x, y, score } in [0..1] normalized coords, or null. `x` and
// `y` always refer to the TIP, not the centroid.
export function detectYadTip(imageData, w, h) {
  const d = imageData.data;
  const npx = w * h;

  // --- mask ---------------------------------------------------------------
  const mask = new Uint8Array(npx);
  let count = 0;
  for (let y = 0; y < h; y++) {
    const row = y * w;
    for (let x = 0; x < w; x++) {
      const i = (row + x) * 4;
      const r = d[i], g = d[i + 1], b = d[i + 2];
      const v = r > g ? (r > b ? r : b) : (g > b ? g : b);
      if (v >= 195) continue;             // parchment / bright bg
      if (r <= g || g <= b) continue;     // not warm
      if (r - g < 18 || r - b < 30) continue; // weak warmth (= text or grey)
      mask[row + x] = 1;
      count++;
    }
  }
  if (count < 200) return null;

  // --- 1-step dilation (4-neighborhood) -----------------------------------
  const dil = new Uint8Array(mask);
  for (let y = 1; y < h - 1; y++) {
    const row = y * w;
    for (let x = 1; x < w - 1; x++) {
      const i = row + x;
      if (mask[i]) continue;
      if (mask[i - 1] || mask[i + 1] || mask[i - w] || mask[i + w]) dil[i] = 1;
    }
  }

  // --- flood-fill connected components ------------------------------------
  const visited = new Uint8Array(npx);
  const stack = new Int32Array(npx);
  const minSize = Math.max(300, Math.floor(npx * 0.005));
  // Keep blob bookkeeping in flat arrays to avoid allocator churn.
  const blobs = [];
  for (let p = 0; p < npx; p++) {
    if (!dil[p] || visited[p]) continue;
    let sp = 0;
    stack[sp++] = p;
    visited[p] = 1;
    let sumX = 0, sumY = 0, cnt = 0;
    let minX = w, maxX = 0, minY = h, maxY = 0;
    // Collect blob points as flat int pairs for later PCA.
    const pts = [];
    while (sp > 0) {
      const cur = stack[--sp];
      const cy = (cur / w) | 0;
      const cx = cur - cy * w;
      sumX += cx; sumY += cy; cnt++;
      pts.push(cx, cy);
      if (cx < minX) minX = cx;
      if (cx > maxX) maxX = cx;
      if (cy < minY) minY = cy;
      if (cy > maxY) maxY = cy;
      if (cx > 0) { const ni = cur - 1; if (dil[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
      if (cx < w - 1) { const ni = cur + 1; if (dil[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
      if (cy > 0) { const ni = cur - w; if (dil[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
      if (cy < h - 1) { const ni = cur + w; if (dil[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
    }
    if (cnt < minSize) continue;
    if (cnt > npx * 0.30) continue;          // background runaway
    const bw = maxX - minX, bh = maxY - minY;
    if (bw > w * 0.85 || bh > h * 0.85) continue; // scroll roller
    const touchesEdge =
      minX <= w * 0.05 || maxX >= w * 0.95 ||
      minY <= h * 0.05 || maxY >= h * 0.95;
    if (!touchesEdge) continue;
    blobs.push({ cx: sumX / cnt, cy: sumY / cnt, cnt, pts, minX, minY, maxX, maxY });
  }
  if (!blobs.length) return null;

  // --- per-blob PCA + tip extraction --------------------------------------
  let best = null;
  for (const b of blobs) {
    const cx = b.cx, cy = b.cy;
    let mxx = 0, myy = 0, mxy = 0;
    const pts = b.pts;
    for (let k = 0; k < pts.length; k += 2) {
      const dx = pts[k] - cx, dy = pts[k + 1] - cy;
      mxx += dx * dx; myy += dy * dy; mxy += dx * dy;
    }
    const trace = mxx + myy;
    const det = mxx * myy - mxy * mxy;
    const disc = Math.sqrt(Math.max(0, trace * trace / 4 - det));
    const lam = trace / 2 + disc;
    let ax, ay;
    if (Math.abs(mxy) > 1e-3) { ax = lam - myy; ay = mxy; }
    else if (mxx >= myy) { ax = 1; ay = 0; }
    else { ax = 0; ay = 1; }
    const norm = Math.hypot(ax, ay) || 1;
    ax /= norm; ay /= norm;

    let tMin = Infinity, tMax = -Infinity;
    let pMinX = 0, pMinY = 0, pMaxX = 0, pMaxY = 0;
    for (let k = 0; k < pts.length; k += 2) {
      const px = pts[k], py = pts[k + 1];
      const t = (px - cx) * ax + (py - cy) * ay;
      if (t < tMin) { tMin = t; pMinX = px; pMinY = py; }
      if (t > tMax) { tMax = t; pMaxX = px; pMaxY = py; }
    }
    const axisLen = tMax - tMin;
    const eLo = Math.min(pMinX, w - pMinX, pMinY, h - pMinY);
    const eHi = Math.min(pMaxX, w - pMaxX, pMaxY, h - pMaxY);
    const farEdgeDist = Math.max(eLo, eHi);
    // Reject scroll-roller-like blobs whose BOTH endpoints touch a frame edge.
    if (farEdgeDist < 0.10 * Math.min(w, h)) continue;

    const bw2 = b.maxX - b.minX, bh2 = b.maxY - b.minY;
    const elong = Math.max(bw2, bh2) / Math.max(1, Math.min(bw2, bh2));
    const score = farEdgeDist * elong * Math.log(b.cnt + 1);
    if (!best || score > best.score) {
      const [tipX, tipY] = (eLo > eHi) ? [pMinX, pMinY] : [pMaxX, pMaxY];
      const confidence =
        Math.min(1, axisLen / (0.3 * Math.max(w, h))) *
        Math.min(1, elong / 3);
      best = { score, tipX, tipY, axisLen, elong, count: b.cnt, confidence };
    }
  }
  if (!best) return null;
  return {
    x: best.tipX / w,
    y: best.tipY / h,
    score: best.confidence,
    elongation: best.elong,
    pixels: best.count,
  };
}

export function cropStrip(canvas, yNorm, heightNorm = 0.16) {
  const w = canvas.width, h = canvas.height;
  const y = Math.max(0, Math.min(h - 1, Math.floor(yNorm * h - heightNorm * h * 0.6)));
  const sh = Math.min(h - y, Math.floor(heightNorm * h));
  const out = document.createElement("canvas");
  out.width = w; out.height = sh;
  out.getContext("2d").drawImage(canvas, 0, y, w, sh, 0, 0, w, sh);
  return out;
}

// ---------------------------------------------------------------------------
// Calibration: image subtraction + bright-square + dice-pattern corner ID
// ---------------------------------------------------------------------------

// Compute pixel-wise positive difference (pattern - baseline) and write to
// `out` ImageData. Returns the same ImageData for chaining.
export function diffFrames(patternImg, baselineImg) {
  const a = patternImg.data, b = baselineImg.data;
  const out = new ImageData(patternImg.width, patternImg.height);
  const o = out.data;
  for (let i = 0; i < a.length; i += 4) {
    const da = (a[i] + a[i + 1] + a[i + 2]) / 3;
    const db = (b[i] + b[i + 1] + b[i + 2]) / 3;
    const v = Math.max(0, da - db);
    const c = Math.min(255, v * 1.4); // slight gain
    o[i] = o[i + 1] = o[i + 2] = c;
    o[i + 3] = 255;
  }
  return out;
}

// Generic flood-fill blob extraction over a binary mask.
function extractBlobs(mask, w, h, minSize, maxFrac = 0.06) {
  const visited = new Uint8Array(w * h);
  const blobs = [];
  const stack = new Int32Array(w * h);
  const maxSize = w * h * maxFrac;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = y * w + x;
      if (!mask[idx] || visited[idx]) continue;
      let sp = 0;
      stack[sp++] = idx;
      visited[idx] = 1;
      let sumX = 0, sumY = 0, count = 0;
      let minX = x, maxX = x, minY = y, maxY = y;
      while (sp > 0) {
        const cur = stack[--sp];
        const cy = (cur / w) | 0;
        const cx = cur - cy * w;
        sumX += cx; sumY += cy; count++;
        if (cx < minX) minX = cx; if (cx > maxX) maxX = cx;
        if (cy < minY) minY = cy; if (cy > maxY) maxY = cy;
        if (cx > 0) { const ni = cur - 1; if (mask[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
        if (cx < w - 1) { const ni = cur + 1; if (mask[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
        if (cy > 0) { const ni = cur - w; if (mask[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
        if (cy < h - 1) { const ni = cur + w; if (mask[ni] && !visited[ni]) { visited[ni] = 1; stack[sp++] = ni; } }
      }
      if (count >= minSize && count <= maxSize) {
        blobs.push({
          x: sumX / count, y: sumY / count, count,
          bbox: { minX, minY, maxX, maxY },
        });
      }
    }
  }
  return blobs;
}

// Identify how many internal dark "pips" exist inside a bright blob.
// We look at the original (non-diff) pattern frame inside the blob bbox,
// build a "dark inside bright square" mask, and count connected components.
function countPips(patternImg, w, h, blob) {
  const { minX, minY, maxX, maxY } = blob.bbox;
  const bw = maxX - minX + 1;
  const bh = maxY - minY + 1;
  if (bw < 8 || bh < 8) return 0;
  const d = patternImg.data;
  // local luminance min/max within bbox
  let lmin = 255, lmax = 0;
  for (let y = minY; y <= maxY; y++) {
    for (let x = minX; x <= maxX; x++) {
      const i = (y * w + x) * 4;
      const lum = (d[i] + d[i + 1] + d[i + 2]) / 3;
      if (lum < lmin) lmin = lum;
      if (lum > lmax) lmax = lum;
    }
  }
  const range = lmax - lmin;
  if (range < 30) return 0;
  const darkThr = lmin + range * 0.35; // pips are clearly darker than the white square

  // mask of dark pixels inside bbox (interior only — shrink 15%)
  const sx = Math.floor(minX + bw * 0.15);
  const ex = Math.ceil(maxX - bw * 0.15);
  const sy = Math.floor(minY + bh * 0.15);
  const ey = Math.ceil(maxY - bh * 0.15);
  const lw = ex - sx + 1;
  const lh = ey - sy + 1;
  if (lw < 4 || lh < 4) return 0;
  const localMask = new Uint8Array(lw * lh);
  for (let y = sy; y <= ey; y++) {
    for (let x = sx; x <= ex; x++) {
      const i = (y * w + x) * 4;
      const lum = (d[i] + d[i + 1] + d[i + 2]) / 3;
      if (lum < darkThr) localMask[(y - sy) * lw + (x - sx)] = 1;
    }
  }
  const minPip = Math.max(4, Math.floor(blob.count * 0.005));
  const pips = extractBlobs(localMask, lw, lh, minPip, 0.4);
  return Math.min(4, pips.length);
}

// Detect the 4 ArUco-like fiducials in a diff'd image, identify corner ID
// from internal pip count using the original pattern image, return mapping.
// Returns object: { TL: {x, y}, TR: {...}, BR: {...}, BL: {...} } in [0..1]
// camera coords, or null on failure.
export function detectAucoFiducials(diffImg, patternImg, w, h) {
  const data = diffImg.data;
  // adaptive bright threshold on diff
  const hist = new Uint32Array(256);
  let sampled = 0;
  for (let i = 0; i < data.length; i += 16) {
    hist[data[i]]++;
    sampled++;
  }
  const targetCount = Math.max(120, Math.floor(sampled * 0.02));
  let cum = 0, thr = 80;
  for (let v = 255; v >= 40; v--) {
    cum += hist[v];
    if (cum >= targetCount) { thr = v; break; }
  }
  thr = Math.max(thr, 50);

  const mask = new Uint8Array(w * h);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    if (data[i] >= thr) mask[p] = 1;
  }

  const minBlob = Math.max(40, Math.floor(w * h * 0.0008));
  const blobs = extractBlobs(mask, w, h, minBlob, 0.06);
  if (blobs.length < 4) return null;
  // Take 6 largest then count pips
  const candidates = blobs.sort((a, b) => b.count - a.count).slice(0, 8);
  const tagged = candidates.map(b => ({ ...b, pips: countPips(patternImg, w, h, b) }));

  const byPip = { 1: null, 2: null, 3: null, 4: null };
  for (const t of tagged) {
    if (t.pips >= 1 && t.pips <= 4 && (!byPip[t.pips] || t.count > byPip[t.pips].count)) {
      byPip[t.pips] = t;
    }
  }
  if (!byPip[1] || !byPip[2] || !byPip[3] || !byPip[4]) return null;

  // Mapping: TL=1, TR=2, BR=3, BL=4
  const norm = (b) => ({ x: b.x / w, y: b.y / h });
  return {
    TL: norm(byPip[1]),
    TR: norm(byPip[2]),
    BR: norm(byPip[3]),
    BL: norm(byPip[4]),
  };
}
