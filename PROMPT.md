# Build Prompt: Torah Chanting Aid

Paste the prompt below into an AI app builder to recreate this project.

---

**Build a "Torah Chanting Aid": a phone-and-projector tool for the Torah reader (ba'al koreh)**

**Goal**
A Torah scroll has no vowels (nekudot), punctuation or cantillation (trope / te'amim). I want a phone, mounted above the bimah, to watch the open scroll with its camera and work out exactly where in the Torah it is open. It should follow the reader's yad (pointer) and project the trope-marked Hebrew for the active line straight onto the parchment, using a projector connected to the phone's HDMI / USB-C port. The reader chants as usual and the scroll is never touched or marked.

**Hard constraint: 100% offline**
Nothing may need the internet while it's in use. No CDNs, no Google Fonts and no runtime API calls. Bundle everything:
- the Hebrew text corpus
- the OCR engine and Hebrew model
- the hand-tracking model and its WASM files
- the fonts

Use a service worker that pre-caches all of this so the app starts cold with no network. Outside data (Sefaria) may be fetched only by build-time scripts that write static JSON.

**Stack**
- React 18 PWA with React Router, Tailwind and shadcn/ui, mobile-first for Chrome on Android.
- FastAPI backend with every route under `/api`.
- Static JSON bundles for the corpus and layouts; MongoDB only for sessions and calibration.
- On-device processing:
  - Tesseract.js with the Hebrew `tessdata_fast` model, self-hosted
  - MediaPipe Tasks-Vision Hand Landmarker, self-hosted model + WASM
  - Self-hosted Noto Serif Hebrew, which renders te'amim correctly

**Data (build-time scripts → `backend/data/`)**
1. `build_corpus.py`: fetch the Torah, Nevi'im and Megillot from Sefaria using the "Tanach with Ta'amei Hamikra" version, with cantillation (about 15,900 verses). Store each verse twice: once with trope for display, and once with all marks stripped for matching. Tag each verse `torah | neviim | megillot`.
2. `build_aliyot.py`: fetch Sefaria's parasha alt-structure and store exact aliyah verse boundaries (54 parshiyot × 7 aliyot) in `aliyot.json`. Also include the 54-entry Ashkenazi haftarah map.
3. `build_column_map.py`: parse a Tikkun Koreim layout into a **column-map scroll profile**. A standard Sefer Torah has 245 columns (some have 248) with exactly **42 lines per column**, and that must be enforced. Each line stores its letters and the verse(s) it covers. Also generate a synthetic 248-column profile.

**Core pipeline (in the browser, requestAnimationFrame loop)**
1. **Torah presence:** a brightness / parchment check decides whether the scroll is present and open, or absent or closed.
2. **Yad tip**, in this priority order:
   - a manual tap on the camera view (held for 30 s, with a visible "MANUAL" badge)
   - otherwise, the MediaPipe index-fingertip landmark
   - otherwise, a warm-dark-blob detector (connected components, rejecting the scroll rollers, tip found by PCA)
3. **OCR:** crop the area around the yad (and the whole column), run Tesseract Hebrew, and send the text to the backend.
4. **Locate:** use a character 3-gram fuzzy matcher with a 3-verse sliding window.
   - It must tolerate about 40% OCR errors on scribal (Stam) script, including common letter swaps (ה↔ת, מ↔ב, כ↔ב, ר↔ד).
   - Reject snippets shorter than about 18 compact characters.
   - Column matching should use a length-normalized recall + precision score, so that short clean snippets still clear the margin threshold.
5. **Multi-frame voting:** keep a rolling window of about 6 votes, weighted by confidence × margin. Lock the column only when one candidate has at least 55% of the weighted share, so a single bad frame can't unlock it.
6. **Line:** the yad's vertical position within the locked column gives the line number (1–42). That line gives the verse.

**Projector**
- A separate `/projector/:sessionId` route runs fullscreen on the extended HDMI display. It is a second window, not a mirror of the phone screen.
- It shows a pure-black background with the active line's trope-marked Hebrew in gold or red, plus a header with the book, parsha, aliyah and chapter:verse.
- It stays in sync with the session through a BroadcastChannel, plus localStorage so a newly opened window picks up the current state.
- A homography (perspective transform) maps the text onto the physical parchment. Compute it in the browser (Gauss-Jordan) and apply it with CSS `matrix3d()`.

**Auto-calibration (no manual corner tapping)**
1. The projector shows 4 unique fiducial markers at known corners (dice patterns with 1–4 pips, or ArUco-style markers).
2. The camera captures a baseline frame (projector black) and a pattern frame. Subtracting the two removes ambient light.
3. Adaptive threshold → blob extraction → pick the 4 brightest squares → count pips to identify each corner.
4. Require 3 stable frames (at most 2.5% drift) and average the corner positions.
5. Save the homography per session, then flash a center crosshair to confirm.

**Pages**
- `/` Home: branding, offline/health status, "Start session".
- `/session/:id` Session:
  - live camera view with the yad marker
  - status pills: Torah present, yad tracking %, OCR confidence, location lock
  - an active-lines panel: previous, active (bold, with trope) and next verse
  - book / parsha / aliyah display, plus the haftarah when reading from Nevi'im
  - manual book + chapter override
  - tap-to-set yad
- `/calibrate/:id`: the auto-calibration flow.
- `/projector/:id`: the projection output.

Use a dignified parchment-and-ink look (deep ink, parchment cream, gold accents). Give every interactive element a `data-testid`.

**API (`/api`)**
- `GET /health`, `POST /index/build`
- `GET /torah/books` (grouped by category), `GET /torah/parshiyot`, `GET /torah/haftarot`, `GET /torah/chapter/{book}/{ch}`
- `POST /torah/locate`: OCR text plus optional book / category hints → book, chapter, verse, parsha, aliyah, score, plus `haftarah_for` for Nevi'im
- `POST /torah/lines`: the active verse plus the verses around it, staying inside the same book
- `POST/GET/PATCH /sessions[/{id}]`, `POST /calibration`, `GET /calibration/{session_id}`
- `GET /scroll/profiles`, `GET /scroll/profile/{name}`, `GET /scroll/{name}/column/{n}`
- `POST /scroll/locate-column`: OCR text → column number, margin and candidates
- `POST /scroll/line-at`: column + vertical position → line + verse

**Acceptance**
- Pytest suites cover locate accuracy, column matching, the 42-lines-per-column rule, aliyah boundaries, sessions and calibration.
- OCR on real Tikkun Koreim pages gets the correct chapter on 10 out of 10 pages.
- The network tab shows zero external requests once the app is loaded.
- Optional: a Python + OpenCV script that takes real scroll video and renders a demo MP4 with the perspective-warped trope overlay on the visible columns.

---

Tip: adding photos of your bimah setup and a sample scroll video at the start will help the build match your conditions.
