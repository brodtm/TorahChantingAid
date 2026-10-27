# Torah Chanting Aid — PRD

## Original Problem Statement
Build a phone-mounted aid for Torah chanting that:
1. Watches an open Torah scroll on the bimah via the phone camera.
2. OCRs the un-vocalized Hebrew text, fuzzy-matches it to the Torah corpus (Sefaria), and locates the exact biblical position.
3. Tracks the yad (pointer) to know which verse/line is being read in real time.
4. Displays the active verse with cantillation marks (te'amim), plus previous and next verses for context, with the active line bold.
5. Drives an HDMI projector mounted above the bimah (separate display, not screen mirror) and projects the trope-marked active line directly onto the parchment using a 4-point affine/homography transform from a manual calibration routine.
6. Detects torah presence/open vs absent/closed.
7. Existing chanting practice must be unchanged — the user uses the yad as always.

## User Choices
- Path: **Web PWA (Path A)** — full live working demo in mobile Chrome.
- Location detection: OCR-based (Tesseract.js client-side, Hebrew model).
- Sefaria API: yes, with cantillation (Tanach with Ta'amei Hamikra version).
- Yad tracking: active CV-based (no manual line advancement needed).
- Projector calibration: 4-point manual corner-tap producing a homography.

## Architecture
- **Backend**: FastAPI + MongoDB. Routes prefixed `/api`.
  - `/api/health`, `/api/index/build`, `/api/torah/{books,parshiyot,chapter/{book}/{ch},locate,lines}`, `/api/sessions`, `/api/calibration`.
  - On-demand fetch of full Torah corpus from Sefaria v3 API (cached in-memory; ~5846 verses).
  - Hebrew text stored with cantillation; stripped twin used for matching.
  - Parsha boundaries (54 parshiyot) and aliyah estimator built-in.
- **Frontend**: React PWA, react-router. Pages:
  - `/` HomePage — branding, health, start session.
  - `/session/:id` SessionPage — camera, CV, OCR loop, status pills, active-line panel, manual override.
  - `/calibrate/:id` CalibrationPage — 4-corner draggable handles on black grid; saves homography.
  - `/projector` & `/projector/:id` ProjectorPage — pure-black with gold trope text, mirrored from session via BroadcastChannel + localStorage.
- **Cross-route sync**: BroadcastChannel `torah-aid-projector` + cached state in localStorage so newly opened projector window picks up current state.
- **CV pipeline (browser, requestAnimationFrame loop)**:
  - Brightness check → torah present.
  - Dark-blob centroid detection in lower-mid ROI → yad tip {x,y,score}.
  - Crop horizontal strip around yad y → Tesseract.js Hebrew OCR.
  - Send OCR'd text to `/api/torah/locate` (with optional book/chapter hint).
- **Homography**: client-side `computeHomography` (Gauss-Jordan), rendered via CSS `matrix3d()` on the projector container.

## Verified (2026-01-07): OCR pipeline tested end-to-end against real Tikkun Koreim PDF
- Pipeline: PDF page render → crop Stam (scribal Torah) column → Tesseract heb (bundled `tessdata_fast`) → `/api/torah/locate`.
- **10/10 pages chapter-correct, 7/10 pinpoint-correct on the verse**, despite Tesseract producing ~40% character errors on the unfamiliar Stam script.
- The 3-gram fuzzy matcher (with 3-verse sliding window) is robust to Tesseract's systematic letter substitutions (ה↔ת, מ↔ב, כ↔ב, ר↔ד).
- Full report at `/app/test_reports/tikkun_ocr_report.md`.
- Improvement: backend now requires snippet ≥ 18 chars (compact) before searching — eliminates false positives from tiny noise fragments.
- Production recommendation: combine OCR-locate with user-set `hint_book` (parsha pre-select) and temporal voting across frames for ~100% accuracy.

## Implemented (2026-01-07)
- **100% offline operation**: every dependency now bundled with the app:
  - `/app/backend/data/torah_corpus.json` — 3.9 MB, 15,887 verses, Torah + Nevi'im + Megillot with cantillation marks
  - `/app/frontend/public/tessdata/heb.traineddata.gz` — 473 KB, Hebrew OCR language model (`tessdata_fast`)
  - `/app/frontend/public/tesseract/` — 14 MB, Tesseract.js worker + WASM core (LSTM + SIMD-LSTM variants)
  - `/app/frontend/public/fonts/` — 1.3 MB, self-hosted Noto Serif Hebrew (te'amim-capable), Cormorant Garamond, Inter (no Google Fonts dependency)
  - `/app/frontend/public/service-worker.js` — production-mode service worker that pre-caches everything above + the React build, with cache-first for static assets and network-first w/ cache fallback for /api
  - **Verified zero external CDN requests** — Google Fonts and jsdelivr.net both fully replaced.
- **Category awareness**: every verse tagged `torah | neviim | megillot`; `/api/torah/books` returns grouped lists; `/api/torah/locate` accepts `hint_category` and returns `category` + `haftarah_for` when applicable; lines traversal stays inside the same book.
- **54-entry Haftarah map** (Ashkenazi tradition) — when located in Nevi'im, the app shows "Haftarah for [parsha name]". Endpoint: `/api/torah/haftarot`.
- Full backend with offline corpus, fuzzy Hebrew location matcher, parsha + aliyah lookup.
- Parsha + aliyah lookup.
- Sessions + calibration persistence (MongoDB, UUID ids, no ObjectId leakage).
- Mobile-first React PWA with 4 routes, parchment aesthetic, Noto Serif Hebrew rendering te'amim correctly.
- Camera + brightness/yad CV detector + Tesseract.js Hebrew OCR worker.
- **Auto-calibration via projected ArUco-style fiducials (2026-01-07 v2)**:
  - Projector displays 4 unique dice-pattern fiducials (1/2/3/4 pips) at known corner coords.
  - Camera captures baseline (projector black) + pattern frames; image subtraction suppresses ambient.
  - Adaptive-threshold flood-fill blob extraction → ranks 4 brightest squares → counts internal pips to identify corner ID unambiguously.
  - 3-frame stability check (≤2.5% drift) before commit; centroids averaged for sub-pixel accuracy.
  - Verification step: projector flashes center crosshair after save.
  - Manual fallback removed per user direction.
- Projector route: pure black, gold cantillation text, header (book/parsha/aliyah), live-synced via BroadcastChannel; supports modes `session | calibration_off | calibration_pattern | calibration_verify`.
- Status pills: Torah present/absent, Yad tracking %, OCR confidence, Location lock.
- Manual override: book + chapter selectors → instant Locate.
- 15/15 backend tests passing.

## Implemented (2026-02 fork)
- **P0 — Yad tracking**
  - `cv.js::detectYadTip` rewritten with warm-dark mask + connected-
    components + scroll-roller rejection + PCA tip extraction.
  - **MediaPipe Hand Landmarker** (Tasks-Vision) bundled fully offline at
    `/mediapipe/hand_landmarker.task` (7.8 MB) + WASM (11 MB). Index-finger
    tip (landmark 8) is used as the yad tip when a hand is in frame;
    auto-detection priority is **manual tap > MediaPipe > warm-dark blob**.
  - Service-worker (`v2`) precaches MediaPipe model + WASM for cold-start
    offline use.
  - **Tap-to-set fallback** in `SessionPage.CameraView` (30 s hold,
    visible "MANUAL" badge + bottom hint).
- **P1 — Aliyah table**: `build_aliyot.py` fetches Sefaria's
  `alts.Parasha.nodes` for all 5 Torah books → `data/aliyot.json` (54
  parshiyot × 7 aliyot = 378 boundaries, 30.6 KB). `estimate_aliyah` now
  consults the table; legacy estimator kept as fallback only.
- **P1 — Multi-frame OCR voting**: `useColumnMap` now keeps a rolling
  6-vote window weighted by `max(0.1, confidence) × (1 + margin)`.
  Locks the column when one candidate's weighted share ≥ 0.55. Single
  bad OCR frames can no longer unlock a hard-won column.
- **P1 — locate_column short-snippet boost**: scoring switched to
  `recall^1.5 + 5 × precision`. Short clean Bereshit margin 0.083 →
  0.256 (above the 0.25 floor), long-snippet behaviour preserved
  (margin > 0.9). Real-video Emor columns still match correctly.
- **P1 — Tightened Tikkun column map** (build_column_map.py): median
  60.5 → **42** lines/col, 245 cols × 10,002 lines, 305,859 letters
  preserved.
- **Refactor — `scroll_routes.py`**: pulled 6 `/api/scroll/*` endpoints
  out of `server.py` into their own module via `register(api)`.
- **Output overlay video** (`/demo/torah_overlay.mp4`, 16 MB): 10 s
  annotated copy of the user's Emor clip showing the yad position, the
  matched column, parsha, aliyah, and the trope-marked active verse
  rendered in Noto Serif Hebrew.

## Verified (2026-02 — iteration_6.json)
- **67/67** backend pytest tests pass (10 new iter-6 acceptance + 57
  regression). Frontend smoke: 0 console errors, all data-testids
  present, demo MP4 + MediaPipe assets all serve 200.
## Backlog
- **P1**: Replace estimated aliyah with real Sefaria aliyah-table data (each parsha's exact aliyah verse boundaries).
- **P1**: Multi-frame OCR voting / temporal smoothing to reduce flicker on poor-light frames.
- **P1**: Persistent index across restarts (write to MongoDB once, skip Sefaria refetch).
- **P1**: Improve `locate_column` short-snippet scoring — current recall+5×precision boosted the 0.083→0.217 margin on Bereshit-only 30-char fragments; add a length-normalised score component to clear the 0.30 threshold.
- **P2**: Detect column scroll (large frame change) and reset OCR cadence.
- **P2**: True yad-tip detection via lightweight TF-Lite/MediaPipe model — current canvas-only `detectYadTip` is reliable for high-contrast yads but degrades on warm-on-warm lighting; the manual tap fallback covers that case for now.
- **P2**: Auto-rotate Hebrew Sof Pasuk / paragraph break recognition.
- **P2**: Render the tap-to-set hint as a small persistent help-pill even when camera is off (currently only shown when cameraOn=true).
- **P3**: Native React Native + Android `Presentation` API port for true HDMI control independent of the phone screen.
- **P3**: Multi-language UI (English/Hebrew toggle).
- **Refactor (deferred)**: `server.py` is 940 lines — move the 6 `/api/scroll/*` routes into a `scroll_routes.py` module.

## Test credentials
None — no auth in this MVP.

## Jun 2026
- User asked to push to https://github.com/brodtm/TorahChantingAid.git; directed to the "Save to Github" chat feature (agent cannot push directly). No code changes.

