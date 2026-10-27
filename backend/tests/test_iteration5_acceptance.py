"""Iteration-5 acceptance tests for the tightened Tikkun-Koreim column-map parser.

These match the explicit acceptance criteria in the review request:
  - GET /api/scroll/profiles returns synthetic_248 AND tikkun_koreim (column_count > 240).
  - Bereshit opening locates to column 1, confidence >= 0.9, margin > 0.5.
  - Emor festivals fragment locates to a column in 141..143.
  - line-at(col=142, y=0.5) returns line==21, lines_in_column==42, verses include
    Leviticus chapter 23 verse 11.
  - 5-char snippet -> null (length floor).
  - Tikkun JSON sanity: median lines/col == 42, mean >= 40, no zero-line column,
    total letters across all lines == 305859.
"""
import json
import os
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
# Frontend .env is the source of truth for the public URL.
load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
API = f"{BASE_URL}/api"

TIKKUN_JSON_PATH = (
    Path(__file__).resolve().parents[1]
    / "data" / "scroll_profiles" / "tikkun_koreim.json"
)


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- /api/scroll/profiles ---------------------------------------------------

def test_profiles_list_contains_both_with_high_column_count(client):
    r = client.get(f"{API}/scroll/profiles", timeout=30)
    assert r.status_code == 200
    data = r.json()
    by_name = {p["name"]: p for p in data}
    assert "synthetic_248" in by_name, f"profiles: {list(by_name)}"
    assert "tikkun_koreim" in by_name, f"profiles: {list(by_name)}"
    assert by_name["synthetic_248"]["column_count"] > 240
    assert by_name["tikkun_koreim"]["column_count"] > 240


# --- /api/scroll/locate-column ----------------------------------------------

def test_locate_bereshit_opening_tikkun(client):
    snippet = (
        "בראשיתבראאלהיםאתהשמיםואתהארץוהארץהיתהתהוובהווחשךעלפניתהוםורוחאלהיםמרחפת"
    )
    r = client.post(
        f"{API}/scroll/locate-column",
        json={"snippet": snippet, "profile": "tikkun_koreim"},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "locate-column returned null for canonical Bereshit opening"
    assert d["column"] == 1, f"expected column 1, got {d['column']}"
    assert d["confidence"] >= 0.9, f"confidence too low: {d['confidence']}"
    assert d["margin"] > 0.5, f"margin too low: {d['margin']}"


def test_locate_emor_festivals_fragment(client):
    snippet = (
        "ובחמשהעשריוםלחדשהזההחגהמצותשבעתימיםמצותתאכלוביוםהראשון"
        "מקראקדשיהיהלכםכלמלאכתעבדהלאתעשו"
    )
    r = client.post(
        f"{API}/scroll/locate-column",
        json={"snippet": snippet, "profile": "tikkun_koreim"},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d is not None, "locate-column returned null for Emor festivals fragment"
    assert 141 <= d["column"] <= 143, f"expected column 141..143, got {d['column']}"


def test_locate_column_5char_returns_null(client):
    r = client.post(
        f"{API}/scroll/locate-column",
        json={"snippet": "אבגדה", "profile": "tikkun_koreim"},
        timeout=30,
    )
    assert r.status_code == 200
    assert r.json() is None, "snippet under length floor should return null"


# --- /api/scroll/line-at ----------------------------------------------------

def test_line_at_col142_mid_returns_leviticus_23_11(client):
    r = client.post(
        f"{API}/scroll/line-at",
        json={"column": 142, "y_fraction": 0.5, "profile": "tikkun_koreim"},
        timeout=30,
    )
    assert r.status_code == 200
    d = r.json()
    assert d["lines_in_column"] == 42, f"lines_in_column={d['lines_in_column']}"
    assert d["line"] == 21, f"line={d['line']}"
    verses = d.get("verses") or []
    matched = any(
        (v.get("book") in ("Leviticus", "ויקרא"))
        and v.get("chapter") == 23
        and v.get("verse") == 11
        for v in verses
    )
    assert matched, f"Leviticus 23:11 not in verses: {verses}"


# --- tikkun_koreim.json sanity (file-level, no API) -------------------------

def test_tikkun_json_sanity_median_42_mean_40_no_zero():
    with open(TIKKUN_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    cols = data["columns"]
    line_counts = sorted(len(c["lines"]) for c in cols)
    n = len(line_counts)
    if n % 2 == 1:
        median = line_counts[n // 2]
    else:
        median = (line_counts[n // 2 - 1] + line_counts[n // 2]) / 2
    mean = sum(line_counts) / n
    assert median == 42, f"median lines/col = {median}, expected 42"
    assert mean >= 40, f"mean lines/col = {mean}, expected >= 40"
    assert min(line_counts) > 0, "found a column with zero lines"


def test_tikkun_json_total_letters_305859():
    with open(TIKKUN_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    total = sum(
        line["letter_count"]
        for col in data["columns"]
        for line in col["lines"]
    )
    assert total == 305859, f"total letters = {total}, expected 305859"
