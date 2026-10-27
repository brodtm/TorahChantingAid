import React, { useEffect, useRef, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api";
import { projectorBus } from "../lib/projectorBus";
import {
  getCanvasFromVideo, diffFrames, detectAucoFiducials,
} from "../lib/cv";
import {
  ArrowLeft, Camera, Loader2, Check, X, RefreshCw, Projector, Eye,
} from "lucide-react";
import { FIDUCIAL_POSITIONS } from "./ProjectorPage";

// Phases of the auto-calibration sequence
const PHASE = {
  IDLE: "idle",
  ENSURING_PROJECTOR: "ensuring_projector",
  CAPTURING_BASELINE: "capturing_baseline",
  CAPTURING_PATTERN: "capturing_pattern",
  DETECTING: "detecting",
  STABILIZING: "stabilizing",
  SAVING: "saving",
  VERIFYING: "verifying",
  DONE: "done",
  FAILED: "failed",
};

const STABILITY_FRAMES = 3;
const STABILITY_TOL = 0.025; // ~2.5% of frame

export default function CalibrationPage() {
  const { id } = useParams();
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const overlayRef = useRef(null);
  const [phase, setPhase] = useState(PHASE.IDLE);
  const [message, setMessage] = useState("Ready to auto-calibrate.");
  const [error, setError] = useState("");
  const [detected, setDetected] = useState(null); // {TL, TR, BR, BL} normalized
  const [history, setHistory] = useState([]); // last detections for stability
  const [savedAt, setSavedAt] = useState(null);

  // ---- Camera lifecycle ----
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
      return true;
    } catch (e) {
      setError(`Camera unavailable: ${e?.message || e}`);
      return false;
    }
  }, []);

  const stopCamera = () => {
    if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop());
    streamRef.current = null;
  };

  useEffect(() => {
    startCamera();
    return () => {
      stopCamera();
      // Restore projector to session mode on unmount
      projectorBus.send({ type: "mode", mode: "session" });
    };
  }, [startCamera]);

  // ---- Helpers ----
  const captureFrame = async () => {
    const v = videoRef.current;
    if (!v || v.readyState < 2) return null;
    const { canvas, ctx, w, h } = getCanvasFromVideo(v, 0.5);
    return { imageData: ctx.getImageData(0, 0, w, h), w, h, canvas };
  };

  const setProjectorMode = (mode) => {
    projectorBus.send({ type: "mode", mode });
  };

  const wait = (ms) => new Promise(r => setTimeout(r, ms));

  // ---- Main auto-calibration sequence ----
  const runCalibration = async () => {
    setError("");
    setDetected(null);
    setHistory([]);
    setSavedAt(null);

    if (!streamRef.current) {
      const ok = await startCamera();
      if (!ok) return;
      await wait(800);
    }

    setPhase(PHASE.ENSURING_PROJECTOR);
    setMessage("Switching projector to baseline (black)…");
    setProjectorMode("calibration_off");
    await wait(900);

    setPhase(PHASE.CAPTURING_BASELINE);
    setMessage("Capturing ambient baseline frame…");
    const baseline = await captureFrame();
    if (!baseline) { setPhase(PHASE.FAILED); setMessage("Camera not ready."); return; }

    setProjectorMode("calibration_pattern");
    setMessage("Projecting calibration fiducials…");
    await wait(1000);

    let stable = [];
    for (let attempt = 0; attempt < 8; attempt++) {
      setPhase(PHASE.CAPTURING_PATTERN);
      setMessage(`Capturing pattern frame ${attempt + 1}…`);
      const pattern = await captureFrame();
      if (!pattern) { await wait(300); continue; }
      const diff = diffFrames(pattern.imageData, baseline.imageData);
      setPhase(PHASE.DETECTING);
      const det = detectAucoFiducials(diff, pattern.imageData, pattern.w, pattern.h);
      if (det) {
        setDetected(det);
        // stability check vs previous
        if (stable.length === 0) {
          stable.push(det);
          setMessage(`Detected fiducials (1/${STABILITY_FRAMES})…`);
        } else {
          const last = stable[stable.length - 1];
          const close = ["TL", "TR", "BR", "BL"].every(k => {
            return Math.hypot(det[k].x - last[k].x, det[k].y - last[k].y) < STABILITY_TOL;
          });
          if (close) {
            stable.push(det);
            setMessage(`Detected fiducials (${stable.length}/${STABILITY_FRAMES})…`);
          } else {
            stable = [det];
            setMessage(`Detection moved — restarting stability check.`);
          }
          setHistory([...stable]);
        }
        if (stable.length >= STABILITY_FRAMES) break;
      } else {
        setMessage(`Couldn't see all 4 fiducials — retrying (${attempt + 1}/8)…`);
      }
      await wait(450);
    }

    if (stable.length < STABILITY_FRAMES) {
      setPhase(PHASE.FAILED);
      setMessage("Auto-calibration failed. Make sure the projector is on, the camera can see all 4 corner markers, and there's no glare.");
      setProjectorMode("session");
      return;
    }

    // Average the stable detections for sub-pixel accuracy
    const avg = { TL: { x: 0, y: 0 }, TR: { x: 0, y: 0 }, BR: { x: 0, y: 0 }, BL: { x: 0, y: 0 } };
    for (const s of stable) {
      for (const k of ["TL", "TR", "BR", "BL"]) { avg[k].x += s[k].x; avg[k].y += s[k].y; }
    }
    for (const k of ["TL", "TR", "BR", "BL"]) {
      avg[k].x /= stable.length; avg[k].y /= stable.length;
    }
    setDetected(avg);

    // Save: points = projector coords, target = where they were detected in camera coords
    setPhase(PHASE.SAVING);
    setMessage("Saving calibration…");
    const points = ["TL", "TR", "BR", "BL"].map(k => ({
      x: FIDUCIAL_POSITIONS[k].x, y: FIDUCIAL_POSITIONS[k].y,
    }));
    const target = ["TL", "TR", "BR", "BL"].map(k => ({ x: avg[k].x, y: avg[k].y }));
    try {
      await api.saveCalibration({ session_id: id, points, target });
    } catch (e) {
      setPhase(PHASE.FAILED);
      setMessage(`Failed to save: ${e?.message || e}`);
      return;
    }

    // Verification step
    setPhase(PHASE.VERIFYING);
    setMessage("Verifying — projecting center crosshair…");
    setProjectorMode("calibration_verify");
    await wait(2200);
    setProjectorMode("session");

    setPhase(PHASE.DONE);
    setSavedAt(new Date().toLocaleTimeString());
    setMessage("Calibration saved successfully.");
  };

  const isRunning = ![PHASE.IDLE, PHASE.DONE, PHASE.FAILED].includes(phase);

  return (
    <div className="min-h-screen bg-black text-projgold flex flex-col" data-testid="calibration-page">
      <header className="px-4 py-3 flex items-center justify-between border-b border-projgold/30 bg-black z-20">
        <Link to={`/session/${id}`} className="inline-flex items-center gap-2 text-xs tracking-[0.25em] uppercase">
          <ArrowLeft size={14} /> Session
        </Link>
        <div className="text-xs tracking-[0.3em] uppercase">Auto-Calibration</div>
        <Link
          to={`/projector/${id}`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs tracking-[0.25em] uppercase opacity-80 hover:opacity-100"
          data-testid="open-projector-window"
        >
          <Projector size={14} /> Open projector
        </Link>
      </header>

      <div className="flex-1 grid lg:grid-cols-2 gap-0">
        {/* Camera preview + detection overlay */}
        <div className="relative bg-black border-r border-projgold/20 min-h-[300px]">
          <video
            ref={videoRef}
            className="absolute inset-0 w-full h-full object-cover"
            playsInline muted
            data-testid="calibration-video"
          />
          <svg
            ref={overlayRef}
            className="absolute inset-0 w-full h-full pointer-events-none"
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
          >
            {detected && Object.entries(detected).map(([k, p]) => (
              <g key={k}>
                <circle cx={p.x * 100} cy={p.y * 100} r="2" fill="none" stroke="#00FF88" strokeWidth="0.4" />
                <circle cx={p.x * 100} cy={p.y * 100} r="0.6" fill="#00FF88" />
                <text x={p.x * 100 + 3} y={p.y * 100 + 1.2} fill="#00FF88" fontSize="2.4" fontFamily="Inter">{k}</text>
              </g>
            ))}
            {detected && (
              <polygon
                points={["TL", "TR", "BR", "BL"].map(k => `${detected[k].x * 100},${detected[k].y * 100}`).join(" ")}
                fill="rgba(0, 255, 136, 0.06)"
                stroke="#00FF88"
                strokeWidth="0.25"
                strokeDasharray="1.5 1"
              />
            )}
          </svg>
          {!streamRef.current && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-projgold/70">
              <Camera size={28} className="mb-2" />
              <div className="text-xs tracking-[0.25em] uppercase">Awaiting camera permission</div>
            </div>
          )}
        </div>

        {/* Control panel */}
        <div className="p-8 flex flex-col gap-6">
          <div>
            <div className="text-xs tracking-[0.3em] uppercase opacity-70 mb-3">How it works</div>
            <ol className="text-sm space-y-2 text-projgold/80 list-decimal list-inside">
              <li>Make sure the projector is mounted, switched on, and showing the projector window.</li>
              <li>Position the phone so its camera can see the entire bimah surface.</li>
              <li>Press <span className="text-projgold font-semibold">Auto-calibrate</span> below.</li>
              <li>The projector flashes a baseline (black) then 4 unique dice fiducials. Stay still.</li>
              <li>The camera detects them, the homography is computed and saved automatically.</li>
            </ol>
          </div>

          <div className="bg-projgold/5 border border-projgold/30 px-5 py-4">
            <div className="text-xs tracking-[0.3em] uppercase opacity-70">Status</div>
            <div className="mt-1 text-sm flex items-center gap-2 min-h-[1.5rem]" data-testid="calibration-status">
              {isRunning && <Loader2 className="animate-spin" size={14} />}
              {phase === PHASE.DONE && <Check size={14} className="text-green-400" />}
              {phase === PHASE.FAILED && <X size={14} className="text-red-400" />}
              <span>{message}</span>
            </div>
            {savedAt && (
              <div className="text-[11px] tracking-[0.25em] uppercase opacity-60 mt-2">
                Saved at {savedAt}
              </div>
            )}
            {history.length > 0 && (
              <div className="text-[10px] opacity-60 mt-2 font-mono">
                Stability: {history.length} / {STABILITY_FRAMES} frames agree
              </div>
            )}
          </div>

          {error && (
            <div className="border border-red-500/40 bg-red-500/10 text-red-300 px-4 py-3 text-sm">
              {error}
            </div>
          )}

          <div className="flex flex-wrap gap-2 mt-auto">
            <button
              data-testid="run-auto-calibration"
              onClick={runCalibration}
              disabled={isRunning}
              className="inline-flex items-center gap-2 bg-projgold text-black px-5 py-3 hover:bg-yellow-400 disabled:opacity-50 text-sm font-semibold"
            >
              {isRunning ? <Loader2 className="animate-spin" size={16} /> : <RefreshCw size={16} />}
              {phase === PHASE.DONE ? "Recalibrate" : "Auto-calibrate"}
            </button>
            <button
              data-testid="show-pattern"
              onClick={() => setProjectorMode("calibration_pattern")}
              disabled={isRunning}
              className="inline-flex items-center gap-1 px-4 py-3 border border-projgold/40 hover:border-projgold text-xs disabled:opacity-50"
            >
              <Eye size={14} /> Show pattern
            </button>
            <button
              data-testid="show-session"
              onClick={() => setProjectorMode("session")}
              disabled={isRunning}
              className="inline-flex items-center gap-1 px-4 py-3 border border-projgold/40 hover:border-projgold text-xs disabled:opacity-50"
            >
              <Projector size={14} /> Back to session view
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
