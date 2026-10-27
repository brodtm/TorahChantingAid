// MediaPipe Hands wrapper — fully offline. Loads the bundled model from
// /mediapipe/hand_landmarker.task and the WASM from /mediapipe/wasm/.
//
// Landmark 8 (INDEX_FINGER_TIP) is treated as the yad tip — when the user
// holds the yad and points at the parchment, the index finger tip is the
// point closest to the active line. This gives much better accuracy than
// raw color-based detection in warm-on-warm lighting.
//
// API:
//   const det = await getHandLandmarker();   // singleton, lazy-init
//   const yad = det.detectFromVideo(videoEl, timestampMs);
//   // yad = { x, y, score } in normalized [0..1] OR null

import { FilesetResolver, HandLandmarker } from "@mediapipe/tasks-vision";

let _landmarker = null;
let _initPromise = null;

const INDEX_FINGER_TIP = 8;   // mediapipe hand landmark index

async function init() {
  // Self-host both wasm + model — no CDN, no internet.
  const vision = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
  _landmarker = await HandLandmarker.createFromOptions(vision, {
    baseOptions: {
      modelAssetPath: "/mediapipe/hand_landmarker.task",
      delegate: "GPU",
    },
    runningMode: "VIDEO",
    numHands: 1,
    minHandDetectionConfidence: 0.4,
    minHandPresenceConfidence: 0.4,
    minTrackingConfidence: 0.4,
  });
  return _landmarker;
}

export async function getHandLandmarker() {
  if (_landmarker) return _landmarker;
  if (!_initPromise) _initPromise = init();
  return _initPromise;
}

/**
 * Run the hand detector on a video frame.
 * @param {HTMLVideoElement} video
 * @param {number} timestampMs - monotonically increasing timestamp
 * @returns {{x:number, y:number, score:number, source:'mediapipe'} | null}
 */
export function detectYadFromVideo(video, timestampMs) {
  if (!_landmarker) return null;
  let result;
  try {
    result = _landmarker.detectForVideo(video, timestampMs);
  } catch (e) {
    console.warn("[mp-hand] detectForVideo error:", e);
    return null;
  }
  if (!result || !result.landmarks || result.landmarks.length === 0) return null;
  const hand = result.landmarks[0];
  const tip = hand[INDEX_FINGER_TIP];
  if (!tip) return null;
  // worldLandmarks gives 3D in meters; for our purposes the 2D normalized
  // tip coords are exactly what the projector pipeline needs.
  // Confidence is reported per-hand via result.handedness[0].score
  const score = result.handedness?.[0]?.[0]?.score ?? 0.5;
  return { x: tip.x, y: tip.y, score, source: "mediapipe" };
}

export function isHandLandmarkerReady() {
  return _landmarker != null;
}
