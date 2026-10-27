import { useEffect, useRef, useState, useCallback } from "react";
import { getCanvasFromVideo, estimateBrightness, detectYadTip, cropStrip } from "./cv";
import { ocrCanvas, getOcrWorker } from "./ocr";
import { getHandLandmarker, detectYadFromVideo, isHandLandmarkerReady } from "./handLandmarker";
import { api } from "./api";

/**
 * Camera + CV pipeline as a reusable hook.
 *  - Manages the MediaStream lifecycle.
 *  - Runs a requestAnimationFrame loop that detects torah presence + yad tip.
 *  - Periodically runs Tesseract Hebrew OCR on the strip near the yad.
 *  - When OCR yields enough text, calls /api/torah/locate and surfaces results.
 *
 * Returns granular state + control handles. Single-purpose, easy to test.
 */
export function useCameraCV({ autoLocate, hintBook, hintChapter, hintCategory } = {}) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const loopRef = useRef(null);
  const lastOcrAt = useRef(0);

  const [cameraOn, setCameraOn] = useState(false);
  const [error, setError] = useState("");
  const [torahPresent, setTorahPresent] = useState(false);
  const [yad, setYad] = useState(null);
  // Manual yad override: ref so the rAF loop reads fresh values without
  // re-binding. Set by user tap on the camera preview; takes precedence
  // over auto-detection for `holdMs` ms (default 30s).
  const yadManualRef = useRef(null);
  const yadManualUntilRef = useRef(0);
  const setYadManual = useCallback((pos, holdMs = 30000) => {
    if (!pos) {
      yadManualRef.current = null;
      yadManualUntilRef.current = 0;
      return;
    }
    yadManualRef.current = { x: pos.x, y: pos.y, score: 1, manual: true };
    yadManualUntilRef.current = Date.now() + holdMs;
  }, []);
  const [ocrText, setOcrText] = useState("");
  const [ocrConfidence, setOcrConfidence] = useState(0);
  const [ocrReady, setOcrReady] = useState(false);
  const [location, setLocation] = useState(null);
  const [lines, setLines] = useState(null);

  // Warm Tesseract worker up-front so first OCR is fast.
  useEffect(() => {
    let cancelled = false;
    getOcrWorker()
      .then(() => { if (!cancelled) setOcrReady(true); })
      .catch((e) => console.warn("[useCameraCV] OCR init failed:", e));
    return () => { cancelled = true; };
  }, []);

  // Warm the MediaPipe Hand Landmarker. The model + WASM are bundled at
  // /mediapipe/ for full offline operation. Loading is ~1-2s on first
  // visit so we do it eagerly; subsequent reloads use the SW cache.
  const [handReady, setHandReady] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getHandLandmarker()
      .then(() => { if (!cancelled) setHandReady(true); })
      .catch((e) => console.warn("[useCameraCV] HandLandmarker init failed:", e));
    return () => { cancelled = true; };
  }, []);
  // expose handReady through return; consumer is not required to surface it
  void handReady;

  const startCamera = useCallback(async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraOn(true);
    } catch (e) {
      setError(`Camera unavailable: ${e?.message || e}. You can still use manual selection below.`);
    }
  }, []);

  const stopCamera = useCallback(() => {
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCameraOn(false);
  }, []);

  // Hold latest hint values in refs so the rAF loop never sees stale values
  // without forcing the loop to re-subscribe on every keystroke.
  const hintsRef = useRef({ autoLocate, hintBook, hintChapter, hintCategory });
  useEffect(() => {
    hintsRef.current = { autoLocate, hintBook, hintChapter, hintCategory };
  }, [autoLocate, hintBook, hintChapter, hintCategory]);

  useEffect(() => {
    if (!cameraOn) return undefined;
    let cancelled = false;

    const runOcrAndLocate = async (canvas, tipY) => {
      try {
        const strip = cropStrip(canvas, tipY, 0.18);
        const { text, confidence } = await ocrCanvas(strip);
        if (cancelled) return;
        setOcrText(text);
        setOcrConfidence(confidence);
        if (!text || text.replace(/\s/g, "").length < 6) return;
        const { hintBook: hb, hintChapter: hc, hintCategory: hcat } = hintsRef.current;
        const loc = await api.locate(
          text,
          hb || undefined,
          hc ? Number(hc) : undefined,
          hcat || undefined,
        );
        if (cancelled || !loc) return;
        setLocation(loc);
        const ls = await api.getLines(loc.book, loc.chapter, loc.verse, 2);
        if (!cancelled) setLines(ls);
      } catch (e) {
        console.warn("[useCameraCV] OCR/locate error:", e);
      }
    };

    const tick = () => {
      if (cancelled) return;
      const v = videoRef.current;
      if (!v || v.readyState < 2) {
        loopRef.current = requestAnimationFrame(tick);
        return;
      }
      try {
        const { canvas, ctx, w, h } = getCanvasFromVideo(v, 0.4);
        const img = ctx.getImageData(0, 0, w, h);
        const brightness = estimateBrightness(img);
        const present = brightness > 50 && brightness < 230;
        setTorahPresent(present);

        // Yad detection priority: manual tap > MediaPipe Hands index-finger
        // tip > canvas-based warm-dark blob. The MediaPipe model gives
        // sub-pixel tip accuracy on warm-on-warm scenes where the colour
        // mask fails.
        let mpTip = null;
        if (present && isHandLandmarkerReady()) {
          mpTip = detectYadFromVideo(v, performance.now());
        }
        const autoTip = mpTip || (present ? detectYadTip(img, w, h) : null);
        // Manual override takes precedence while inside the hold window.
        const now = Date.now();
        if (yadManualRef.current && now > yadManualUntilRef.current) {
          yadManualRef.current = null;
        }
        const tip = yadManualRef.current || autoTip;
        setYad(tip);

        const { autoLocate: al } = hintsRef.current;
        if (
          present && tip && tip.score > 0.05 && ocrReady && al &&
          now - lastOcrAt.current > 2500
        ) {
          lastOcrAt.current = now;
          runOcrAndLocate(canvas, tip.y);
        }
      } catch (e) {
        console.warn("[useCameraCV] frame error:", e);
      }
      loopRef.current = requestAnimationFrame(tick);
    };

    loopRef.current = requestAnimationFrame(tick);
    return () => {
      cancelled = true;
      if (loopRef.current) cancelAnimationFrame(loopRef.current);
    };
  }, [cameraOn, ocrReady]);

  // Cleanup on unmount
  useEffect(() => stopCamera, [stopCamera]);

  return {
    videoRef,
    cameraOn, startCamera, stopCamera,
    error, setError,
    torahPresent, yad, ocrText, ocrConfidence, ocrReady, handReady,
    location, setLocation,
    lines, setLines,
    setYadManual,
  };
}
