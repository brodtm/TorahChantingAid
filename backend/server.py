"""
Torah Chanting Aid - FastAPI Backend
Provides Torah text from Sefaria, location detection from OCR snippets,
session/calibration persistence, and parsha/aliyah lookup.
"""
import os
import re
import json
import uuid
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
SEFARIA_BASE_URL = os.environ.get("SEFARIA_BASE_URL", "https://www.sefaria.org/api")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("torah-aid")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="Torah Chanting Aid API")
api = APIRouter(prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Torah corpus (in-memory cache, loaded from Sefaria on demand)
# ---------------------------------------------------------------------------

TORAH_BOOKS = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]
NEVIIM_BOOKS = [
    "Joshua", "Judges", "I Samuel", "II Samuel", "I Kings", "II Kings",
    "Isaiah", "Jeremiah", "Ezekiel",
    "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah",
    "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
]
MEGILLOT_BOOKS = ["Song of Songs", "Ruth", "Lamentations", "Ecclesiastes", "Esther"]
ALL_BOOKS = TORAH_BOOKS + NEVIIM_BOOKS + MEGILLOT_BOOKS

HEBREW_BOOK_NAMES = {
    "Genesis": "בראשית", "Exodus": "שמות", "Leviticus": "ויקרא",
    "Numbers": "במדבר", "Deuteronomy": "דברים",
    "Joshua": "יהושע", "Judges": "שופטים",
    "I Samuel": "שמואל א", "II Samuel": "שמואל ב",
    "I Kings": "מלכים א", "II Kings": "מלכים ב",
    "Isaiah": "ישעיהו", "Jeremiah": "ירמיהו", "Ezekiel": "יחזקאל",
    "Hosea": "הושע", "Joel": "יואל", "Amos": "עמוס", "Obadiah": "עובדיה",
    "Jonah": "יונה", "Micah": "מיכה", "Nahum": "נחום", "Habakkuk": "חבקוק",
    "Zephaniah": "צפניה", "Haggai": "חגי", "Zechariah": "זכריה", "Malachi": "מלאכי",
    "Song of Songs": "שיר השירים", "Ruth": "רות", "Lamentations": "איכה",
    "Ecclesiastes": "קהלת", "Esther": "אסתר",
}

BOOK_CATEGORY = {b: "torah" for b in TORAH_BOOKS}
BOOK_CATEGORY.update({b: "neviim" for b in NEVIIM_BOOKS})
BOOK_CATEGORY.update({b: "megillot" for b in MEGILLOT_BOOKS})

# In-memory caches
_text_cache: Dict[str, Dict[str, Any]] = {}        # key: "Book.Chapter" -> sefaria response
_unvocalized_index: List[Dict[str, Any]] = []       # flat verse list w/ stripped text
_index_built = False

NIKUD_TEAMIM_RE = re.compile(r"[\u0591-\u05C7]")  # Hebrew accents + nikud range
NON_HEBREW_RE = re.compile(r"[^\u05D0-\u05EA\s]")  # keep only Hebrew letters + spaces
WHITESPACE_RE = re.compile(r"\s+")


def strip_nikud_teamim(text: str) -> str:
    """Remove all vowel points and cantillation marks. Returns letters only."""
    if not text:
        return ""
    text = NIKUD_TEAMIM_RE.sub("", text)
    text = NON_HEBREW_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


async def fetch_sefaria_chapter(book: str, chapter: int) -> Dict[str, Any]:
    """Fetch a chapter from Sefaria with cantillation marks (Tanach with Ta'amei Hamikra)."""
    cache_key = f"{book}.{chapter}"
    if cache_key in _text_cache:
        return _text_cache[cache_key]

    # Use Sefaria v3 API with the te'amim version
    url = f"{SEFARIA_BASE_URL}/v3/texts/{book}.{chapter}"
    params = {"version": "hebrew|Tanach with Ta'amei Hamikra"}
    async with httpx.AsyncClient(timeout=30.0) as http:
        try:
            r = await http.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning(f"Sefaria v3 failed for {book}.{chapter}: {e}; falling back to v1")
            r = await http.get(f"{SEFARIA_BASE_URL}/texts/{book}.{chapter}")
            r.raise_for_status()
            data = r.json()

    _text_cache[cache_key] = data
    return data


def extract_he_verses(data: Dict[str, Any]) -> List[str]:
    """Extract list of Hebrew verses (with cantillation) from Sefaria response."""
    # v3 API: data["versions"][0]["text"] is list of verses
    if "versions" in data and data["versions"]:
        for v in data["versions"]:
            txt = v.get("text")
            if isinstance(txt, list) and txt:
                return [t if isinstance(t, str) else "" for t in txt]
    # v1 API fallback: data["he"]
    he = data.get("he")
    if isinstance(he, list):
        return [t if isinstance(t, str) else "" for t in he]
    return []


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LocateRequest(BaseModel):
    snippet: str  # Hebrew OCR'd text (likely unvocalized)
    hint_book: Optional[str] = None  # narrow search to a single book
    hint_chapter: Optional[int] = None
    hint_category: Optional[str] = None  # "torah" | "neviim" | "megillot"


class LocationResult(BaseModel):
    book: str
    book_he: str
    category: str  # torah | neviim | megillot
    chapter: int
    verse: int
    confidence: float
    matched_text: str
    parsha: Optional[str] = None  # only set for Torah
    aliyah: Optional[int] = None  # only set for Torah
    haftarah_for: Optional[str] = None  # parsha name if this passage is a haftarah


class LinesRequest(BaseModel):
    book: str
    chapter: int
    verse: int
    context: int = 2  # lines before/after


class LineEntry(BaseModel):
    book: str
    book_he: Optional[str] = None
    category: Optional[str] = None
    chapter: int
    verse: int
    he_with_teamim: str
    he_plain: str


class LinesResponse(BaseModel):
    active: LineEntry
    previous: List[LineEntry]
    next: List[LineEntry]
    parsha: Optional[str] = None
    aliyah: Optional[int] = None
    haftarah_for: Optional[str] = None
    category: Optional[str] = None


class CalibrationPoints(BaseModel):
    session_id: str
    points: List[Dict[str, float]]  # 4 points: tl, tr, br, bl in projector coords
    target: List[Dict[str, float]]  # 4 corresponding points on torah surface
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Untitled Session"
    book: Optional[str] = None
    chapter: Optional[int] = None
    verse: Optional[int] = None
    parsha: Optional[str] = None
    aliyah: Optional[int] = None
    calibration: Optional[Dict[str, Any]] = None
    torah_present: bool = False
    yad_detected: bool = False
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Index building (lazy)
# ---------------------------------------------------------------------------

async def build_index_from_local_file() -> bool:
    """Load the bundled Torah corpus from disk. Returns True on success."""
    corpus_path = ROOT_DIR / "data" / "torah_corpus.json"
    if not corpus_path.exists():
        return False
    try:
        import json as _json
        with open(corpus_path, "r", encoding="utf-8") as f:
            corpus = _json.load(f)
    except Exception as e:
        logger.error(f"Failed to read bundled corpus: {e}")
        return False

    for book_entry in corpus.get("books", []):
        book = book_entry["en"]
        category = book_entry.get("category", "torah")
        chapters = book_entry["chapters"]
        if book not in HEBREW_BOOK_NAMES:
            # Unknown book in bundle — skip rather than crash
            logger.warning(f"Bundled book '{book}' not in HEBREW_BOOK_NAMES; skipping")
            continue
        for ch_idx, chapter_verses in enumerate(chapters, start=1):
            if not isinstance(chapter_verses, list):
                continue
            for v_idx, verse_text in enumerate(chapter_verses, start=1):
                if not isinstance(verse_text, str):
                    continue
                _unvocalized_index.append({
                    "book": book,
                    "book_he": HEBREW_BOOK_NAMES[book],
                    "category": category,
                    "chapter": ch_idx,
                    "verse": v_idx,
                    "he_with_teamim": verse_text,
                    "he_plain": strip_nikud_teamim(verse_text),
                })
            _text_cache[f"{book}.{ch_idx}"] = {"versions": [{"text": chapter_verses}]}
        logger.info(
            f"Loaded {book} [{category}]: {sum(1 for v in _unvocalized_index if v['book']==book)} verses (from bundle)"
        )
    return True


async def build_index_for_book(book: str):
    """Fetch all chapters of a book from Sefaria and add to index. Used only as fallback."""
    # Fetch the whole book using v3 API
    url = f"{SEFARIA_BASE_URL}/v3/texts/{book}"
    params = {"version": "hebrew|Tanach with Ta'amei Hamikra"}
    async with httpx.AsyncClient(timeout=60.0) as http:
        try:
            r = await http.get(url, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning(f"Failed to fetch full book {book}: {e}")
            return

    # v3 text returns nested array: chapters -> verses
    versions = data.get("versions", [])
    text_blob = None
    for v in versions:
        if isinstance(v.get("text"), list):
            text_blob = v["text"]
            break
    if not text_blob:
        return

    for ch_idx, chapter_verses in enumerate(text_blob, start=1):
        if not isinstance(chapter_verses, list):
            continue
        for v_idx, verse_text in enumerate(chapter_verses, start=1):
            if not isinstance(verse_text, str):
                continue
            plain = strip_nikud_teamim(verse_text)
            _unvocalized_index.append({
                "book": book,
                "book_he": HEBREW_BOOK_NAMES[book],
                "category": BOOK_CATEGORY.get(book, "torah"),
                "chapter": ch_idx,
                "verse": v_idx,
                "he_with_teamim": verse_text,
                "he_plain": plain,
            })
        # cache by chapter for line lookups
        _text_cache[f"{book}.{ch_idx}"] = {
            "versions": [{"text": chapter_verses}]
        }
    logger.info(f"Indexed {book}: {sum(1 for v in _unvocalized_index if v['book']==book)} verses")


async def ensure_index():
    global _index_built
    if _index_built:
        return
    # Prefer bundled corpus (offline-first)
    if await build_index_from_local_file():
        _index_built = True
        logger.info(f"Index ready (bundled): {len(_unvocalized_index)} total verses")
        return
    # Fall back to Sefaria if bundle missing (e.g. fresh dev environment)
    logger.warning("Bundled corpus not found; falling back to Sefaria fetch.")
    for b in ALL_BOOKS:
        await build_index_for_book(b)
    _index_built = True
    logger.info(f"Index ready (Sefaria): {len(_unvocalized_index)} total verses")


# ---------------------------------------------------------------------------
# Parsha / Aliyah index (static minimal data; full data could be fetched from Sefaria)
# ---------------------------------------------------------------------------

# Compact parsha boundaries: list of (parsha_he, parsha_en, start_book, start_ch, start_v)
# Source: standard Torah parsha divisions. End is implied by next parsha start.
PARSHIYOT = [
    ("בראשית", "Bereshit", "Genesis", 1, 1),
    ("נח", "Noach", "Genesis", 6, 9),
    ("לך לך", "Lech-Lecha", "Genesis", 12, 1),
    ("וירא", "Vayera", "Genesis", 18, 1),
    ("חיי שרה", "Chayei Sara", "Genesis", 23, 1),
    ("תולדות", "Toldot", "Genesis", 25, 19),
    ("ויצא", "Vayetzei", "Genesis", 28, 10),
    ("וישלח", "Vayishlach", "Genesis", 32, 4),
    ("וישב", "Vayeshev", "Genesis", 37, 1),
    ("מקץ", "Miketz", "Genesis", 41, 1),
    ("ויגש", "Vayigash", "Genesis", 44, 18),
    ("ויחי", "Vayechi", "Genesis", 47, 28),
    ("שמות", "Shemot", "Exodus", 1, 1),
    ("וארא", "Vaera", "Exodus", 6, 2),
    ("בא", "Bo", "Exodus", 10, 1),
    ("בשלח", "Beshalach", "Exodus", 13, 17),
    ("יתרו", "Yitro", "Exodus", 18, 1),
    ("משפטים", "Mishpatim", "Exodus", 21, 1),
    ("תרומה", "Terumah", "Exodus", 25, 1),
    ("תצוה", "Tetzaveh", "Exodus", 27, 20),
    ("כי תשא", "Ki Tisa", "Exodus", 30, 11),
    ("ויקהל", "Vayakhel", "Exodus", 35, 1),
    ("פקודי", "Pekudei", "Exodus", 38, 21),
    ("ויקרא", "Vayikra", "Leviticus", 1, 1),
    ("צו", "Tzav", "Leviticus", 6, 1),
    ("שמיני", "Shemini", "Leviticus", 9, 1),
    ("תזריע", "Tazria", "Leviticus", 12, 1),
    ("מצרע", "Metzora", "Leviticus", 14, 1),
    ("אחרי מות", "Achrei Mot", "Leviticus", 16, 1),
    ("קדשים", "Kedoshim", "Leviticus", 19, 1),
    ("אמר", "Emor", "Leviticus", 21, 1),
    ("בהר", "Behar", "Leviticus", 25, 1),
    ("בחקתי", "Bechukotai", "Leviticus", 26, 3),
    ("במדבר", "Bamidbar", "Numbers", 1, 1),
    ("נשא", "Naso", "Numbers", 4, 21),
    ("בהעלותך", "Beha'alotcha", "Numbers", 8, 1),
    ("שלח", "Shelach", "Numbers", 13, 1),
    ("קרח", "Korach", "Numbers", 16, 1),
    ("חקת", "Chukat", "Numbers", 19, 1),
    ("בלק", "Balak", "Numbers", 22, 2),
    ("פינחס", "Pinchas", "Numbers", 25, 10),
    ("מטות", "Matot", "Numbers", 30, 2),
    ("מסעי", "Masei", "Numbers", 33, 1),
    ("דברים", "Devarim", "Deuteronomy", 1, 1),
    ("ואתחנן", "Vaetchanan", "Deuteronomy", 3, 23),
    ("עקב", "Eikev", "Deuteronomy", 7, 12),
    ("ראה", "Re'eh", "Deuteronomy", 11, 26),
    ("שופטים", "Shoftim", "Deuteronomy", 16, 18),
    ("כי תצא", "Ki Teitzei", "Deuteronomy", 21, 10),
    ("כי תבוא", "Ki Tavo", "Deuteronomy", 26, 1),
    ("נצבים", "Nitzavim", "Deuteronomy", 29, 9),
    ("וילך", "Vayelech", "Deuteronomy", 31, 1),
    ("האזינו", "Ha'azinu", "Deuteronomy", 32, 1),
    ("וזאת הברכה", "V'Zot HaBerachah", "Deuteronomy", 33, 1),
]

BOOK_ORDER = {b: i for i, b in enumerate(TORAH_BOOKS)}


def find_parsha(book: str, chapter: int, verse: int) -> Optional[Dict[str, Any]]:
    """Return the parsha containing the given (book, chapter, verse)."""
    if book not in BOOK_ORDER:
        return None
    target = (BOOK_ORDER[book], chapter, verse)
    current = None
    for he, en, b, c, v in PARSHIYOT:
        start = (BOOK_ORDER[b], c, v)
        if start <= target:
            current = {"he": he, "en": en, "start": {"book": b, "chapter": c, "verse": v}}
        else:
            break
    return current


def estimate_aliyah(book: str, chapter: int, verse: int) -> Optional[int]:
    """Return the 1-7 aliyah index for a given (book, chapter, verse).

    Uses the authoritative Sefaria aliyot table bundled at
    /app/backend/data/aliyot.json (54 parshiyot × 7 aliyot = 378
    boundaries). Falls back to the old verse-count estimator only if the
    table is missing.
    """
    a = _lookup_aliyah_from_table(book, chapter, verse)
    if a is not None:
        return a
    return _estimate_aliyah_legacy(book, chapter, verse)


_aliyot_table = None  # lazy-loaded


def _load_aliyot_table():
    global _aliyot_table
    if _aliyot_table is not None:
        return _aliyot_table
    path = Path(__file__).parent / "data" / "aliyot.json"
    if not path.exists():
        _aliyot_table = []
        return _aliyot_table
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    _aliyot_table = data.get("parshiyot", [])
    return _aliyot_table


def _lookup_aliyah_from_table(book: str, chapter: int, verse: int) -> Optional[int]:
    parshiyot = _load_aliyot_table()
    target = (chapter, verse)
    for p in parshiyot:
        if p.get("book") != book:
            continue
        for idx, a in enumerate(p["aliyot"], start=1):
            start = (a["start_ch"], a["start_v"])
            end = (a["end_ch"], a["end_v"])
            if start <= target <= end:
                return idx
    return None


def _estimate_aliyah_legacy(book: str, chapter: int, verse: int) -> Optional[int]:
    """Old crude estimator — fallback only if aliyot.json is missing."""
    p = find_parsha(book, chapter, verse)
    if not p:
        return None
    # Count verses from parsha start to current
    start = p["start"]
    count = 0
    target_count = 0
    found = False
    for entry in _unvocalized_index:
        if entry["book"] == start["book"] and (
            entry["chapter"] > start["chapter"] or
            (entry["chapter"] == start["chapter"] and entry["verse"] >= start["verse"])
        ):
            count += 1
            if entry["book"] == book and entry["chapter"] == chapter and entry["verse"] == verse:
                target_count = count
                found = True
                break
            # Stop if we've crossed into next parsha
            np = find_parsha(entry["book"], entry["chapter"], entry["verse"])
            if np and np["en"] != p["en"]:
                break
    if not found or count == 0:
        return None
    # Estimate parsha length by remaining iteration
    total = count
    for entry in _unvocalized_index:
        np = find_parsha(entry["book"], entry["chapter"], entry["verse"])
        if np and np["en"] == p["en"]:
            total += 1
    # crude split into 7
    aliyah = min(7, max(1, ((target_count - 1) * 7 // max(total, 1)) + 1))
    return aliyah


# ---------------------------------------------------------------------------
# Haftarot map (Ashkenazi tradition; weekly parsha + a few commonly chanted)
# Each entry: parsha_en -> { he: parsha_he, ref: { book, start_ch, start_v, end_ch, end_v } }
# Refs are not exhaustive (some traditions differ); used only to label a Nevi'im
# location with "haftarah for X" if the user is reading a known portion.
# ---------------------------------------------------------------------------

HAFTAROT = {
    # Bereshit cycle (Ashkenazi)
    "Bereshit":     {"book": "Isaiah",     "start": (42, 5),  "end": (43, 10)},
    "Noach":        {"book": "Isaiah",     "start": (54, 1),  "end": (55, 5)},
    "Lech-Lecha":   {"book": "Isaiah",     "start": (40, 27), "end": (41, 16)},
    "Vayera":       {"book": "II Kings",   "start": (4, 1),   "end": (4, 37)},
    "Chayei Sara":  {"book": "I Kings",    "start": (1, 1),   "end": (1, 31)},
    "Toldot":       {"book": "Malachi",    "start": (1, 1),   "end": (2, 7)},
    "Vayetzei":     {"book": "Hosea",      "start": (12, 13), "end": (14, 10)},
    "Vayishlach":   {"book": "Obadiah",    "start": (1, 1),   "end": (1, 21)},
    "Vayeshev":     {"book": "Amos",       "start": (2, 6),   "end": (3, 8)},
    "Miketz":       {"book": "I Kings",    "start": (3, 15),  "end": (4, 1)},
    "Vayigash":     {"book": "Ezekiel",    "start": (37, 15), "end": (37, 28)},
    "Vayechi":      {"book": "I Kings",    "start": (2, 1),   "end": (2, 12)},
    # Shemot
    "Shemot":       {"book": "Isaiah",     "start": (27, 6),  "end": (28, 13)},
    "Vaera":        {"book": "Ezekiel",    "start": (28, 25), "end": (29, 21)},
    "Bo":           {"book": "Jeremiah",   "start": (46, 13), "end": (46, 28)},
    "Beshalach":    {"book": "Judges",     "start": (4, 4),   "end": (5, 31)},
    "Yitro":        {"book": "Isaiah",     "start": (6, 1),   "end": (7, 6)},
    "Mishpatim":    {"book": "Jeremiah",   "start": (34, 8),  "end": (34, 22)},
    "Terumah":      {"book": "I Kings",    "start": (5, 26),  "end": (6, 13)},
    "Tetzaveh":     {"book": "Ezekiel",    "start": (43, 10), "end": (43, 27)},
    "Ki Tisa":      {"book": "I Kings",    "start": (18, 1),  "end": (18, 39)},
    "Vayakhel":     {"book": "I Kings",    "start": (7, 40),  "end": (7, 50)},
    "Pekudei":      {"book": "I Kings",    "start": (7, 51),  "end": (8, 21)},
    # Vayikra
    "Vayikra":      {"book": "Isaiah",     "start": (43, 21), "end": (44, 23)},
    "Tzav":         {"book": "Jeremiah",   "start": (7, 21),  "end": (8, 3)},
    "Shemini":      {"book": "II Samuel",  "start": (6, 1),   "end": (7, 17)},
    "Tazria":       {"book": "II Kings",   "start": (4, 42),  "end": (5, 19)},
    "Metzora":      {"book": "II Kings",   "start": (7, 3),   "end": (7, 20)},
    "Achrei Mot":   {"book": "Ezekiel",    "start": (22, 1),  "end": (22, 19)},
    "Kedoshim":     {"book": "Amos",       "start": (9, 7),   "end": (9, 15)},
    "Emor":         {"book": "Ezekiel",    "start": (44, 15), "end": (44, 31)},
    "Behar":        {"book": "Jeremiah",   "start": (32, 6),  "end": (32, 27)},
    "Bechukotai":   {"book": "Jeremiah",   "start": (16, 19), "end": (17, 14)},
    # Bamidbar
    "Bamidbar":     {"book": "Hosea",      "start": (2, 1),   "end": (2, 22)},
    "Naso":         {"book": "Judges",     "start": (13, 2),  "end": (13, 25)},
    "Beha'alotcha": {"book": "Zechariah",  "start": (2, 14),  "end": (4, 7)},
    "Shelach":      {"book": "Joshua",     "start": (2, 1),   "end": (2, 24)},
    "Korach":       {"book": "I Samuel",   "start": (11, 14), "end": (12, 22)},
    "Chukat":       {"book": "Judges",     "start": (11, 1),  "end": (11, 33)},
    "Balak":        {"book": "Micah",      "start": (5, 6),   "end": (6, 8)},
    "Pinchas":      {"book": "I Kings",    "start": (18, 46), "end": (19, 21)},
    "Matot":        {"book": "Jeremiah",   "start": (1, 1),   "end": (2, 3)},
    "Masei":        {"book": "Jeremiah",   "start": (2, 4),   "end": (2, 28)},
    # Devarim
    "Devarim":      {"book": "Isaiah",     "start": (1, 1),   "end": (1, 27)},
    "Vaetchanan":   {"book": "Isaiah",     "start": (40, 1),  "end": (40, 26)},
    "Eikev":        {"book": "Isaiah",     "start": (49, 14), "end": (51, 3)},
    "Re'eh":        {"book": "Isaiah",     "start": (54, 11), "end": (55, 5)},
    "Shoftim":      {"book": "Isaiah",     "start": (51, 12), "end": (52, 12)},
    "Ki Teitzei":   {"book": "Isaiah",     "start": (54, 1),  "end": (54, 10)},
    "Ki Tavo":      {"book": "Isaiah",     "start": (60, 1),  "end": (60, 22)},
    "Nitzavim":     {"book": "Isaiah",     "start": (61, 10), "end": (63, 9)},
    "Vayelech":     {"book": "Hosea",      "start": (14, 2),  "end": (14, 10)},
    "Ha'azinu":     {"book": "II Samuel",  "start": (22, 1),  "end": (22, 51)},
    "V'Zot HaBerachah": {"book": "Joshua", "start": (1, 1),   "end": (1, 18)},
}


def find_haftarah_for(book: str, chapter: int, verse: int) -> Optional[str]:
    """Return the parsha name (English) whose haftarah covers (book, ch, v)."""
    for parsha_en, h in HAFTAROT.items():
        if h["book"] != book:
            continue
        sc, sv = h["start"]
        ec, ev = h["end"]
        if (chapter > sc or (chapter == sc and verse >= sv)) and \
           (chapter < ec or (chapter == ec and verse <= ev)):
            return parsha_en
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@api.get("/")
async def root():
    return {"service": "torah-chanting-aid", "status": "ok", "indexed": _index_built}


@api.get("/health")
async def health():
    return {"ok": True, "indexed_verses": len(_unvocalized_index)}


@api.post("/index/build")
async def trigger_index_build():
    await ensure_index()
    return {"ok": True, "verses": len(_unvocalized_index)}


@api.get("/torah/books")
async def get_books():
    """Return all bundled books grouped by category."""
    return {
        "torah": [{"en": b, "he": HEBREW_BOOK_NAMES[b], "category": "torah"} for b in TORAH_BOOKS],
        "neviim": [{"en": b, "he": HEBREW_BOOK_NAMES[b], "category": "neviim"} for b in NEVIIM_BOOKS],
        "megillot": [{"en": b, "he": HEBREW_BOOK_NAMES[b], "category": "megillot"} for b in MEGILLOT_BOOKS],
    }


@api.get("/torah/haftarot")
async def get_haftarot():
    """Return the haftarah-for-parsha mapping (Ashkenazi)."""
    return [
        {
            "parsha_en": pn,
            "book": h["book"],
            "book_he": HEBREW_BOOK_NAMES.get(h["book"]),
            "start": {"chapter": h["start"][0], "verse": h["start"][1]},
            "end": {"chapter": h["end"][0], "verse": h["end"][1]},
        }
        for pn, h in HAFTAROT.items()
    ]


@api.get("/torah/parshiyot")
async def get_parshiyot():
    return [
        {"he": he, "en": en, "book": b, "chapter": c, "verse": v}
        for he, en, b, c, v in PARSHIYOT
    ]


@api.get("/torah/chapter/{book}/{chapter}")
async def get_chapter(book: str, chapter: int):
    if book not in ALL_BOOKS:
        raise HTTPException(400, f"Unknown book: {book}")
    await ensure_index()
    category = BOOK_CATEGORY.get(book, "torah")
    verses = [
        {
            "book": book,
            "category": category,
            "chapter": e["chapter"],
            "verse": e["verse"],
            "he_with_teamim": e["he_with_teamim"],
            "he_plain": e["he_plain"],
        }
        for e in _unvocalized_index
        if e["book"] == book and e["chapter"] == chapter
    ]
    if not verses:
        raise HTTPException(404, f"Chapter not found: {book} {chapter}")
    return {
        "book": book,
        "book_he": HEBREW_BOOK_NAMES[book],
        "category": category,
        "chapter": chapter,
        "verses": verses,
    }


# ---------------------------------------------------------------------------
# Locate helpers (kept module-level so the endpoint stays small & testable)
# ---------------------------------------------------------------------------
#
# Tuning rationale for the magic constants below (calibrated against the
# Tikkun Koreim PDF OCR test in /app/test_reports/tikkun_ocr_report.md):
#
#   _NGRAM_N            = 3   3-grams give the best signal-to-noise on Hebrew
#                             OCR — bi-grams are too noisy, 4-grams break under
#                             the systematic Tesseract substitutions (ה↔ת etc).
#   _MIN_COMPACT_LEN    = 18  Below this we bail out; matching becomes random.
#                             18 chars ≈ 5–6 Hebrew words, the smallest scale
#                             where 3-gram Jaccard discriminates verses.
#   _MIN_INTER_VERSE    = 3   Need at least 3 shared 3-grams in a single verse
#                             for that verse to be a candidate.
#   _MIN_INTER_WINDOW   = 4   Slightly stricter for the 3-verse window pass
#                             since each window has more text to share with.
#   _MIN_SCORE          = 0.18  Final cut-off; below this we return None.
#                             Empirically: real OCR matches score 0.20–1.0,
#                             noise/coincidence rarely exceeds 0.15.

_NGRAM_N = 3
_MIN_COMPACT_LEN = 18
_MIN_INTER_VERSE = 3
_MIN_INTER_WINDOW = 4
_MIN_SCORE = 0.18


def _ngrams(s: str, n: int = _NGRAM_N) -> set:
    """Character n-grams (spaces removed)."""
    if len(s) < n:
        return set()
    return {s[i:i + n] for i in range(0, len(s) - n + 1)}


def _filter_pool(req: "LocateRequest") -> List[dict]:
    pool = _unvocalized_index
    if req.hint_category:
        pool = [e for e in pool if e.get("category") == req.hint_category]
    if req.hint_book:
        pool = [e for e in pool if e["book"] == req.hint_book]
    if req.hint_chapter:
        pool = [e for e in pool if e["chapter"] == req.hint_chapter]
    return pool


def _score_per_verse(pool, snippet_ngrams: set, snippet_words: set):
    """First pass: per-verse 3-gram Jaccard recall + word overlap."""
    best, best_score = None, 0.0
    for entry in pool:
        verse_compact = re.sub(r"\s+", "", entry["he_plain"])
        v_ng = _ngrams(verse_compact)
        if not v_ng:
            continue
        inter = snippet_ngrams & v_ng
        if len(inter) < _MIN_INTER_VERSE:
            continue
        recall = len(inter) / max(len(snippet_ngrams), 1)
        verse_words = set(entry["he_plain"].split())
        word_overlap = (len(snippet_words & verse_words) / max(len(snippet_words), 1)) if snippet_words else 0
        score = 0.85 * recall + 0.15 * word_overlap
        if score > best_score:
            best, best_score = entry, score
    return best, best_score


def _score_sliding_window(pool, snippet_ngrams: set, current_best, current_score):
    """Second pass: 3-verse sliding windows (snippets often span verse boundaries)."""
    by_chapter = {}
    for e in pool:
        by_chapter.setdefault((e["book"], e["chapter"]), []).append(e)
    best, best_score = current_best, current_score
    for verses in by_chapter.values():
        verses.sort(key=lambda e: e["verse"])
        for i in range(len(verses)):
            window = verses[i:i + 3]
            window_compact = re.sub(r"\s+", "", " ".join(e["he_plain"] for e in window))
            w_ng = _ngrams(window_compact)
            if not w_ng:
                continue
            inter = snippet_ngrams & w_ng
            if len(inter) < _MIN_INTER_WINDOW:
                continue
            score = 0.8 * (len(inter) / max(len(snippet_ngrams), 1))
            if score > best_score:
                best_score = score
                best = max(
                    window,
                    key=lambda v: len(snippet_ngrams & _ngrams(re.sub(r"\s+", "", v["he_plain"]))),
                )
    return best, best_score


def _build_location(entry: dict, score: float) -> LocationResult:
    category = entry.get("category", BOOK_CATEGORY.get(entry["book"], "torah"))
    parsha = find_parsha(entry["book"], entry["chapter"], entry["verse"]) if category == "torah" else None
    aliyah = estimate_aliyah(entry["book"], entry["chapter"], entry["verse"]) if category == "torah" else None
    haftarah_for = find_haftarah_for(entry["book"], entry["chapter"], entry["verse"]) if category == "neviim" else None
    return LocationResult(
        book=entry["book"],
        book_he=entry["book_he"],
        category=category,
        chapter=entry["chapter"],
        verse=entry["verse"],
        confidence=round(score, 3),
        matched_text=entry["he_plain"][:140],
        parsha=parsha["he"] if parsha else None,
        aliyah=aliyah,
        haftarah_for=haftarah_for,
    )


@api.post("/torah/locate", response_model=Optional[LocationResult])
async def locate(req: LocateRequest):
    """Locate an OCR'd Hebrew snippet in the bundled corpus.
    Strategy: 3-gram fuzzy match (per verse + sliding 3-verse windows).
    Returns None if no match clears the minimum score."""
    await ensure_index()
    snippet = strip_nikud_teamim(req.snippet)
    if len(snippet) < 4:
        raise HTTPException(400, "Snippet too short")

    s_compact = re.sub(r"\s+", "", snippet)
    if len(s_compact) < _MIN_COMPACT_LEN:
        return None  # too noisy / short — would yield random hits

    snippet_ngrams = _ngrams(s_compact)
    if not snippet_ngrams:
        raise HTTPException(400, "Snippet too short for matching")

    snippet_words = {w for w in snippet.split() if len(w) >= 2}
    pool = _filter_pool(req)

    best, score = _score_per_verse(pool, snippet_ngrams, snippet_words)
    best, score = _score_sliding_window(pool, snippet_ngrams, best, score)

    if not best or score < _MIN_SCORE:
        return None
    return _build_location(best, score)


@api.post("/torah/lines", response_model=LinesResponse)
async def get_lines(req: LinesRequest):
    """Get active line + N previous + N next, with cantillation."""
    await ensure_index()
    # constrain prev/next to the same book to avoid bleeding across books
    same_book_idxs = [i for i, e in enumerate(_unvocalized_index) if e["book"] == req.book]
    idx = -1
    for i in same_book_idxs:
        e = _unvocalized_index[i]
        if e["chapter"] == req.chapter and e["verse"] == req.verse:
            idx = i
            break
    if idx == -1:
        raise HTTPException(404, "Verse not found")

    def to_entry(e):
        return LineEntry(
            book=e["book"], book_he=e.get("book_he"),
            category=e.get("category"),
            chapter=e["chapter"], verse=e["verse"],
            he_with_teamim=e["he_with_teamim"], he_plain=e["he_plain"],
        )

    pos_in_book = same_book_idxs.index(idx)
    prev_book_idxs = same_book_idxs[max(0, pos_in_book - req.context):pos_in_book]
    next_book_idxs = same_book_idxs[pos_in_book + 1:pos_in_book + 1 + req.context]
    active = to_entry(_unvocalized_index[idx])
    prev = [to_entry(_unvocalized_index[i]) for i in prev_book_idxs]
    nxt = [to_entry(_unvocalized_index[i]) for i in next_book_idxs]

    category = BOOK_CATEGORY.get(req.book, "torah")
    parsha = find_parsha(req.book, req.chapter, req.verse) if category == "torah" else None
    aliyah = estimate_aliyah(req.book, req.chapter, req.verse) if category == "torah" else None
    haftarah_for = find_haftarah_for(req.book, req.chapter, req.verse) if category == "neviim" else None
    return LinesResponse(
        active=active, previous=prev, next=nxt,
        parsha=parsha["he"] if parsha else None,
        aliyah=aliyah,
        haftarah_for=haftarah_for,
        category=category,
    )


# ---------------------------------------------------------------------------
# Sessions & calibration
# ---------------------------------------------------------------------------

@api.post("/sessions", response_model=SessionState)
async def create_session(payload: Dict[str, Any] = Body(default={})):
    s = SessionState(name=payload.get("name", "Session"))
    doc = s.model_dump()
    await db.sessions.insert_one(doc)
    return s


@api.get("/sessions/{session_id}", response_model=SessionState)
async def get_session(session_id: str):
    doc = await db.sessions.find_one({"id": session_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Session not found")
    return SessionState(**doc)


@api.patch("/sessions/{session_id}", response_model=SessionState)
async def update_session(session_id: str, payload: Dict[str, Any] = Body(...)):
    payload["last_seen_at"] = datetime.now(timezone.utc)
    await db.sessions.update_one({"id": session_id}, {"$set": payload})
    doc = await db.sessions.find_one({"id": session_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Session not found")
    return SessionState(**doc)


@api.post("/calibration")
async def save_calibration(payload: CalibrationPoints):
    doc = payload.model_dump()
    await db.calibrations.update_one(
        {"session_id": payload.session_id},
        {"$set": doc},
        upsert=True,
    )
    await db.sessions.update_one(
        {"id": payload.session_id},
        {"$set": {"calibration": {"points": payload.points, "target": payload.target}}},
    )
    return {"ok": True}


@api.get("/calibration/{session_id}")
async def get_calibration(session_id: str):
    doc = await db.calibrations.find_one({"session_id": session_id}, {"_id": 0})
    return doc or {}


# ---------------------------------------------------------------------------
# Status endpoints (legacy starter-style)
# ---------------------------------------------------------------------------

@api.post("/status", response_model=StatusCheck)
async def create_status(input: Dict[str, Any] = Body(...)):
    obj = StatusCheck(client_name=input.get("client_name", "anon"))
    await db.status_checks.insert_one(obj.model_dump())
    return obj


@api.get("/status", response_model=List[StatusCheck])
async def list_status():
    docs = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    return [StatusCheck(**d) for d in docs]


# ---------------------------------------------------------------------------
# Scroll-profile endpoints (column-map approach) — see scroll_routes.py
# ---------------------------------------------------------------------------

from scroll_routes import register as register_scroll_routes  # noqa: E402

register_scroll_routes(api)


app.include_router(api)


@app.on_event("startup")
async def on_start():
    logger.info("Backend starting up. Loading bundled Torah corpus…")
    try:
        await ensure_index()
    except Exception as e:
        logger.warning(f"Initial index load failed (will retry on first request): {e}")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
