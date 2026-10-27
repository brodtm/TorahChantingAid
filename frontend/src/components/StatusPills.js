import React from "react";

/**
 * Status pills showing real-time CV/OCR/locate state.
 * Pure-presentational; no state of its own.
 */
export default function StatusPills({ torahPresent, yad, ocrConfidence, ocrReady, located }) {
  return (
    <div className="flex flex-wrap gap-2">
      <span className={`status-pill ${torahPresent ? "ok" : "idle"}`} data-testid="status-torah">
        <span className="dot" /> Torah {torahPresent ? "detected" : "absent"}
      </span>
      <span className={`status-pill ${yad ? "ok" : "idle"}`} data-testid="status-yad">
        <span className="dot" /> Yad {yad ? `tracked ${(yad.score * 100).toFixed(0)}%` : "—"}
      </span>
      <span
        className={`status-pill ${ocrConfidence > 50 ? "ok" : ocrConfidence ? "warn" : "idle"}`}
        data-testid="status-ocr"
      >
        <span className="dot" /> OCR {ocrConfidence ? `${ocrConfidence.toFixed(0)}%` : (ocrReady ? "ready" : "loading")}
      </span>
      <span className={`status-pill ${located ? "ok" : "idle"}`} data-testid="status-location">
        <span className="dot" /> {located ? "Located" : "Searching"}
      </span>
    </div>
  );
}
