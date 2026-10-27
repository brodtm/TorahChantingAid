"""Backend API tests for Torah Chanting Aid (Tanakh-expanded corpus).

Covers:
  - /api/health (15887 verses)
  - /api/torah/books grouped by category (torah/neviim/megillot)
  - /api/torah/haftarot (54 mappings)
  - /api/torah/chapter/{book}/{ch} for Torah, Nevi'im, Megillot + 400 unknown
  - /api/torah/locate (snippets across categories, hint_category, haftarah_for)
  - /api/torah/lines for each category, prev/next stays in same book
  - Sessions CRUD + calibration (no _id leakage)
  - CORS
"""
import os
import re
import pytest
import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://59d09d1e-ef84-4b94-83f1-fa490e9b420c.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

TEAMIM_RE = re.compile(r"[\u0591-\u05C7]")


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session", autouse=True)
def ensure_index(client):
    r = client.post(f"{API}/index/build", timeout=300)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True
    # Bundle covers Torah + Nevi'im + Megillot ~= 15887 verses
    assert data.get("verses", 0) >= 15000


def _no_objectid(obj):
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leaked: {obj}"
        for v in obj.values():
            _no_objectid(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_objectid(v)


# --- Health & meta -----------------------------------------------------------

def test_health_indexed_15887(client):
    r = client.get(f"{API}/health", timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d.get("ok") is True
    assert d.get("indexed_verses") == 15887, f"expected 15887, got {d.get('indexed_verses')}"


# --- Books grouped by category ----------------------------------------------

def test_books_grouped_by_category(client):
    r = client.get(f"{API}/torah/books", timeout=30)
    assert r.status_code == 200
    books = r.json()
    _no_objectid(books)
    assert set(books.keys()) >= {"torah", "neviim", "megillot"}
    assert len(books["torah"]) == 5
    assert len(books["neviim"]) == 21
    assert len(books["megillot"]) == 5
    # each entry has en/he/category
    for cat, items in books.items():
        for entry in items:
            assert "en" in entry and "he" in entry and "category" in entry
            assert entry["category"] == cat
    torah_en = [b["en"] for b in books["torah"]]
    assert torah_en == ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]
    megillot_en = {b["en"] for b in books["megillot"]}
    assert megillot_en == {"Song of Songs", "Ruth", "Lamentations", "Ecclesiastes", "Esther"}
    # spot check Hebrew names
    he_map = {b["en"]: b["he"] for b in books["torah"] + books["neviim"] + books["megillot"]}
    assert he_map["Genesis"] == "בראשית"
    assert he_map["Esther"] == "אסתר"
    assert he_map["Judges"] == "שופטים"


# --- Haftarot ---------------------------------------------------------------

def test_haftarot_54_mappings(client):
    r = client.get(f"{API}/torah/haftarot", timeout=30)
    assert r.status_code == 200
    haftarot = r.json()
    _no_objectid(haftarot)
    assert isinstance(haftarot, list)
    assert len(haftarot) == 54
    sample = haftarot[0]
    assert "parsha_en" in sample
    assert "book" in sample
    assert "start" in sample and "chapter" in sample["start"] and "verse" in sample["start"]
    assert "end" in sample and "chapter" in sample["end"] and "verse" in sample["end"]
    parshas = {h["parsha_en"] for h in haftarot}
    assert "Beshalach" in parshas
    beshalach = next(h for h in haftarot if h["parsha_en"] == "Beshalach")
    assert beshalach["book"] == "Judges"
    assert beshalach["start"] == {"chapter": 4, "verse": 4}
    assert beshalach["end"] == {"chapter": 5, "verse": 31}


# --- Parshiyot --------------------------------------------------------------

def test_parshiyot(client):
    r = client.get(f"{API}/torah/parshiyot", timeout=30)
    assert r.status_code == 200
    p = r.json()
    assert len(p) == 54
    assert p[0]["en"] == "Bereshit"


# --- Chapter retrieval per category -----------------------------------------

def test_chapter_genesis_1_torah(client):
    r = client.get(f"{API}/torah/chapter/Genesis/1", timeout=60)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["book"] == "Genesis"
    assert d["category"] == "torah"
    assert d["book_he"] == "בראשית"
    assert len(d["verses"]) >= 31
    assert TEAMIM_RE.search(d["verses"][0]["he_with_teamim"]) is not None
    assert TEAMIM_RE.search(d["verses"][0]["he_plain"]) is None
    assert d["verses"][0]["category"] == "torah"


def test_chapter_judges_5_neviim(client):
    r = client.get(f"{API}/torah/chapter/Judges/5", timeout=60)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["book"] == "Judges"
    assert d["category"] == "neviim"
    assert d["book_he"] == "שופטים"
    assert len(d["verses"]) >= 30  # Judges 5 has 31 verses
    assert TEAMIM_RE.search(d["verses"][0]["he_with_teamim"]) is not None
    for v in d["verses"]:
        assert v["category"] == "neviim"


def test_chapter_esther_3_megillot(client):
    r = client.get(f"{API}/torah/chapter/Esther/3", timeout=60)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["book"] == "Esther"
    assert d["category"] == "megillot"
    assert d["book_he"] == "אסתר"
    assert len(d["verses"]) >= 13
    for v in d["verses"]:
        assert v["category"] == "megillot"


def test_chapter_joshua_1_neviim(client):
    r = client.get(f"{API}/torah/chapter/Joshua/1", timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d["book"] == "Joshua"
    assert d["category"] == "neviim"
    assert len(d["verses"]) >= 18


def test_chapter_unknown_book_400(client):
    r = client.get(f"{API}/torah/chapter/UnknownBook/1", timeout=30)
    assert r.status_code == 400


def test_chapter_psalms_400(client):
    # Psalms is not in the bundled set
    r = client.get(f"{API}/torah/chapter/Psalms/1", timeout=30)
    assert r.status_code == 400


# --- Locate -----------------------------------------------------------------

def test_locate_genesis_1_1_torah(client):
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "בראשית ברא אלהים את השמים ואת הארץ"
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None
    assert d["book"] == "Genesis"
    assert d["category"] == "torah"
    assert d["chapter"] == 1
    assert d["verse"] == 1
    assert d["parsha"] == "בראשית"
    assert d["aliyah"] == 1
    assert d["haftarah_for"] is None


def test_locate_esther_megillot(client):
    # Esther 3:1 (unvocalized): "אחר הדברים האלה גדל המלך אחשורוש את המן"
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "אחר הדברים האלה גדל המלך אחשורוש את המן בן המדתא"
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "Locate returned null for Esther snippet"
    assert d["book"] == "Esther"
    assert d["category"] == "megillot"
    assert d["parsha"] is None
    assert d["aliyah"] is None
    assert d["haftarah_for"] is None


def test_locate_judges_song_of_deborah_haftarah(client):
    # Judges 5 — Song of Deborah, also haftarah for Beshalach
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "ותשר דבורה וברק בן אבינעם ביום ההוא לאמר"
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "Locate returned null for Judges snippet"
    assert d["book"] == "Judges"
    assert d["category"] == "neviim"
    assert d["haftarah_for"] == "Beshalach"
    assert d["parsha"] is None
    assert d["aliyah"] is None


def test_locate_hint_category_torah(client):
    # Use a snippet that exists in Torah; restrict to torah only
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "ואלה שמות בני ישראל הבאים מצרימה",
        "hint_category": "torah",
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None
    assert d["category"] == "torah"
    assert d["book"] in {"Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"}


def test_locate_hint_category_neviim(client):
    # Snippet from Joshua 1:1 area — restrict to neviim
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "ויהי אחרי מות משה עבד יהוה ויאמר יהוה אל יהושע",
        "hint_category": "neviim",
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None
    assert d["category"] == "neviim"


def test_locate_too_short_400(client):
    r = client.post(f"{API}/torah/locate", json={"snippet": "אב"}, timeout=30)
    assert r.status_code == 400


def test_locate_compact_below_min_returns_null(client):
    # Snippet >= 4 chars (passes first guard) but compact length < 18 — early exit returns null
    r = client.post(f"{API}/torah/locate", json={"snippet": "ויאמר אלהים"}, timeout=30)
    assert r.status_code == 200
    assert r.json() is None


def test_locate_mangled_ocr_genesis_1_26(client):
    # OCR-mangled snippet from Genesis 1:26 — must still resolve via 3-gram fuzzy
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "יאמור אלתיב נעשיה אדם בצלבנו בדמותנווורדו"
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "Locate returned null for mangled OCR Genesis 1:26 snippet"
    assert d["book"] == "Genesis"
    assert d["chapter"] == 1
    assert d["verse"] == 26
    assert d["category"] == "torah"


def test_locate_hint_book_restricts_pool(client):
    # Generic "ויהי" snippet — without hint could hit anywhere; with hint_book=Esther must stay there
    r = client.post(f"{API}/torah/locate", json={
        "snippet": "ויהי בימי אחשורוש הוא אחשורוש המלך מהדו ועד כוש",
        "hint_book": "Esther",
    }, timeout=60)
    assert r.status_code == 200
    d = r.json()
    assert d is not None
    assert d["book"] == "Esther"
    assert d["category"] == "megillot"


# --- Lines per category -----------------------------------------------------

def test_lines_genesis_1_1_torah(client):
    r = client.post(f"{API}/torah/lines", json={
        "book": "Genesis", "chapter": 1, "verse": 1, "context": 2
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["category"] == "torah"
    assert d["active"]["verse"] == 1
    assert d["active"]["category"] == "torah"
    assert d["parsha"] == "בראשית"
    assert d["aliyah"] == 1
    assert d["haftarah_for"] is None
    # Genesis 1:1 has no previous in same book
    assert d["previous"] == []
    assert len(d["next"]) == 2
    # All next stays in Genesis
    for ln in d["next"]:
        assert ln["book"] == "Genesis"


def test_lines_genesis_1_5_active_prev_next_teamim(client):
    r = client.post(f"{API}/torah/lines", json={
        "book": "Genesis", "chapter": 1, "verse": 5, "context": 2
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["category"] == "torah"
    assert d["active"]["book"] == "Genesis"
    assert d["active"]["chapter"] == 1
    assert d["active"]["verse"] == 5
    # te'amim (cantillation) Unicode U+0591..U+05C7 must be present on active text
    assert TEAMIM_RE.search(d["active"]["he_with_teamim"]) is not None
    # 2 previous and 2 next, all in Genesis ch 1
    assert len(d["previous"]) == 2
    assert len(d["next"]) == 2
    for ln in d["previous"] + d["next"]:
        assert ln["book"] == "Genesis"
        assert ln["chapter"] == 1
        assert TEAMIM_RE.search(ln["he_with_teamim"]) is not None
    # Ordering: previous verses 3,4 and next verses 6,7
    assert [v["verse"] for v in d["previous"]] == [3, 4]
    assert [v["verse"] for v in d["next"]] == [6, 7]


def test_lines_judges_5_1_haftarah(client):
    r = client.post(f"{API}/torah/lines", json={
        "book": "Judges", "chapter": 5, "verse": 1, "context": 2
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["category"] == "neviim"
    assert d["haftarah_for"] == "Beshalach"
    assert d["parsha"] is None
    assert d["aliyah"] is None
    assert d["active"]["book"] == "Judges"
    assert d["active"]["category"] == "neviim"
    assert TEAMIM_RE.search(d["active"]["he_with_teamim"])
    # all prev/next must be in Judges
    for ln in d["previous"] + d["next"]:
        assert ln["book"] == "Judges"


def test_lines_esther_1_1_no_bleed(client):
    # Esther 1:1 prev should be empty (not bleed into Lamentations or any other book)
    r = client.post(f"{API}/torah/lines", json={
        "book": "Esther", "chapter": 1, "verse": 1, "context": 3
    }, timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["category"] == "megillot"
    assert d["parsha"] is None
    assert d["aliyah"] is None
    assert d["haftarah_for"] is None
    assert d["active"]["book"] == "Esther"
    assert d["previous"] == [], f"Esther 1:1 should have no prev, got {d['previous']}"
    for ln in d["next"]:
        assert ln["book"] == "Esther", f"next bled into {ln['book']}"


def test_lines_not_found_404(client):
    r = client.post(f"{API}/torah/lines", json={
        "book": "Genesis", "chapter": 999, "verse": 999, "context": 2
    }, timeout=30)
    assert r.status_code == 404


# --- Sessions ---------------------------------------------------------------

def test_session_crud_no_objectid(client):
    r = client.post(f"{API}/sessions", json={"name": "TEST_session"}, timeout=30)
    assert r.status_code == 200
    s = r.json()
    _no_objectid(s)
    assert s["name"] == "TEST_session"
    sid = s["id"]
    assert len(sid) >= 32

    r = client.get(f"{API}/sessions/{sid}", timeout=30)
    assert r.status_code == 200
    _no_objectid(r.json())

    r = client.patch(f"{API}/sessions/{sid}", json={"book": "Esther", "chapter": 1, "verse": 1}, timeout=30)
    assert r.status_code == 200
    u = r.json()
    _no_objectid(u)
    assert u["book"] == "Esther"


def test_session_get_404(client):
    r = client.get(f"{API}/sessions/nonexistent-id-xyz", timeout=30)
    assert r.status_code == 404


# --- Calibration ------------------------------------------------------------

def test_calibration_save_and_fetch(client):
    r = client.post(f"{API}/sessions", json={"name": "TEST_calib"}, timeout=30)
    sid = r.json()["id"]
    payload = {
        "session_id": sid,
        "points": [{"x": 0, "y": 0}, {"x": 1920, "y": 0}, {"x": 1920, "y": 1080}, {"x": 0, "y": 1080}],
        "target": [{"x": 100, "y": 100}, {"x": 1820, "y": 100}, {"x": 1820, "y": 980}, {"x": 100, "y": 980}],
    }
    r = client.post(f"{API}/calibration", json=payload, timeout=30)
    assert r.status_code == 200
    assert r.json().get("ok") is True

    r = client.get(f"{API}/calibration/{sid}", timeout=30)
    assert r.status_code == 200
    d = r.json()
    _no_objectid(d)
    assert d["session_id"] == sid
    assert len(d["points"]) == 4


# --- CORS -------------------------------------------------------------------

def test_cors_headers(client):
    r = client.get(f"{API}/health", headers={"Origin": "https://example.com"}, timeout=30)
    assert r.status_code == 200
    aco = r.headers.get("access-control-allow-origin")
    assert aco in ("*", "https://example.com")
