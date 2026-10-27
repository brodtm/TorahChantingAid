"""
Fetch Sefaria's authoritative aliyot table for all 5 books of the Torah.

Sefaria publishes aliyot boundaries via /api/index/<book>.alts.Parasha.nodes.
Each node has 7 aliyot refs (e.g. "Genesis 1:1-2:3"). We parse these into
a flat lookup keyed by Hebrew + English parsha name, write a JSON bundle
to /app/backend/data/aliyot.json so the live app stays 100 % offline.

Run once at build time. The output is < 100 KB.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "data" / "aliyot.json"
TORAH_BOOKS = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]
SEFARIA = "https://www.sefaria.org/api/index/{book}"

REF_RE = re.compile(r"^(.+?)\s+(\d+):(\d+)(?:[-\u2013\u2014](?:(\d+):)?(\d+))?$")


def parse_ref(ref: str):
    """'Genesis 1:1-2:3' → (book, start_ch, start_v, end_ch, end_v)
       Accepts ASCII '-' as well as Unicode en-dash and em-dash.
    """
    # Normalise all dash variants to plain hyphen first
    ref = ref.replace("\u2013", "-").replace("\u2014", "-").strip()
    m = REF_RE.match(ref)
    if not m:
        raise ValueError(f"Cannot parse ref: {ref!r}")
    book, sc, sv, ec, ev = m.groups()
    sc, sv, ev = int(sc), int(sv), int(ev)
    ec = int(ec) if ec is not None else sc
    return {"book": book, "start_ch": sc, "start_v": sv,
            "end_ch": ec, "end_v": ev}


def fetch_book(book: str):
    url = SEFARIA.format(book=book)
    print(f"  GET {url}")
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)
    alts = data.get("alts", {}).get("Parasha", {})
    nodes = alts.get("nodes", [])
    out = []
    for n in nodes:
        title_en = (n.get("title") or "").strip()
        title_he = (n.get("heTitle") or "").strip()
        refs = n.get("refs") or []
        if len(refs) != 7:
            print(f"    WARN {book} parsha {title_en!r}: {len(refs)} aliyot (expected 7)")
        aliyot = [parse_ref(r) for r in refs]
        out.append({
            "en": title_en,
            "he": title_he,
            "whole_ref": n.get("wholeRef"),
            "aliyot": aliyot,
        })
    return out


def main():
    bundle = {"parshiyot": []}
    for book in TORAH_BOOKS:
        print(f"Fetching {book}…")
        try:
            parshiyot = fetch_book(book)
        except Exception as e:
            print(f"  FAIL: {e}", file=sys.stderr)
            sys.exit(1)
        for p in parshiyot:
            p["book"] = book
            bundle["parshiyot"].append(p)
    total = len(bundle["parshiyot"])
    aliyot_total = sum(len(p["aliyot"]) for p in bundle["parshiyot"])
    print(f"\n✅ Fetched {total} parshiyot, {aliyot_total} aliyot boundaries")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = OUT.stat().st_size / 1024
    print(f"✅ Wrote {OUT} ({size_kb:.1f} KB)")

    # Sanity print
    sample = bundle["parshiyot"][:3]
    for p in sample:
        print(f"\n  {p['book']} · {p['en']} ({p['he']}) — {p['whole_ref']}")
        for i, a in enumerate(p["aliyot"], start=1):
            print(f"    aliyah {i}: {a['book']} "
                  f"{a['start_ch']}:{a['start_v']}–{a['end_ch']}:{a['end_v']}")


if __name__ == "__main__":
    main()
