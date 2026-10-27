# Torah Chanting Aid

A phone-and-projector aid for the Torah reader (*ba'al koreh*). The phone's camera watches the open scroll on the bimah and works out exactly where in the Torah it is open. It follows the reader's *yad* (pointer) and projects the cantillation (trope / te'amim) for the active line straight onto the parchment, using an HDMI projector connected to the phone.

The reader chants the way they always do. The scroll stays unmarked, and the trope is only light.

> **100% offline.** Everything needed at the bimah is bundled with the app: the Hebrew text corpus, the OCR model, hand tracking, and the fonts. It needs no internet connection, CDN or external API during use.

---

## Features

- **Location detection by OCR.** On-device Hebrew OCR (Tesseract.js) reads the unvocalized scribal text. N-gram fuzzy matching then finds the book, chapter and verse among 15,887 verses (Torah, Nevi'im and Megillot).
- **Column-map tracking.** A Torah scroll has a fixed layout: 245 or 248 columns of 42 lines each. OCR'd text is matched to a physical column, and the yad's position gives the exact line within it.
- **Yad tracking.** MediaPipe Hands runs offline (WASM) and finds the pointer tip. A warm-dark blob detector is used when no hand is visible, and you can tap the screen to set the position yourself.
- **Trope projection.** A second screen shows the trope-marked Hebrew in Noto Serif Hebrew. A homography (perspective transform) maps it onto the physical scroll.
- **Projector auto-calibration.** The projector shows four fiducial markers. The camera finds them, and the app computes the camera-to-projector transform.
- **Context display.** It shows the current book, parsha and aliyah (from Sefaria's aliyah tables) and, for Nevi'im readings, the haftarah.
- **Multi-frame OCR voting.** Votes over a rolling window keep a single bad frame from moving the locked column.
- **Torah presence detection.** It detects whether the scroll is present and open, or absent or closed.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18 PWA, React Router, Tailwind CSS, shadcn/ui |
| On-device CV | Tesseract.js 5 (Hebrew `tessdata_fast`), MediaPipe Tasks-Vision (Hand Landmarker), custom canvas CV, CSS `matrix3d` homography |
| Offline | Service worker that pre-caches the app shell, the WASM files, the models and the fonts |
| Backend | FastAPI (Python 3.11) |
| Data | Bundled JSON (corpus, aliyot, scroll profiles) and MongoDB (sessions and calibration) |

## Project structure

```
backend/
  server.py                 FastAPI app: Torah, locate, sessions, calibration routes
  scroll_routes.py          /api/scroll/* column-map routes
  scroll_profiles.py        Column-map loading + locate_column scoring
  build_corpus.py           Build-time: fetch corpus from Sefaria -> data/torah_corpus.json
  build_aliyot.py           Build-time: fetch aliyah tables -> data/aliyot.json
  build_column_map.py       Build-time: parse Tikkun PDF -> 42-line column map
  build_synthetic_profile.py  Build-time: synthetic 248-column profile
  data/
    torah_corpus.json       15,887 verses with cantillation
    aliyot.json             54 parshiyot x 7 aliyot
    scroll_profiles/        tikkun_koreim.json (245 cols), synthetic_248.json
  tests/                    pytest suites
frontend/
  public/
    service-worker.js       Offline pre-cache
    tesseract/, tessdata/   OCR engine + Hebrew model
    mediapipe/              Hand Landmarker model + WASM
    fonts/                  Self-hosted fonts
  src/
    pages/                  HomePage, SessionPage, CalibrationPage, ProjectorPage
    components/             ActiveLinesPanel, StatusPills
    lib/                    api, cv, ocr, transform, handLandmarker,
                            useCameraCV, useColumnMap, projectorBus
```

## Getting started

### Prerequisites
- Python 3.11+
- Node.js 18+ and Yarn
- MongoDB (local)

### Backend
```bash
cd backend
pip install -r requirements.txt
```
Create `backend/.env`:
```
MONGO_URL=mongodb://localhost:27017
DB_NAME=torah_aid
SEFARIA_BASE_URL=https://www.sefaria.org
```
`SEFARIA_BASE_URL` is used only by the build-time scripts. The app does not call it at runtime.
```bash
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend
```bash
cd frontend
yarn install
```
Create `frontend/.env`:
```
REACT_APP_BACKEND_URL=http://localhost:8001
```
```bash
yarn start      # development
yarn build      # production build (enables the offline service worker)
```

### Regenerating the bundled data (optional, needs internet)
```bash
cd backend
python build_corpus.py
python build_aliyot.py
python build_column_map.py
```
A column map must keep exactly **42 lines per column**.

## How to use

1. Open the app in mobile Chrome on the phone. Connect the projector over HDMI or USB-C.
2. Start a session on the **Home** page.
3. Open the **Projector** view on the external display.
4. Run **Calibrate**. Aim the camera at the projected markers, and the app finds them on its own.
5. Point the camera at the open scroll. Once it locks the location, the projector shows the trope for the line under the yad.
6. If tracking loses the yad, tap the camera view to set the line by hand. You can also choose a book and chapter manually to jump straight to it.

## API reference

All routes start with `/api`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/index/build` | Build the in-memory search index |
| GET | `/torah/books` | Books grouped by category |
| GET | `/torah/parshiyot` | The 54 parshiyot |
| GET | `/torah/haftarot` | Haftarah map (Ashkenazi) |
| GET | `/torah/chapter/{book}/{chapter}` | Verses of a chapter, with trope |
| POST | `/torah/locate` | Fuzzy-match OCR text to book, chapter and verse |
| POST | `/torah/lines` | Active verse plus surrounding verses |
| POST / GET / PATCH | `/sessions`, `/sessions/{id}` | Reading sessions |
| POST / GET | `/calibration`, `/calibration/{session_id}` | Saved projector homography |
| GET | `/scroll/profiles` | Available scroll layouts |
| GET | `/scroll/profile/{name}` | Profile metadata |
| GET | `/scroll/{name}/column/{n}` | Lines of one column |
| POST | `/scroll/locate-column` | Match OCR text to a physical column |
| POST | `/scroll/line-at` | Line at a vertical position in a column |

## Testing
```bash
cd backend
pytest tests/ -v
```

## Rebuilding from scratch
[`PROMPT.md`](PROMPT.md) holds the full prompt for rebuilding this project with an AI app builder.

## Credits
- Hebrew text, cantillation and aliyah data: [Sefaria](https://www.sefaria.org) (fetched once at build time).
- OCR: [Tesseract.js](https://github.com/naptha/tesseract.js). Hand tracking: [MediaPipe](https://developers.google.com/mediapipe).
- Font: Noto Serif Hebrew (SIL Open Font License).
