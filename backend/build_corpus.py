"""
One-shot script to fetch the entire Torah, Nevi'im (all Haftarah portions live here),
and the Five Megillot — all with Ta'amei Hamikra (cantillation marks) — from Sefaria,
and save them to /app/backend/data/torah_corpus.json.

Run this once to bundle the full chant-able corpus with the app so it works offline.
After this file exists, server.py loads from it instead of hitting Sefaria.

Usage:
    cd /app/backend && python build_corpus.py
"""
import json
import sys
import time
from pathlib import Path

import httpx

SEFARIA_BASE = "https://www.sefaria.org/api"

TORAH = [
    ("Genesis", "בראשית"),
    ("Exodus", "שמות"),
    ("Leviticus", "ויקרא"),
    ("Numbers", "במדבר"),
    ("Deuteronomy", "דברים"),
]

# All Prophets (Nevi'im) — every Haftarah portion comes from these books.
NEVIIM = [
    ("Joshua", "יהושע"),
    ("Judges", "שופטים"),
    ("I Samuel", "שמואל א"),
    ("II Samuel", "שמואל ב"),
    ("I Kings", "מלכים א"),
    ("II Kings", "מלכים ב"),
    ("Isaiah", "ישעיהו"),
    ("Jeremiah", "ירמיהו"),
    ("Ezekiel", "יחזקאל"),
    ("Hosea", "הושע"),
    ("Joel", "יואל"),
    ("Amos", "עמוס"),
    ("Obadiah", "עובדיה"),
    ("Jonah", "יונה"),
    ("Micah", "מיכה"),
    ("Nahum", "נחום"),
    ("Habakkuk", "חבקוק"),
    ("Zephaniah", "צפניה"),
    ("Haggai", "חגי"),
    ("Zechariah", "זכריה"),
    ("Malachi", "מלאכי"),
]

# The Five Megillot
MEGILLOT = [
    ("Song of Songs", "שיר השירים"),
    ("Ruth", "רות"),
    ("Lamentations", "איכה"),
    ("Ecclesiastes", "קהלת"),
    ("Esther", "אסתר"),
]

OUT = Path(__file__).parent / "data" / "torah_corpus.json"


def fetch_book(client: httpx.Client, book: str):
    """Fetch full book with cantillation marks via Sefaria v3 API."""
    print(f"Fetching {book}…", flush=True)
    r = client.get(
        f"{SEFARIA_BASE}/v3/texts/{book}",
        params={"version": "hebrew|Tanach with Ta'amei Hamikra"},
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    versions = data.get("versions", [])
    text_blob = None
    for v in versions:
        if isinstance(v.get("text"), list):
            text_blob = v["text"]
            break
    if not text_blob:
        # Some books may need fallback to v1 API
        r = client.get(f"{SEFARIA_BASE}/texts/{book}", timeout=120)
        r.raise_for_status()
        data = r.json()
        text_blob = data.get("he")
        if not isinstance(text_blob, list):
            raise RuntimeError(f"No text found for {book}")
    chapters = []
    for ch in text_blob:
        if isinstance(ch, list):
            chapters.append([t if isinstance(t, str) else "" for t in ch])
    return chapters


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    corpus = {"books": []}
    plan = (
        [(b, h, "torah") for b, h in TORAH]
        + [(b, h, "neviim") for b, h in NEVIIM]
        + [(b, h, "megillot") for b, h in MEGILLOT]
    )
    with httpx.Client() as client:
        for book, hebrew, category in plan:
            chapters = None
            for attempt in range(3):
                try:
                    chapters = fetch_book(client, book)
                    break
                except Exception as e:
                    print(f"  attempt {attempt+1} failed: {e}", flush=True)
                    time.sleep(2)
            if chapters is None:
                print(f"FATAL: could not fetch {book}", file=sys.stderr)
                sys.exit(1)
            verse_count = sum(len(c) for c in chapters)
            print(f"  {book}: {len(chapters)} chapters, {verse_count} verses", flush=True)
            corpus["books"].append({
                "en": book,
                "he": hebrew,
                "category": category,
                "chapters": chapters,
            })
    total = sum(sum(len(c) for c in b["chapters"]) for b in corpus["books"])
    corpus["total_verses"] = total
    corpus["source"] = "Sefaria · Tanach with Ta'amei Hamikra"
    corpus["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, separators=(",", ":"))
    size_mb = OUT.stat().st_size / (1024 * 1024)
    print(f"\nWrote {OUT} ({size_mb:.2f} MB, {total} verses across {len(corpus['books'])} books)")


if __name__ == "__main__":
    main()
