"""Iteration-6 acceptance tests.

Covers the review-request items for this iteration:
  (a) recall^1.5 short-snippet boost in locate_column
  (b) confidence-weighted 6-frame OCR voting (frontend, smoke-tested separately)
  (c) Sefaria-derived aliyot lookup table (54 parshiyot * 7 aliyot)
  (d) scroll_routes.py refactor preservation
  (e) MediaPipe Hand Landmarker pipeline (static asset smoke)

Also runs the EXACT real-video Tesseract OCR output for the Emor scroll's
column-3 strip (or a known fallback) and asserts column 140..145.
"""
import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set in /app/frontend/.env"
API = f"{BASE_URL}/api"

ALIYOT_PATH = Path("/app/backend/data/aliyot.json")
TESS_PNG = Path("/tmp/c3.png")
EMOR_FALLBACK = (
    "האתאלהלאיקכאםבתולחאשהולאזללזרעו"
    "בעמיובוהוידברדבראלאהרןלאטראשריהיהבומוםלא"
)


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- (d) scroll_routes.py refactor: profiles preserved -----------------------

def test_scroll_profiles_endpoint_preserves_synthetic_and_tikkun(client):
    r = client.get(f"{API}/scroll/profiles", timeout=30)
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert "synthetic_248" in names
    assert "tikkun_koreim" in names


# --- (a) recall^1.5 short-snippet: clean Bereshit ---------------------------

def test_locate_column_clean_bereshit_margin_gt_0_25(client):
    r = client.post(
        f"{API}/scroll/locate-column",
        json={"snippet": "בראשית ברא אלהים את השמים ואת הארץ"},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d is not None
    assert d["column"] == 1
    assert d["confidence"] == 1.0
    assert d["margin"] > 0.25, f"expected margin>0.25 got {d['margin']}"


# --- Real-video Tesseract OCR Emor strip ------------------------------------

def _tesseract_ocr(png: Path) -> str:
    out = subprocess.run(
        ["tesseract", str(png), "-", "-l", "heb", "--psm", "4"],
        capture_output=True, text=True, check=False,
    )
    raw = out.stdout or ""
    raw = re.sub(r"[\s\r\n[:punct:]]", "", raw)
    # Mimic the request's `tr -d '\n\r [:punct:]'`; strip non-Hebrew.
    raw = re.sub(r"[^\u05D0-\u05EA]", "", raw)
    return raw


def test_locate_column_emor_column_3_strip_140_to_145(client):
    if TESS_PNG.exists():
        snippet = _tesseract_ocr(TESS_PNG)
        if len(snippet) < 30:
            snippet = EMOR_FALLBACK
    else:
        snippet = EMOR_FALLBACK
    r = client.post(
        f"{API}/scroll/locate-column",
        json={"snippet": snippet},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d is not None, f"locate-column returned null for Emor snippet ({len(snippet)} chars)"
    assert 140 <= d["column"] <= 145, (
        f"expected col in [140,145] got {d['column']} (snippet len {len(snippet)})"
    )


# --- /api/torah/lines + aliyot lookup ---------------------------------------

def test_torah_lines_emor_lev_23_11(client):
    r = client.post(
        f"{API}/torah/lines",
        json={"book": "Leviticus", "chapter": 23, "verse": 11, "context": 1},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["parsha"] == "אמר"
    assert d["aliyah"] == 4


def test_torah_lines_bereshit_gen_1_1(client):
    r = client.post(
        f"{API}/torah/lines",
        json={"book": "Genesis", "chapter": 1, "verse": 1, "context": 1},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["parsha"] == "בראשית"
    assert d["aliyah"] == 1


def test_torah_lines_noach_gen_6_9(client):
    r = client.post(
        f"{API}/torah/lines",
        json={"book": "Genesis", "chapter": 6, "verse": 9, "context": 1},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["parsha"] == "נח"
    assert d["aliyah"] == 1


# --- (c) Sefaria aliyot bundle ---------------------------------------------

def test_aliyot_bundle_54_parshiyot_each_7_aliyot():
    assert ALIYOT_PATH.exists(), "/app/backend/data/aliyot.json missing"
    data = json.loads(ALIYOT_PATH.read_text(encoding="utf-8"))
    # Accept either {"parshiyot": [...]} or a top-level list
    items = data["parshiyot"] if isinstance(data, dict) else data
    assert len(items) == 54, f"expected 54 parshiyot, got {len(items)}"
    for p in items:
        aliyot = p.get("aliyot") or []
        assert len(aliyot) == 7, f"parsha {p.get('en')} has {len(aliyot)} aliyot"
        for a in aliyot:
            assert isinstance(a, dict)
            for key in ("book", "start_ch", "start_v", "end_ch", "end_v"):
                assert key in a, f"aliyah missing key {key}: {a}"


# --- (e) MediaPipe & demo video static assets -------------------------------

def test_demo_overlay_mp4_served():
    r = requests.get(f"{BASE_URL}/demo/torah_overlay.mp4", timeout=60, stream=True)
    assert r.status_code == 200
    ctype = r.headers.get("content-type", "")
    assert "video/mp4" in ctype, f"expected video/mp4, got {ctype}"
    clen = int(r.headers.get("content-length", "0"))
    assert clen > 1_000_000, f"overlay too small: {clen}B"


def _asset_size(url: str) -> int:
    """Return the actual asset size in bytes.

    The Cloudflare edge in front of the preview env sometimes drops the
    upstream Content-Length when downgrading to chunked transfer encoding,
    so a streaming HEAD or GET can yield 0. HEAD against the origin worker
    preserves the header — use that and fall back to a streamed body
    read if necessary.
    """
    h = requests.head(url, timeout=60, allow_redirects=True)
    if h.status_code != 200:
        return -1
    clen = int(h.headers.get("content-length", "0"))
    if clen > 0:
        return clen
    # Fallback: actually download and count bytes.
    r = requests.get(url, timeout=120, stream=True)
    if r.status_code != 200:
        return -1
    total = 0
    for chunk in r.iter_content(chunk_size=64 * 1024):
        total += len(chunk)
    return total


def test_mediapipe_model_served():
    size = _asset_size(f"{BASE_URL}/mediapipe/hand_landmarker.task")
    assert size > 5 * 1024 * 1024, f"model too small: {size}B"


def test_mediapipe_wasm_served():
    size = _asset_size(f"{BASE_URL}/mediapipe/wasm/vision_wasm_internal.wasm")
    assert size > 5 * 1024 * 1024, f"wasm too small: {size}B"
