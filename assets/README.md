# Assets

Source and test material used to build and check the Torah Chanting Aid.

| File | What it is | Used by |
|---|---|---|
| `Tikkun-Koreim-HB50656.pdf` | Tikkun Koreim: the scribal (Stam) text side by side with the vowelled text, 245 columns | `backend/build_column_map.py` builds the 42-line column map from it (`backend/data/scroll_profiles/tikkun_koreim.json`); used for the OCR accuracy test in `test_reports/tikkun_ocr_report.md` |
| `../frontend/public/demo/torah_overlay.mp4` | Demo output: real Parashat Emor scroll footage with the perspective-warped trope overlay | Served by the app at `/demo/torah_overlay.mp4` |

Test results from these files are in `../test_reports/` (`real_video_validation.md`, `tikkun_ocr_report.md`, `iteration_*.json`, `pytest/*.xml`).

## Not included
The original Parashat Emor scroll video, the frames taken from it, and the demo-rendering scripts (`render_overlay_v*.py`) were kept in temporary storage while the app was being built. They were not saved with the project. To add the source video, put it here as `assets/emor_scroll_input.mp4` (GitHub rejects files over 100 MB).
