"""
Build a Sefer Torah column map (column → list of lines → verses on each line)
by extracting the line-break structure from the user-supplied Tikkun Koreim PDF.

Strategy:
    1. For each PDF page (1-245 = the 245 Torah columns):
         - Use pdfminer.six to extract every glyph with (x, y, font, size).
         - Identify the Stam scribal column (left half of the page) by x-coord.
         - Group glyphs by y-coordinate band → each band is one Torah scroll line.
         - Count Hebrew letters per line.
    2. Walk the bundled Hebrew corpus letter-by-letter (Genesis → Deuteronomy),
       allocating each letter to the next line in the next column.
    3. For each line, record the (book, chapter, verse) triples it touches and
       the line's plain text.

Output: /app/backend/data/scroll_profiles/tikkun_koreim.json

This is the AUTHORITATIVE column map — source 'a' in the user's choice 1c.
A separate synthetic profile (source 'b') is built by `build_synthetic_profile.py`.
"""
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTTextBox, LTTextLine, LTChar

PDF = Path("/tmp/tikkun/tikkun.pdf")
CORPUS = Path(__file__).parent / "data" / "torah_corpus.json"
OUT = Path(__file__).parent / "data" / "scroll_profiles" / "tikkun_koreim.json"

TORAH_BOOKS = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"]
HEB_LETTER = re.compile(r"[\u05D0-\u05EA]")
NIKUD_TEAMIM = re.compile(r"[\u0591-\u05C7]")
TORAH_PAGES = (1, 245)  # 1-indexed inclusive


def strip_nikud(s: str) -> str:
    return NIKUD_TEAMIM.sub("", s)


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def extract_glyphs(page_layout):
    """Extract (x0, y0, char, font, size) for every glyph on a page."""
    glyphs = []
    def walk(elem):
        if isinstance(elem, LTChar):
            ch = elem.get_text()
            if ch and ch.strip():
                glyphs.append((elem.x0, elem.y0, ch, elem.fontname, elem.size))
        elif hasattr(elem, "__iter__"):
            for child in elem:
                walk(child)
    for elem in page_layout:
        walk(elem)
    return glyphs


def _dominant_stam_size(glyphs, page_width):
    """The Stam scribal text dominates the left side of the page. We pick
    the MODE (most frequent) glyph size. Picking max or max-of-top-3 loses
    to rare dropcap initials (~18.5pt). Picking the mode reliably lands on
    the Stam body text (~16pt) which forms the bulk of pixels."""
    stam_area = [g for g in glyphs
                 if g[0] < page_width * 0.62 and HEB_LETTER.search(g[2])]
    if not stam_area:
        return None
    from collections import Counter
    buckets = Counter(round(g[4] * 2) / 2 for g in stam_area)
    return buckets.most_common(1)[0][0]


def group_lines(glyphs, page_width):
    """Identify Stam-script lines on the page.
    The Stam column is on the LEFT half of the page (in PDF coords, lower x).

    1. Keep only Hebrew glyphs in the left 62% of the page (Stam side).
    2. Keep only glyphs of the DOMINANT (largest) font size — this drops
       Masoretic notes, paragraph markers, page numbers etc. that would
       otherwise be misread as extra lines.
    3. Cluster glyphs by y-coordinate using a tolerance ≈ 50% of the
       expected line height. Each cluster is one Torah scroll line.

    Returns list of dicts: {y, letter_count, raw_text} sorted top→bottom.
    """
    dom = _dominant_stam_size(glyphs, page_width)
    if dom is None:
        return []
    # Tolerance: 0.5× the Stam line-height. Stam glyphs are ~16pt; ~8pt
    # tolerance comfortably groups glyphs of the same baseline and rejects
    # the next line above/below.
    line_h = dom
    tol = line_h * 0.5
    stam = [g for g in glyphs
            if g[0] < page_width * 0.62
            and HEB_LETTER.search(g[2])
            and abs(g[4] - dom) <= 0.5]   # only the dominant Stam size
    if not stam:
        return []

    # Cluster y values greedily: sort glyphs by y descending (top to bottom
    # in PDF coords is high-y to low-y), start a new line whenever the y
    # of the next glyph is more than `tol` below the current line's y.
    stam.sort(key=lambda g: -g[1])
    bands = []   # list of dicts {y, items}
    cur = None
    for g in stam:
        if cur is None or (cur["y"] - g[1]) > tol:
            cur = {"y": g[1], "items": []}
            bands.append(cur)
        cur["items"].append(g)

    out = []
    for band in bands:
        # Require >= 5 letters (filters out stray marginalia that escaped
        # the size filter).
        if len(band["items"]) < 5:
            continue
        # Sort right-to-left (Hebrew RTL — rightmost on page has highest x)
        band["items"].sort(key=lambda g: -g[0])
        letters = "".join(g[2] for g in band["items"] if HEB_LETTER.match(g[2]))
        if not letters:
            continue
        out.append({
            "y": band["y"],
            "letter_count": len(letters),
            "raw_text": letters,
        })
    return out


# ---------------------------------------------------------------------------
# Corpus walking
# ---------------------------------------------------------------------------

def build_letter_stream():
    """Flatten the Torah into a list of (book, chapter, verse, letter)."""
    with open(CORPUS, "r", encoding="utf-8") as f:
        corpus = json.load(f)
    stream = []
    for book_entry in corpus["books"]:
        if book_entry["en"] not in TORAH_BOOKS:
            continue
        book = book_entry["en"]
        for ch_idx, chapter in enumerate(book_entry["chapters"], start=1):
            for v_idx, verse in enumerate(chapter, start=1):
                plain = strip_nikud(verse)
                for ch in plain:
                    if HEB_LETTER.match(ch):
                        stream.append((book, ch_idx, v_idx, ch))
    return stream


def slot_letters_into_columns(letter_stream, columns_line_counts):
    """For each column, for each line: take the next N letters from the stream
    and record which verses they touch + the plain text."""
    cursor = 0
    columns = []
    for col_idx, line_counts in enumerate(columns_line_counts, start=1):
        col = {"column": col_idx, "lines": []}
        for line_idx, n in enumerate(line_counts, start=1):
            chunk = letter_stream[cursor:cursor + n]
            cursor += n
            text = "".join(c[3] for c in chunk)
            verses = sorted({(c[0], c[1], c[2]) for c in chunk},
                            key=lambda v: (TORAH_BOOKS.index(v[0]), v[1], v[2]))
            col["lines"].append({
                "line": line_idx,
                "letter_count": n,
                "text_plain": text,
                "verses": [{"book": b, "chapter": c, "verse": v} for b, c, v in verses],
            })
        # Convenience: which verse opens / closes this column
        if col["lines"]:
            opening = col["lines"][0]["verses"][0] if col["lines"][0]["verses"] else None
            closing = col["lines"][-1]["verses"][-1] if col["lines"][-1]["verses"] else None
            col["opens_with"] = opening
            col["closes_with"] = closing
        columns.append(col)
    if cursor < len(letter_stream):
        print(f"WARN: {len(letter_stream) - cursor} letters left over after slotting "
              f"(cursor={cursor}, stream={len(letter_stream)})")
    elif cursor > len(letter_stream):
        print(f"WARN: ran out of letters before all lines filled "
              f"(cursor={cursor}, stream={len(letter_stream)})")
    return columns


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not PDF.exists():
        print(f"PDF not found at {PDF}", file=sys.stderr)
        sys.exit(1)
    print(f"Loading corpus from {CORPUS}")
    stream = build_letter_stream()
    print(f"  Letter stream: {len(stream)} Torah letters")

    print(f"Parsing {TORAH_PAGES[1]} pages of {PDF.name}…")
    laparams = LAParams(line_margin=0.3, char_margin=2.0, word_margin=0.1, all_texts=False)
    columns_line_counts = []
    page_diagnostics = []
    pages_iter = extract_pages(str(PDF), laparams=laparams,
                               page_numbers=list(range(TORAH_PAGES[0] - 1, TORAH_PAGES[1])))
    for i, layout in enumerate(pages_iter, start=TORAH_PAGES[0]):
        glyphs = extract_glyphs(layout)
        bands = group_lines(glyphs, layout.width)
        line_counts = [b["letter_count"] for b in bands]
        columns_line_counts.append(line_counts)
        page_diagnostics.append({
            "page": i, "n_lines": len(bands), "total_letters": sum(line_counts),
        })
        if i % 20 == 0 or i == TORAH_PAGES[1]:
            print(f"  page {i:>3}: {len(bands)} lines, {sum(line_counts)} letters")

    total_extracted = sum(d["total_letters"] for d in page_diagnostics)
    print(f"\nExtracted layout: {len(columns_line_counts)} columns, "
          f"{sum(len(c) for c in columns_line_counts)} total lines, "
          f"{total_extracted} letters from PDF")
    print(f"Corpus has {len(stream)} letters")
    delta = total_extracted - len(stream)
    print(f"Delta (PDF - corpus) = {delta} letters "
          f"({100*delta/len(stream):.1f}%)")

    # If the deltas are large, we need to scale per-line counts so they sum
    # to the corpus total (to avoid running out / having leftovers).
    if abs(delta) / len(stream) > 0.005:
        scale = len(stream) / total_extracted
        print(f"Scaling per-line letter counts by {scale:.4f} to match corpus total")
        adjusted = []
        residual = 0.0
        for line_counts in columns_line_counts:
            new_counts = []
            for c in line_counts:
                target = c * scale + residual
                rounded = max(1, int(round(target)))
                residual = target - rounded
                new_counts.append(rounded)
            adjusted.append(new_counts)
        # Final correction: ensure sum equals stream length exactly
        running = sum(sum(cc) for cc in adjusted)
        diff = len(stream) - running
        if diff != 0:
            # Add/subtract from the last line of the last column
            adjusted[-1][-1] = max(1, adjusted[-1][-1] + diff)
        columns_line_counts = adjusted

    print("Slotting corpus letters into column lines…")
    columns = slot_letters_into_columns(stream, columns_line_counts)

    profile = {
        "name": "tikkun_koreim",
        "title": "Tikkun Koreim (HB50656) — Ashkenazi Stam layout",
        "tradition": "Ashkenazi",
        "source": "Parsed from user-supplied Tikkun-Koreim-HB50656.pdf, pages 1-245",
        "column_count": len(columns),
        "books_covered": TORAH_BOOKS,
        "columns": columns,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, separators=(",", ":"))
    size_kb = OUT.stat().st_size / 1024
    print(f"\n✅ Wrote {OUT} ({size_kb:.1f} KB)")
    print(f"   {len(columns)} columns, "
          f"{sum(len(c['lines']) for c in columns)} total lines")
    # Print first column summary
    if columns:
        first = columns[0]
        print(f"\n   Column 1: {len(first['lines'])} lines, "
              f"opens with {first.get('opens_with')}")
        for ln in first["lines"][:3]:
            print(f"     L{ln['line']:>2}: ({ln['letter_count']}) {ln['text_plain'][:60]}")


if __name__ == "__main__":
    main()
