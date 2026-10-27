// 4-point projective (homography) transform helpers.
// Given 4 source points and 4 destination points, solve a 3x3 homography matrix H
// such that dest ≈ H * source (in homogeneous coordinates).
// We then expose `applyHomography(H, x, y)` and a CSS `matrix3d(...)` builder
// suitable for the calibrated overlay.

function solve(A, b) {
  // Solve A x = b using Gauss-Jordan elimination. A is n x n.
  const n = A.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let i = 0; i < n; i++) {
    // partial pivot
    let max = i;
    for (let k = i + 1; k < n; k++) {
      if (Math.abs(M[k][i]) > Math.abs(M[max][i])) max = k;
    }
    [M[i], M[max]] = [M[max], M[i]];
    const piv = M[i][i];
    if (Math.abs(piv) < 1e-12) return null;
    for (let j = i; j <= n; j++) M[i][j] /= piv;
    for (let k = 0; k < n; k++) {
      if (k === i) continue;
      const f = M[k][i];
      for (let j = i; j <= n; j++) M[k][j] -= f * M[i][j];
    }
  }
  return M.map(row => row[n]);
}

export function computeHomography(srcPts, dstPts) {
  // srcPts, dstPts: arrays of {x, y} with length 4 (TL, TR, BR, BL)
  const A = [];
  const b = [];
  for (let i = 0; i < 4; i++) {
    const { x: sx, y: sy } = srcPts[i];
    const { x: dx, y: dy } = dstPts[i];
    A.push([sx, sy, 1, 0, 0, 0, -sx * dx, -sy * dx]);
    b.push(dx);
    A.push([0, 0, 0, sx, sy, 1, -sx * dy, -sy * dy]);
    b.push(dy);
  }
  const h = solve(A, b);
  if (!h) return null;
  // 3x3 homography (h33 = 1)
  return [
    [h[0], h[1], h[2]],
    [h[3], h[4], h[5]],
    [h[6], h[7], 1],
  ];
}

export function applyHomography(H, x, y) {
  const X = H[0][0] * x + H[0][1] * y + H[0][2];
  const Y = H[1][0] * x + H[1][1] * y + H[1][2];
  const W = H[2][0] * x + H[2][1] * y + H[2][2];
  return { x: X / W, y: Y / W };
}

// Build CSS matrix3d() string from a 3x3 homography (used for projecting an
// HTML element flat onto the calibrated quad surface).
export function homographyToMatrix3d(H) {
  // 3x3 -> 4x4, column-major for matrix3d.
  // [ a b 0 c ]
  // [ d e 0 f ]
  // [ 0 0 1 0 ]
  // [ g h 0 1 ]
  const [a, b, c] = H[0];
  const [d, e, f] = H[1];
  const [g, h] = H[2];
  return `matrix3d(
    ${a}, ${d}, 0, ${g},
    ${b}, ${e}, 0, ${h},
    0, 0, 1, 0,
    ${c}, ${f}, 0, 1
  )`;
}
