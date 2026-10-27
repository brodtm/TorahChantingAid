import React, { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Camera, CameraOff, Loader2, Crosshair, Target,
  Sliders, Projector, AlertTriangle, Layers,
} from "lucide-react";
import { api } from "../lib/api";
import { projectorBus } from "../lib/projectorBus";
import { useCameraCV } from "../lib/useCameraCV";
import { useColumnMap } from "../lib/useColumnMap";
import StatusPills from "../components/StatusPills";
import ActiveLinesPanel from "../components/ActiveLinesPanel";

export default function SessionPage() {
  const { id } = useParams();
  const [books, setBooks] = useState({ torah: [], neviim: [], megillot: [] });
  const [hintCategory, setHintCategory] = useState("");
  const [hintBook, setHintBook] = useState("");
  const [hintChapter, setHintChapter] = useState("");
  const [autoLocate, setAutoLocate] = useState(true);
  const [busy, setBusy] = useState(false);

  // Scroll / column-map mode
  const [scrollMode, setScrollMode] = useState(false);
  const [profiles, setProfiles] = useState([]);
  const [profileName, setProfileName] = useState("tikkun_koreim");
  const [manualColumn, setManualColumn] = useState("");

  const cv = useCameraCV({ autoLocate, hintBook, hintChapter, hintCategory });
  const colmap = useColumnMap({
    ocrText: cv.ocrText,
    yad: cv.yad,
    profileName,
    enabled: scrollMode,
  });

  // Initial loads
  useEffect(() => {
    api.getBooks().then(setBooks).catch((e) => console.warn("[session] getBooks", e));
    api.listScrollProfiles().then(setProfiles).catch((e) => console.warn("[session] listProfiles", e));
  }, []);

  // Push state to projector whenever it changes
  useEffect(() => {
    projectorBus.send({
      type: "state",
      payload: {
        sessionId: id,
        torahPresent: cv.torahPresent,
        yad: cv.yad,
        location: cv.location,
        lines: cv.lines,
        ocrConfidence: cv.ocrConfidence,
        // Column-map mode payload
        scrollMode,
        column: colmap.column,
        columnConfidence: colmap.columnConfidence,
        columnLocked: colmap.locked,
        lineInfo: colmap.lineInfo,
        scrollVerses: colmap.verses,
      },
    });
  }, [
    id, cv.torahPresent, cv.yad, cv.location, cv.lines, cv.ocrConfidence,
    scrollMode, colmap.column, colmap.columnConfidence, colmap.locked,
    colmap.lineInfo, colmap.verses,
  ]);

  const manualLocate = useCallback(async () => {
    if (!hintBook || !hintChapter) return;
    setBusy(true);
    try {
      const ch = await api.getChapter(hintBook, Number(hintChapter));
      const first = ch.verses?.[0];
      if (!first) return;
      const ls = await api.getLines(first.book, first.chapter, first.verse, 2);
      cv.setLocation({
        book: first.book,
        book_he: ch.book_he,
        category: ch.category,
        chapter: first.chapter,
        verse: first.verse,
        confidence: 1,
        matched_text: first.he_plain,
        parsha: ls.parsha || null,
        aliyah: ls.aliyah || null,
        haftarah_for: ls.haftarah_for || null,
      });
      cv.setLines(ls);
    } catch (e) {
      console.warn("[session] manualLocate failed:", e);
    } finally {
      setBusy(false);
    }
  }, [hintBook, hintChapter, cv]);

  const advance = useCallback(async (delta) => {
    if (!cv.location) return;
    const nextV = cv.location.verse + delta;
    if (nextV < 1) return;
    try {
      const ls = await api.getLines(cv.location.book, cv.location.chapter, nextV, 2);
      cv.setLocation({
        ...cv.location, verse: nextV,
        parsha: ls.parsha || null, aliyah: ls.aliyah || null,
        haftarah_for: ls.haftarah_for || null,
      });
      cv.setLines(ls);
    } catch (e) {
      try {
        const newCh = cv.location.chapter + delta;
        if (newCh < 1) return;
        const ch = await api.getChapter(cv.location.book, newCh);
        const first = ch.verses?.[0];
        if (!first) return;
        const ls = await api.getLines(first.book, first.chapter, first.verse, 2);
        cv.setLocation({
          ...cv.location, chapter: newCh, verse: first.verse,
          parsha: ls.parsha || null, aliyah: ls.aliyah || null,
          haftarah_for: ls.haftarah_for || null,
        });
        cv.setLines(ls);
      } catch (e2) {
        console.warn("[session] cross-chapter advance failed:", e, e2);
      }
    }
  }, [cv]);

  const setManualCol = useCallback(() => {
    const n = Number(manualColumn);
    if (n >= 1 && n <= 248) colmap.setColumnManually(n);
  }, [manualColumn, colmap]);

  const openProjector = () => {
    const w = window.open(`/projector/${id}`, "torah_projector", "noopener,noreferrer");
    if (!w) alert("Allow popups to open the projector view.");
  };

  const bookList = hintCategory ? books[hintCategory] : [...books.torah, ...books.neviim, ...books.megillot];

  return (
    <div className="min-h-screen parchment-bg" data-testid="session-page">
      <header className="px-4 sm:px-6 py-4 border-b border-border1 flex items-center justify-between bg-surface">
        <div className="flex items-center gap-3">
          <Link to="/" className="text-xs tracking-[0.25em] uppercase text-ink2 hover:text-ink">Home</Link>
          <span className="text-ink2">/</span>
          <span className="font-display text-lg">Reading Session</span>
        </div>
        <div className="flex items-center gap-2">
          <Link to={`/calibrate/${id}`} data-testid="open-calibration" className="status-pill hover:border-gold">
            <Sliders size={12} /> Calibrate
          </Link>
          <button data-testid="open-projector" onClick={openProjector} className="status-pill hover:border-gold">
            <Projector size={12} /> Projector
          </button>
        </div>
      </header>

      <div className="grid lg:grid-cols-2 gap-6 p-4 sm:p-6 max-w-7xl mx-auto">
        <div className="space-y-4">
          <CameraView
            videoRef={cv.videoRef}
            cameraOn={cv.cameraOn}
            yad={cv.yad}
            onTapYad={cv.setYadManual}
          />
          <CameraControls
            cameraOn={cv.cameraOn}
            onToggle={cv.cameraOn ? cv.stopCamera : cv.startCamera}
            autoLocate={autoLocate}
            setAutoLocate={setAutoLocate}
          />
          <StatusPills
            torahPresent={cv.torahPresent}
            yad={cv.yad}
            ocrConfidence={cv.ocrConfidence}
            ocrReady={cv.ocrReady}
            located={!!cv.location || !!colmap.column}
          />
          <ScrollModePanel
            scrollMode={scrollMode}
            setScrollMode={setScrollMode}
            profiles={profiles}
            profileName={profileName}
            setProfileName={setProfileName}
            colmap={colmap}
            manualColumn={manualColumn}
            setManualColumn={setManualColumn}
            onSetColumn={setManualCol}
          />
          {!scrollMode && (
            <ManualOverride
              books={books}
              bookList={bookList}
              hintCategory={hintCategory}
              setHintCategory={(v) => { setHintCategory(v); setHintBook(""); }}
              hintBook={hintBook}
              setHintBook={setHintBook}
              hintChapter={hintChapter}
              setHintChapter={setHintChapter}
              ocrText={cv.ocrText}
              busy={busy}
              onLocate={manualLocate}
            />
          )}
          {cv.error && (
            <div className="border border-warning/40 bg-warning/10 text-warning px-4 py-3 flex items-start gap-2 text-sm">
              <AlertTriangle size={16} className="mt-0.5" /> <div>{cv.error}</div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          {scrollMode ? (
            <ColumnMapPanel colmap={colmap} />
          ) : (
            <ActiveLinesPanel location={cv.location} lines={cv.lines} onAdvance={advance} />
          )}
          <div className="text-xs text-ink2 leading-relaxed">
            <Crosshair size={12} className="inline mr-1 -mt-0.5" />
            {scrollMode
              ? "Column-map mode: OCR identifies which scroll column you're on; the yad's vertical position determines the active line geometrically."
              : "The cantillation marks (te'amim) above appear in real Torah-trope form. Once the yad lands on a verse, this panel updates automatically."}
          </div>
        </div>
      </div>
    </div>
  );
}

function CameraView({ videoRef, cameraOn, yad, onTapYad }) {
  const handleTap = useCallback(
    (e) => {
      if (!cameraOn || !onTapYad) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      if (x < 0 || x > 1 || y < 0 || y > 1) return;
      onTapYad({ x, y });
    },
    [cameraOn, onTapYad]
  );
  return (
    <div
      className="relative bg-black overflow-hidden border border-border1 aspect-[4/3]"
      onClick={handleTap}
      data-testid="camera-view"
      role="button"
      tabIndex={cameraOn ? 0 : -1}
    >
      <video
        ref={videoRef}
        data-testid="camera-video"
        className="absolute inset-0 w-full h-full object-cover"
        playsInline muted
      />
      {!cameraOn && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-parchment/80 gap-3">
          <Camera size={32} />
          <div className="text-xs tracking-[0.25em] uppercase">Camera off</div>
        </div>
      )}
      {cameraOn && (
        <svg className="reticle" viewBox="0 0 100 75" preserveAspectRatio="none">
          <rect x="10" y="8" width="80" height="59" fill="none" stroke="#FFD700" strokeWidth="0.2" strokeDasharray="2 1" />
          <line x1="50" y1="0" x2="50" y2="75" stroke="#FFD700" strokeWidth="0.1" opacity="0.4" />
          <line x1="0" y1="37.5" x2="100" y2="37.5" stroke="#FFD700" strokeWidth="0.1" opacity="0.4" />
        </svg>
      )}
      {cameraOn && yad && (
        <div
          className="absolute pointer-events-none"
          style={{ left: `${yad.x * 100}%`, top: `${yad.y * 100}%` }}
          data-testid="yad-marker"
        >
          <div
            className={`w-10 h-10 -translate-x-1/2 -translate-y-1/2 border-2 ${
              yad.manual ? "border-projgold" : "border-projgold/70"
            } rounded-full animate-pulse`}
            style={{ boxShadow: "0 0 20px rgba(255,215,0,0.6)" }}
          />
          {yad.manual && (
            <div
              className="absolute -translate-x-1/2 mt-7 text-[10px] tracking-[0.2em] uppercase text-projgold whitespace-nowrap"
              style={{ left: "50%", textShadow: "0 1px 2px #000" }}
              data-testid="yad-manual-badge"
            >
              Manual
            </div>
          )}
        </div>
      )}
      {cameraOn && (
        <div
          className="absolute bottom-2 left-2 right-2 text-center text-[10px] tracking-[0.2em] uppercase text-parchment/60 pointer-events-none"
          data-testid="yad-tap-hint"
        >
          Tap to mark yad position (30 s)
        </div>
      )}
    </div>
  );
}

function CameraControls({ cameraOn, onToggle, autoLocate, setAutoLocate }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        data-testid="toggle-camera"
        onClick={onToggle}
        className="inline-flex items-center gap-2 bg-ink text-parchment px-4 py-2 hover:bg-gold transition-colors"
      >
        {cameraOn ? <CameraOff size={16} /> : <Camera size={16} />}
        {cameraOn ? "Stop camera" : "Start camera"}
      </button>
      <label className="inline-flex items-center gap-2 status-pill">
        <input
          type="checkbox"
          data-testid="auto-locate-toggle"
          checked={autoLocate}
          onChange={(e) => setAutoLocate(e.target.checked)}
        />
        Auto-locate
      </label>
    </div>
  );
}

function ScrollModePanel({
  scrollMode, setScrollMode, profiles, profileName, setProfileName, colmap,
  manualColumn, setManualColumn, onSetColumn,
}) {
  return (
    <div className="bg-surface border border-border1 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs tracking-[0.25em] uppercase text-ink2 flex items-center gap-2">
          <Layers size={12} /> Scroll column-map
        </div>
        <label className="inline-flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            data-testid="scroll-mode-toggle"
            checked={scrollMode}
            onChange={(e) => setScrollMode(e.target.checked)}
          />
          Enabled
        </label>
      </div>
      {scrollMode && (
        <div className="flex flex-wrap gap-2 items-center">
          <select
            data-testid="profile-select"
            value={profileName}
            onChange={(e) => setProfileName(e.target.value)}
            className="bg-transparent border border-border1 px-3 py-2 text-sm"
          >
            {profiles.map((p) => (
              <option key={p.name} value={p.name}>{p.title} ({p.column_count} cols)</option>
            ))}
          </select>
          <input
            data-testid="manual-column-input"
            type="number" min="1" max="248" placeholder="Column #"
            value={manualColumn}
            onChange={(e) => setManualColumn(e.target.value)}
            className="bg-transparent border border-border1 px-3 py-2 text-sm w-28"
          />
          <button
            data-testid="set-column-button"
            onClick={onSetColumn}
            disabled={!manualColumn}
            className="inline-flex items-center gap-1 bg-ink text-parchment px-3 py-2 text-sm disabled:opacity-50"
          >
            Set
          </button>
          <span className="text-xs text-ink2 ml-auto">
            {colmap.column ? (
              <>
                Col <span className="text-ink font-semibold">{colmap.column}</span>
                {" · "}
                <span className={colmap.locked ? "text-success" : "text-warning"}>
                  {colmap.locked ? "locked" : "searching"}
                </span>
                {" · "}
                {Math.round(colmap.columnConfidence * 100)}%
              </>
            ) : "no column"}
          </span>
        </div>
      )}
    </div>
  );
}

function ColumnMapPanel({ colmap }) {
  if (!colmap.column) {
    return (
      <div className="bg-surface border border-border1 p-6 sm:p-8 text-center text-ink2 py-16">
        <Layers size={32} className="mx-auto mb-3 opacity-50" />
        <div className="text-sm">Waiting for OCR to identify the active column…</div>
      </div>
    );
  }
  const verses = colmap.verses || [];
  return (
    <div className="bg-surface border border-border1 p-6 sm:p-8">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-xs tracking-[0.25em] uppercase text-ink2">Now Reading</div>
          <div className="font-display text-2xl mt-1">
            <span className="text-ink">Column {colmap.column}</span>
            {colmap.lineInfo && (
              <>
                {" · "}
                <span className="text-gold">Line {colmap.lineInfo.line}/{colmap.lineInfo.lines_in_column}</span>
              </>
            )}
          </div>
        </div>
        <span className={`status-pill ${colmap.locked ? "ok" : "warn"}`}>
          <span className="dot" /> {colmap.locked ? "Locked" : "Searching"}
          {" · "}{Math.round(colmap.columnConfidence * 100)}%
        </span>
      </div>
      <div className="space-y-4 text-right" dir="rtl" data-testid="column-map-lines">
        {verses.length === 0 && (
          <div className="text-ink2 text-center py-8">Yad position not yet detected.</div>
        )}
        {verses.map((v) => (
          <div key={`${v.book}-${v.chapter}-${v.verse}`} className="hebrew-line hebrew-active">
            <span className="text-xs tracking-[0.2em] uppercase text-ink2 ml-2">
              {v.book} {v.chapter}:{v.verse}
            </span>
            {v.he_with_teamim}
          </div>
        ))}
      </div>
      {colmap.lineInfo && (
        <div className="mt-6 pt-4 border-t border-border1 text-xs text-ink2 text-right hebrew-line" dir="rtl">
          <span className="text-[10px] tracking-[0.2em] uppercase ml-2">Scroll line:</span>
          {colmap.lineInfo.text_plain}
        </div>
      )}
    </div>
  );
}

function ManualOverride({
  bookList, hintCategory, setHintCategory, hintBook, setHintBook,
  hintChapter, setHintChapter, ocrText, busy, onLocate,
}) {
  return (
    <div className="bg-surface border border-border1 p-4">
      <div className="text-xs tracking-[0.25em] uppercase text-ink2 mb-3">Manual override</div>
      <div className="flex flex-wrap gap-2 items-center">
        <select
          data-testid="hint-category-select"
          value={hintCategory}
          onChange={(e) => setHintCategory(e.target.value)}
          className="bg-transparent border border-border1 px-3 py-2"
        >
          <option value="">All readings</option>
          <option value="torah">Torah · תורה</option>
          <option value="neviim">Nevi'im · נביאים</option>
          <option value="megillot">Megillot · מגילות</option>
        </select>
        <select
          data-testid="hint-book-select"
          value={hintBook}
          onChange={(e) => setHintBook(e.target.value)}
          className="bg-transparent border border-border1 px-3 py-2 max-w-[180px]"
        >
          <option value="">Any book</option>
          {bookList.map((b) => (
            <option key={b.en} value={b.en}>{b.en} · {b.he}</option>
          ))}
        </select>
        <input
          data-testid="hint-chapter-input"
          type="number" min="1" placeholder="Chapter"
          value={hintChapter}
          onChange={(e) => setHintChapter(e.target.value)}
          className="bg-transparent border border-border1 px-3 py-2 w-28"
        />
        <button
          data-testid="manual-locate-button"
          onClick={onLocate}
          disabled={!hintBook || !hintChapter || busy}
          className="inline-flex items-center gap-1 bg-ink text-parchment px-4 py-2 disabled:opacity-50 hover:bg-gold transition-colors"
        >
          {busy ? <Loader2 className="animate-spin" size={14} /> : <Target size={14} />}
          Locate
        </button>
      </div>
      {ocrText && (
        <div className="mt-3 text-right hebrew-line text-base text-ink2" dir="rtl" data-testid="ocr-text">
          <span className="text-xs tracking-[0.2em] uppercase text-ink2 ml-2">OCR:</span>
          {ocrText}
        </div>
      )}
    </div>
  );
}
