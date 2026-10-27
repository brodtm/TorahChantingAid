"""Backend API tests for scroll-profile / column-map endpoints.

Covers:
  - GET  /api/scroll/profiles        (lists 2 profiles: tikkun_koreim, synthetic_248)
  - GET  /api/scroll/profile/{name}  (metadata; 404 if missing)
  - GET  /api/scroll/{name}/column/{n} (column body; 404 out of range)
  - POST /api/scroll/locate-column   (OCR snippet → column #)
  - POST /api/scroll/line-at         (column + y_fraction → line + verses)
  - Regression on /api/health, /api/torah/locate, /api/torah/lines,
    /api/torah/books, /api/torah/haftarot, /api/sessions, /api/calibration
  - Verifies no MongoDB _id leaks in any JSON response
"""
import os
import re
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Frontend public URL is the source of truth for end-to-end testing.
BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://torah-chant-lens.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

TEAMIM_RE = re.compile(r"[\u0591-\u05C7]")


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _no_objectid(obj):
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leaked: keys={list(obj.keys())}"
        for v in obj.values():
            _no_objectid(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_objectid(v)


# --- Scroll profiles list / meta -------------------------------------------

def test_scroll_profiles_list_two_entries(client):
    r = client.get(f"{API}/scroll/profiles", timeout=30)
    assert r.status_code == 200
    data = r.json()
    _no_objectid(data)
    assert isinstance(data, list)
    assert len(data) == 2
    by_name = {p["name"]: p for p in data}
    assert "tikkun_koreim" in by_name
    assert "synthetic_248" in by_name
    assert by_name["tikkun_koreim"]["column_count"] == 245
    assert by_name["synthetic_248"]["column_count"] == 248
    for p in data:
        assert "title" in p and "tradition" in p and "source" in p


def test_scroll_profile_meta_tikkun(client):
    r = client.get(f"{API}/scroll/profile/tikkun_koreim", timeout=30)
    assert r.status_code == 200
    p = r.json()
    _no_objectid(p)
    assert p["name"] == "tikkun_koreim"
    assert p["column_count"] == 245
    assert p.get("title")


def test_scroll_profile_meta_synthetic(client):
    r = client.get(f"{API}/scroll/profile/synthetic_248", timeout=30)
    assert r.status_code == 200
    p = r.json()
    assert p["name"] == "synthetic_248"
    assert p["column_count"] == 248


def test_scroll_profile_missing_404(client):
    r = client.get(f"{API}/scroll/profile/missing", timeout=30)
    assert r.status_code == 404


# --- Column body retrieval --------------------------------------------------

def test_scroll_get_column_1_tikkun(client):
    r = client.get(f"{API}/scroll/tikkun_koreim/column/1", timeout=30)
    assert r.status_code == 200
    col = r.json()
    _no_objectid(col)
    assert col.get("column") == 1
    assert isinstance(col.get("lines"), list)
    assert len(col["lines"]) > 0
    line0 = col["lines"][0]
    assert "text_plain" in line0
    assert "line" in line0
    assert "verses" in line0


def test_scroll_get_column_zero_404(client):
    r = client.get(f"{API}/scroll/tikkun_koreim/column/0", timeout=30)
    assert r.status_code == 404


def test_scroll_get_column_out_of_range_404(client):
    r = client.get(f"{API}/scroll/tikkun_koreim/column/999", timeout=30)
    assert r.status_code == 404


# --- locate-column ----------------------------------------------------------

def test_locate_column_clean_bereshit_1_1(client):
    r = client.post(f"{API}/scroll/locate-column", json={
        "snippet": "בראשית ברא אלהים את השמים ואת הארץ",
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "expected match for clean Bereshit 1:1 snippet"
    assert d["column"] == 1
    assert d["confidence"] == 1.0
    # 0.25 is the realistic floor for SHORT (~28 char) snippets where many
    # columns share common Torah trigrams (אלהים, השמים, הארץ). Long
    # snippets routinely hit margin > 0.9. See PRD locate_column docstring.
    assert d["margin"] > 0.25, f"margin too low: {d['margin']}"


def test_locate_column_end_of_torah(client):
    r = client.post(f"{API}/scroll/locate-column", json={
        "snippet": "וזאת הברכה אשר ברך משה איש האלהים את בני ישראל לפני מותו",
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d is not None
    assert d["column"] >= 240, f"expected near-end column, got {d['column']}"


def test_locate_column_mangled_ocr_genesis_1_26(client):
    # OCR-mangled Genesis 1:26 area — should still resolve to first 10 columns.
    # Snippet uses a longer prefix so the matcher has enough distinctive
    # trigrams to dominate generic Hebrew-letter background noise.
    r = client.post(f"{API}/scroll/locate-column", json={
        "snippet": "יאמורא לתיב נעשיה אדם בצלבנו כדבותנו וירדו בדגת חים ובעוף השבים ובבחבה ובבל הארץ",
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "Locate-column returned null for mangled OCR snippet"
    assert 1 <= d["column"] <= 10, f"expected col 1-10, got {d['column']}"


def test_locate_column_too_short_returns_null(client):
    r = client.post(f"{API}/scroll/locate-column", json={"snippet": "ABCD"}, timeout=30)
    assert r.status_code == 200
    assert r.json() is None


def test_locate_column_synthetic_profile(client):
    r = client.post(f"{API}/scroll/locate-column", json={
        "snippet": "בראשית ברא אלהים את השמים ואת הארץ",
        "profile": "synthetic_248",
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "locate-column on synthetic_248 returned null"
    assert isinstance(d["column"], int)
    assert 1 <= d["column"] <= 248


# --- line-at ----------------------------------------------------------------

def test_line_at_col1_top_genesis_1_1(client):
    r = client.post(f"{API}/scroll/line-at", json={
        "column": 1, "y_fraction": 0.0,
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["column"] == 1
    assert d["line"] == 1
    assert isinstance(d["verses"], list) and len(d["verses"]) > 0
    # The very first line should reference Genesis 1:1.
    found = any(
        (v.get("book") in ("Genesis", "בראשית")) and v.get("chapter") == 1 and v.get("verse") == 1
        for v in d["verses"]
    )
    assert found, f"Genesis 1:1 not in first line verses: {d['verses']}"


def test_line_at_col1_bottom(client):
    r = client.post(f"{API}/scroll/line-at", json={
        "column": 1, "y_fraction": 1.0,
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["column"] == 1
    assert d["line"] == d["lines_in_column"]
    assert d["lines_in_column"] >= 1


def test_line_at_col245_end_deuteronomy(client):
    r = client.post(f"{API}/scroll/line-at", json={
        "column": 245, "y_fraction": 0.95,
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["column"] == 245
    assert isinstance(d["verses"], list) and len(d["verses"]) > 0
    # Expect Deuteronomy 34:11 or 34:12 to be referenced near the end.
    matched = any(
        (v.get("book") in ("Deuteronomy", "דברים"))
        and v.get("chapter") == 34
        and v.get("verse") in (11, 12)
        for v in d["verses"]
    )
    assert matched, f"Deut 34:11/12 not in last-line verses: {d['verses']}"


def test_line_at_column_out_of_range_404(client):
    r = client.post(f"{API}/scroll/line-at", json={
        "column": 999, "y_fraction": 0.5,
    }, timeout=30)
    assert r.status_code == 404


# --- Regression: pre-existing endpoints still work --------------------------

def test_health_indexed_15887(client):
    r = client.get(f"{API}/health", timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d.get("ok") is True
    assert d.get("indexed_verses") == 15887


def test_torah_locate_still_works(client):
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "בראשית ברא אלהים את השמים ואת הארץ"
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None
    assert d["book"] == "Genesis"
    assert d["chapter"] == 1
    assert d["verse"] == 1


def test_torah_lines_still_works(client):
    r = client.post(f"{API}/torah/lines", json={
        "book": "Genesis", "chapter": 1, "verse": 1, "context": 2
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["active"]["verse"] == 1
    assert TEAMIM_RE.search(d["active"]["he_with_teamim"]) is not None


def test_torah_books_still_works(client):
    r = client.get(f"{API}/torah/books", timeout=30)
    assert r.status_code == 200
    books = r.json()
    assert len(books["torah"]) == 5
    assert len(books["neviim"]) == 21
    assert len(books["megillot"]) == 5


def test_torah_haftarot_still_works(client):
    r = client.get(f"{API}/torah/haftarot", timeout=30)
    assert r.status_code == 200
    h = r.json()
    assert len(h) == 54


def test_sessions_and_calibration_still_work(client):
    r = client.post(f"{API}/sessions", json={"name": "TEST_scroll_regress"}, timeout=30)
    assert r.status_code == 200
    s = r.json()
    _no_objectid(s)
    sid = s["id"]

    payload = {
        "session_id": sid,
        "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
        "target": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}],
    }
    r = client.post(f"{API}/calibration", json=payload, timeout=30)
    assert r.status_code == 200
    r = client.get(f"{API}/calibration/{sid}", timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["session_id"] == sid
