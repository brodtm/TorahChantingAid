import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "./api";

/**
 * Column-map mode: instead of word-perfect OCR matching, we
 *   (1) identify the active scroll column via OCR + n-gram (~1200 ngrams,
 *       very robust against ~40% letter errors), and
 *   (2) use the yad's vertical position + camera homography to look up the
 *       active line via /api/scroll/line-at.
 *
 * The column re-locks with a 3-frame consensus, then sticks until OCR votes
 * for a different column 3 frames in a row (avoids flicker on bad OCR frames).
 *
 * Inputs:
 *   ocrText      - latest OCR text from the camera loop (string)
 *   yad          - { x, y, score } | null  yad detection in normalized coords
 *   profileName  - which scroll-profile to query
 *   enabled      - toggle the whole subsystem
 *
 * Returns:
 *   { column, columnConfidence, locked, lineInfo, verses, alternates }
 */
export function useColumnMap({ ocrText, yad, profileName = "tikkun_koreim", enabled = false } = {}) {
  const [column, setColumn] = useState(null);
  const [columnConfidence, setColumnConfidence] = useState(0);
  const [alternates, setAlternates] = useState([]);
  const [lineInfo, setLineInfo] = useState(null);
  const [verses, setVerses] = useState([]);
  const [locked, setLocked] = useState(false);

  // Rolling window of the last N column votes.  Each vote is the
  // backend's full {column, confidence, score, margin, alternates}
  // response, OR null for a "no match" frame.  Voting is confidence-
  // weighted so one good frame can outweigh several mediocre ones; a
  // single bad OCR frame can no longer unlock a hard-won column.
  const VOTE_WINDOW = 6;
  const LOCK_THRESHOLD = 0.55;  // winner's share of total weight
  const votesRef = useRef([]);
  const lastSnippetRef = useRef("");

  // Whenever we get a new OCR snippet, ask the backend which column it is.
  useEffect(() => {
    if (!enabled || !ocrText) return;
    if (ocrText === lastSnippetRef.current) return;
    lastSnippetRef.current = ocrText;
    let cancelled = false;
    (async () => {
      try {
        const res = await api.locateColumn(ocrText, profileName);
        if (cancelled) return;
        votesRef.current = [...votesRef.current, res || null].slice(-VOTE_WINDOW);

        // Confidence-weighted histogram of recent votes.
        const tally = new Map();   // column → cumulative weight
        const meta = new Map();    // column → most recent {confidence, alternates}
        let totalWeight = 0;
        for (const v of votesRef.current) {
          if (!v || !v.column) continue;
          // Vote weight = confidence; floor 0.1 so any positive vote
          // contributes something. Margin further reinforces high-
          // certainty frames.
          const w = Math.max(0.1, v.confidence) * (1 + Math.max(0, v.margin || 0));
          tally.set(v.column, (tally.get(v.column) || 0) + w);
          totalWeight += w;
          meta.set(v.column, v);
        }
        if (totalWeight === 0) {
          // No positive votes in window → leave previous state alone
          return;
        }
        // Pick winner
        let bestCol = null;
        let bestWeight = 0;
        for (const [c, w] of tally.entries()) {
          if (w > bestWeight) {
            bestCol = c;
            bestWeight = w;
          }
        }
        const winnerMeta = meta.get(bestCol);
        const share = bestWeight / totalWeight;
        setColumn(bestCol);
        setColumnConfidence(winnerMeta.confidence);
        setAlternates(winnerMeta.alternates || []);
        setLocked(share >= LOCK_THRESHOLD);
      } catch (e) {
        console.warn("[useColumnMap] locate-column failed:", e);
      }
    })();
    return () => { cancelled = true; };
  }, [ocrText, profileName, enabled]);

  // Whenever yad y changes (and we have a column), look up the active line.
  const yadY = yad?.y ?? null;
  useEffect(() => {
    if (!enabled || !column || yadY == null) return;
    let cancelled = false;
    (async () => {
      try {
        const li = await api.scrollLineAt(column, yadY, profileName);
        if (cancelled) return;
        setLineInfo(li);
        // Fetch verse text (with cantillation) for each verse the line touches.
        const vs = await Promise.all(
          (li.verses || []).map((v) =>
            api.getLines(v.book, v.chapter, v.verse, 0).catch(() => null),
          ),
        );
        if (!cancelled) {
          setVerses(vs.filter(Boolean).map((r) => r.active));
        }
      } catch (e) {
        console.warn("[useColumnMap] line-at failed:", e);
      }
    })();
    return () => { cancelled = true; };
  }, [column, yadY, profileName, enabled]);

  // Allow manual column override (user can set column when OCR is unavailable)
  const setColumnManually = useCallback((n) => {
    setColumn(n);
    setLocked(true);
    setColumnConfidence(1);
    votesRef.current = [];
  }, []);

  return {
    column, columnConfidence, alternates, locked, lineInfo, verses,
    setColumnManually,
  };
}
