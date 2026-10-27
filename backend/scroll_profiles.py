"""
Scroll-profile / column-map service.

A scroll profile divides a Torah scroll into N columns, each containing a list
of lines. Each line records (a) its plain Hebrew text and (b) the (book, chapter,
verse) triples that the line touches.

Once we know which column the camera is looking at and where the yad is in the
frame (y-fraction 0..1), we can geometrically map directly to the active line
without precise OCR — we only need OCR good enough to identify the column.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

PROFILES_DIR = Path(__file__).parent / "data" / "scroll_profiles"

HEB_LETTER = re.compile(r"[\u05D0-\u05EA]")
NIKUD_TEAMIM = re.compile(r"[\u0591-\u05C7]")
WHITESPACE = re.compile(r"\s+")
NON_HEBREW = re.compile(r"[^\u05D0-\u05EA]")

# In-memory cache: name -> profile dict
_profiles: Dict[str, dict] = {}
# Reverse index: name -> list of dicts {column_idx, line_idx, text_compact, ngrams}
_search_index: Dict[str, List[dict]] = {}

DEFAULT_PROFILE = "tikkun_koreim"
NGRAM_N = 3


def _strip_to_letters(s: str) -> str:
    s = NIKUD_TEAMIM.sub("", s)
    s = NON_HEBREW.sub("", s)
    return s


def _ngrams(s: str, n: int = NGRAM_N) -> set:
    return {s[i:i + n] for i in range(0, len(s) - n + 1)} if len(s) >= n else set()


def list_profiles() -> List[dict]:
    """List available scroll profiles (without loading their full text)."""
    out = []
    for f in sorted(PROFILES_DIR.glob("*.json")):
        try:
            # Read only the metadata fields, not the columns array
            with open(f, "r", encoding="utf-8") as fp:
                # Parse the whole thing once — these files are small enough.
                data = json.load(fp)
            out.append({
                "name": data.get("name", f.stem),
                "title": data.get("title", f.stem),
                "tradition": data.get("tradition"),
                "source": data.get("source"),
                "column_count": data.get("column_count", len(data.get("columns", []))),
            })
        except Exception:
            continue
    return out


def get_profile(name: str) -> Optional[dict]:
    if name in _profiles:
        return _profiles[name]
    f = PROFILES_DIR / f"{name}.json"
    if not f.exists():
        return None
    with open(f, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    _profiles[name] = data
    return data


def _build_search_index(name: str):
    """Pre-compute per-line compact text + 3-grams for fast column lookup."""
    if name in _search_index:
        return _search_index[name]
    profile = get_profile(name)
    if not profile:
        return []
    idx = []
    for col in profile["columns"]:
        # Concatenate all letters in this column, plus per-line ngrams
        col_compact = "".join(line["text_plain"] for line in col["lines"])
        col_ngrams = _ngrams(col_compact)
        idx.append({
            "column": col["column"],
            "compact": col_compact,
            "ngrams": col_ngrams,
            "letter_count": len(col_compact),
        })
    _search_index[name] = idx
    return idx


def locate_column(snippet: str, profile_name: str = DEFAULT_PROFILE) -> Optional[dict]:
    """Given an OCR'd Hebrew snippet, identify which column of the scroll it
    came from. Returns {column, confidence, top_alternates} or None.

    Scoring combines:
      - recall    = |inter| / |snippet_ngrams|       in [0, 1]
      - precision = |inter| / |column_ngrams|        in [0, ~0.05]
      - The recall component is raised to the 1.5 power. This widens
        the gap between perfect-match candidates and almost-perfect
        ones — short clean snippets used to tie column 1 with column 203
        because both shared the common trigrams of "בראשית ברא אלהים" —
        without being so harsh that noisy OCR snippets (recall ≈ 0.4)
        fail to converge.

        score = recall^1.5 + 5.0 × precision

    On exact ties the lower column number wins (deterministic).
    """
    snippet_compact = _strip_to_letters(snippet)
    if len(snippet_compact) < 12:
        return None
    s_ng = _ngrams(snippet_compact)
    if not s_ng:
        return None
    idx = _build_search_index(profile_name)
    if not idx:
        return None
    s_size = max(len(s_ng), 1)
    PRECISION_WEIGHT = 5.0

    scored = []
    for col in idx:
        col_ng = col["ngrams"]
        if not col_ng:
            continue
        inter = s_ng & col_ng
        if not inter:
            continue
        recall = len(inter) / s_size
        precision = len(inter) / max(len(col_ng), 1)
        score = (recall ** 1.5) + PRECISION_WEIGHT * precision
        scored.append((score, recall, col["column"], len(inter), precision))

    if not scored:
        return None
    # Sort: highest score first; on ties, lower column number wins.
    scored.sort(key=lambda x: (-x[0], x[2]))
    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    margin = best[0] - (runner_up[0] if runner_up else 0.0)
    return {
        "column": best[2],
        "confidence": round(best[1], 3),       # headline recall (familiar 0..1)
        "score": round(best[0], 3),            # combined recall+precision
        "margin": round(margin, 3),
        "matched_ngram_count": best[3],
        "alternates": [
            {"column": c, "confidence": round(r, 3), "score": round(s, 3)}
            for s, r, c, _, _ in scored[1:5]
        ],
    }


def get_line_at(
    column: int,
    y_fraction: float,
    profile_name: str = DEFAULT_PROFILE,
) -> Optional[dict]:
    """Given a column # (1-based) and a y-fraction 0..1 (0=top, 1=bottom of
    the column on the scroll), return the active line: its index, plain text
    and the verse(s) it covers."""
    profile = get_profile(profile_name)
    if not profile:
        return None
    cols = profile["columns"]
    if column < 1 or column > len(cols):
        return None
    col = cols[column - 1]
    n = len(col["lines"])
    if n == 0:
        return None
    line_idx = max(0, min(n - 1, int(round(y_fraction * (n - 1)))))
    line = col["lines"][line_idx]
    return {
        "column": column,
        "line": line["line"],
        "lines_in_column": n,
        "letter_count": line["letter_count"],
        "text_plain": line["text_plain"],
        "verses": line["verses"],
    }


def get_column(column: int, profile_name: str = DEFAULT_PROFILE) -> Optional[dict]:
    profile = get_profile(profile_name)
    if not profile:
        return None
    cols = profile["columns"]
    if column < 1 or column > len(cols):
        return None
    return cols[column - 1]
