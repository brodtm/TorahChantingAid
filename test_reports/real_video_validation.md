# Real-video validation v2 — after column-map tightening + yad-tap fallback

Date: 2026-02 fork (P0 + P1 complete)

## Tightened Tikkun column-map parser
- Old `build_column_map.py` produced 6706 lines across 245 columns
  (mean ~60 lines/col, ~37% of corpus letters lost, 47 broken pages).
- New parser filters glyphs to the MODE (most frequent) font size per page
  before y-clustering. Drops marginalia / nikud notes / dropcap initials.
- New profile: **245 columns, 10,002 lines, mean 40.8, median 42, full
  305,859 corpus letters preserved.**
- Verse boundaries now align with reality:
  - col 1: Genesis 1:1 → … (Bereshit opening, 38 lines)
  - col 140: Leviticus 21:2 → 22:4 (Emor 1st aliyah — blemishes)
  - col 141: Leviticus 22:4 → 22:30
  - col 142: Leviticus 22:30 → 23:22 (Emor festivals — "ובחמשה עשר")
  - col 143: Leviticus 23:22 → 23:42 (Sukkot)

## Real-video verification (Parashat Emor scroll)
Re-OCR'd the same 5 columns from `framesfull/f_05.jpg` against the new
profile via `/api/scroll/locate-column`:

| Strip | Old map → col | New map → col | Match |
|-------|---------------|---------------|-------|
| c1    | 142           | **142**       | ✅ Emor |
| c2    | 142           | **142**       | ✅ Emor |
| c3    | 141           | **143**       | ✅ Emor (closer to actual yad-pointed line) |
| c4    | 140           | **141**       | ✅ Emor |
| c5    | 140           | 167           | ⚠ low conf (margin 0.106) — partial-column OCR |

`/api/scroll/line-at` with column 142, y=0.5 returns **line 21/42 →
Leviticus 23:11** — exactly the wave-the-omer passage in the middle of
the festival aliyah. The geometric line-lookup is now usable.

## Yad-tip detection (P0)
Replaced the dark-blob centroid in `cv.js::detectYadTip` with a
warm-dark mask + connected-components + scroll-roller rejection + PCA
tip extraction. The tip is identified as the PCA-axis endpoint with the
larger distance to the nearest frame edge.

Limitations observed on the user's video: when the yad reflects the
warm parchment tone (saturation ~0.5, value ~200), it blends into
parchment and auto-detection has low recall. To handle that:

Added a **tap-to-set fallback** in `SessionPage.CameraView`:
- Tapping the camera preview sets the yad's normalized (x, y) for 30s.
- Override stored in a ref so rAF loop reads fresh values without
  re-binding.
- Visible "MANUAL" badge below the yad marker; "Tap to mark yad
  position" hint at the bottom of the camera frame.

This makes the line-tracking pipeline usable end-to-end even in low-
contrast lighting where auto-detection struggles.
