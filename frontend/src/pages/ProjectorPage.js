import React, { useEffect, useState, useRef } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import { projectorBus } from "../lib/projectorBus";
import { computeHomography, homographyToMatrix3d } from "../lib/transform";

// Projector display modes:
//   "session"             - normal trope display synced from session
//   "calibration_off"     - pure black baseline
//   "calibration_pattern" - 4 ArUco-style dice fiducials at known corners
//   "calibration_verify"  - center crosshair to confirm calibration
//
// Mode is broadcast from the calibration page via projectorBus.

// Fiducial corner positions (normalized projector coords).
// Inset 9% from each edge so the markers are clearly inside the frame.
export const FIDUCIAL_POSITIONS = {
  TL: { x: 0.09, y: 0.09, pips: 1 },
  TR: { x: 0.91, y: 0.09, pips: 2 },
  BR: { x: 0.91, y: 0.91, pips: 3 },
  BL: { x: 0.09, y: 0.91, pips: 4 },
};

// Marker size as fraction of min(viewport w, h).
const MARKER_SIZE = 0.11;

function PipPattern({ count, size }) {
  // dice-style pip layout
  const positions = {
    1: [[0.5, 0.5]],
    2: [[0.3, 0.3], [0.7, 0.7]],
    3: [[0.3, 0.3], [0.5, 0.5], [0.7, 0.7]],
    4: [[0.3, 0.3], [0.7, 0.3], [0.3, 0.7], [0.7, 0.7]],
  }[count] || [];
  const r = size * 0.085;
  return (
    <>
      {positions.map(([px, py]) => (
        <circle
          key={`pip-${px}-${py}`}
          cx={px * size}
          cy={py * size}
          r={r}
          fill="#000000"
        />
      ))}
    </>
  );
}

function Fiducial({ corner, vw, vh }) {
  const f = FIDUCIAL_POSITIONS[corner];
  const size = Math.min(vw, vh) * MARKER_SIZE;
  const cx = f.x * vw;
  const cy = f.y * vh;
  return (
    <svg
      width={size}
      height={size}
      style={{
        position: "absolute",
        left: cx - size / 2,
        top: cy - size / 2,
      }}
    >
      <rect x="0" y="0" width={size} height={size} fill="#FFFFFF" />
      <PipPattern count={f.pips} size={size} />
    </svg>
  );
}

export default function ProjectorPage() {
  const { id } = useParams();
  const [state, setState] = useState(() => projectorBus.getCachedState() || {});
  const [mode, setMode] = useState("session");
  const [calib, setCalib] = useState(null);
  const containerRef = useRef(null);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });

  useEffect(() => {
    const onResize = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    return projectorBus.subscribe((msg) => {
      if (msg?.type === "state") setState(msg.payload || {});
      else if (msg?.type === "mode") setMode(msg.mode || "session");
    });
  }, []);

  useEffect(() => {
    if (!id) return;
    api.getCalibration(id).then(setCalib).catch(() => setCalib(null));
  }, [id]);

  // ---- CALIBRATION MODES (no homography applied) ----
  if (mode === "calibration_off") {
    return <div className="fixed inset-0 bg-black" data-testid="projector-calibration-off" />;
  }
  if (mode === "calibration_pattern") {
    return (
      <div className="fixed inset-0 bg-black overflow-hidden" data-testid="projector-calibration-pattern">
        <Fiducial corner="TL" vw={size.w} vh={size.h} />
        <Fiducial corner="TR" vw={size.w} vh={size.h} />
        <Fiducial corner="BR" vw={size.w} vh={size.h} />
        <Fiducial corner="BL" vw={size.w} vh={size.h} />
      </div>
    );
  }
  if (mode === "calibration_verify") {
    return (
      <div className="fixed inset-0 bg-black flex items-center justify-center" data-testid="projector-calibration-verify">
        <svg width="120" height="120" viewBox="0 0 120 120">
          <circle cx="60" cy="60" r="58" fill="none" stroke="#FFFFFF" strokeWidth="2" />
          <line x1="60" y1="0" x2="60" y2="120" stroke="#FFFFFF" strokeWidth="1.5" />
          <line x1="0" y1="60" x2="120" y2="60" stroke="#FFFFFF" strokeWidth="1.5" />
          <circle cx="60" cy="60" r="4" fill="#FFD700" />
        </svg>
      </div>
    );
  }

  // ---- SESSION MODE ----
  let matrix3d = null;
  if (calib?.points?.length === 4 && calib?.target?.length === 4) {
    const src = calib.points.map(p => ({ x: p.x * size.w, y: p.y * size.h }));
    const dst = calib.target.map(p => ({ x: p.x * size.w, y: p.y * size.h }));
    const H = computeHomography(src, dst);
    if (H) matrix3d = homographyToMatrix3d(H);
  }

  // Two display branches: scroll/column-map or classic verse-locate.
  const scrollMode = state?.scrollMode;
  const lines = state?.lines;
  const loc = state?.location;
  const column = state?.column;
  const columnLocked = state?.columnLocked;
  const columnConfidence = state?.columnConfidence ?? 0;
  const lineInfo = state?.lineInfo;
  const scrollVerses = state?.scrollVerses || [];
  const columnUnknown = scrollMode && (!column || !columnLocked || columnConfidence < 0.4);

  return (
    <div className="fixed inset-0 bg-black overflow-hidden" data-testid="projector-page">
      <div
        ref={containerRef}
        className="absolute inset-0"
        style={matrix3d ? { transform: matrix3d, transformOrigin: "0 0" } : undefined}
      >
        {scrollMode ? (
          <ScrollProjection
            column={column}
            columnLocked={columnLocked}
            columnConfidence={columnConfidence}
            columnUnknown={columnUnknown}
            lineInfo={lineInfo}
            scrollVerses={scrollVerses}
          />
        ) : (
          <ClassicProjection loc={loc} lines={lines} />
        )}

        <div className="absolute bottom-0 left-0 right-0 px-12 py-6 flex items-center justify-between text-projgold/60 text-[10px] tracking-[0.3em] uppercase">
          <span>{state?.torahPresent ? "Torah · detected" : "Torah · absent"}</span>
          <span>{state?.yad ? `Yad · ${(state.yad.score * 100).toFixed(0)}%` : "Yad · —"}</span>
          <span>{state?.ocrConfidence ? `OCR · ${state.ocrConfidence.toFixed(0)}%` : "OCR · —"}</span>
        </div>
      </div>
    </div>
  );
}

function ClassicProjection({ loc, lines }) {
  return (
    <>
      <div className="absolute top-0 left-0 right-0 px-12 py-8 flex items-baseline justify-between text-projgold">
        <div>
          <div className="text-[10px] tracking-[0.4em] uppercase opacity-70">Now Reading</div>
          {loc ? (
            <div className="font-display text-3xl mt-1">{loc.book} {loc.chapter}:{loc.verse}</div>
          ) : (
            <div className="text-projgold/40 text-sm mt-1">Awaiting yad…</div>
          )}
          {loc?.haftarah_for && (
            <div className="text-[10px] tracking-[0.4em] uppercase opacity-70 mt-1">
              Haftarah · {loc.haftarah_for}
            </div>
          )}
        </div>
        <div className="text-right">
          {loc?.parsha && <div className="projector-text text-3xl" dir="rtl">{loc.parsha}</div>}
          {!loc?.parsha && loc?.book_he && (
            <div className="projector-text text-3xl" dir="rtl">{loc.book_he}</div>
          )}
          {loc?.aliyah && (
            <div className="text-[10px] tracking-[0.4em] uppercase opacity-70 mt-1">Aliyah {loc.aliyah}</div>
          )}
        </div>
      </div>

      <div className="absolute inset-0 flex flex-col items-end justify-center px-12 gap-8" dir="rtl">
        {lines?.previous?.slice(-1).map((p) => (
          <div key={`pp-${p.book}-${p.chapter}-${p.verse}`} className="projector-text context text-3xl">
            {p.he_with_teamim}
          </div>
        ))}
        {lines?.active ? (
          <div
            className="projector-text font-bold leading-relaxed text-right"
            style={{ fontSize: "min(8vw, 6rem)" }}
            data-testid="projector-active-line"
          >
            {lines.active.he_with_teamim}
          </div>
        ) : (
          <div className="projector-text context text-2xl text-center w-full">Waiting for location lock…</div>
        )}
        {lines?.next?.slice(0, 1).map((n) => (
          <div key={`nn-${n.book}-${n.chapter}-${n.verse}`} className="projector-text context text-3xl">
            {n.he_with_teamim}
          </div>
        ))}
      </div>
    </>
  );
}

function ScrollProjection({
  column, columnLocked, columnConfidence, columnUnknown,
  lineInfo, scrollVerses,
}) {
  const dimmed = columnUnknown ? "opacity-25" : "opacity-100";
  return (
    <>
      <div className={`absolute top-0 left-0 right-0 px-12 py-8 flex items-baseline justify-between text-projgold transition-opacity duration-500 ${dimmed}`}>
        <div>
          <div className="text-[10px] tracking-[0.4em] uppercase opacity-70">Scroll</div>
          {column ? (
            <div className="font-display text-3xl mt-1">
              Column {column}
              {lineInfo && <span className="text-projgold/60"> · L{lineInfo.line}/{lineInfo.lines_in_column}</span>}
            </div>
          ) : (
            <div className="text-projgold/40 text-sm mt-1">Awaiting column lock…</div>
          )}
          <div className="text-[10px] tracking-[0.4em] uppercase opacity-70 mt-1">
            {columnLocked ? "Locked" : "Searching"} · {Math.round(columnConfidence * 100)}%
          </div>
        </div>
        <div className="text-right">
          {scrollVerses[0] && (
            <div className="text-[10px] tracking-[0.4em] uppercase opacity-70">
              {scrollVerses[0].book} {scrollVerses[0].chapter}:{scrollVerses[0].verse}
            </div>
          )}
        </div>
      </div>

      <div className={`absolute inset-0 flex flex-col items-end justify-center px-12 gap-6 transition-opacity duration-500 ${dimmed}`} dir="rtl">
        {scrollVerses.length > 0 ? (
          scrollVerses.map((v) => (
            <div
              key={`sv-${v.book}-${v.chapter}-${v.verse}`}
              className="projector-text font-bold leading-relaxed text-right"
              style={{ fontSize: "min(7.5vw, 5.5rem)" }}
              data-testid="projector-scroll-line"
            >
              {v.he_with_teamim}
            </div>
          ))
        ) : (
          <div className="projector-text context text-2xl text-center w-full">
            Yad position not yet detected.
          </div>
        )}
      </div>

      {columnUnknown && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center text-projgold max-w-md px-8 py-6 border border-projgold/40 bg-black/60 backdrop-blur-sm">
            <div className="text-xs tracking-[0.4em] uppercase opacity-80 mb-2">Column unknown</div>
            <div className="text-2xl font-display mb-1">Point yad at any word</div>
            <div className="text-xs tracking-[0.2em] opacity-70">…and hold for 2 seconds to relock.</div>
          </div>
        </div>
      )}
    </>
  );
}
