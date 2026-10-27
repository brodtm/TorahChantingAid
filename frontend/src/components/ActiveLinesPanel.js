import React from "react";
import { BookOpen, ChevronRight, ChevronLeft } from "lucide-react";

const CATEGORY_LABELS = { torah: "Torah", neviim: "Nevi'im", megillot: "Megillah" };

/**
 * The trope-aware active line panel: renders previous, active (bold), and next
 * verses with cantillation. Includes header (book / parsha / aliyah / haftarah)
 * and prev/next navigation. Pure-presentational + callbacks.
 */
export default function ActiveLinesPanel({ location, lines, onAdvance }) {
  return (
    <div className="bg-surface border border-border1 p-6 sm:p-8">
      <PanelHeader location={location} />
      {!lines && <EmptyState />}
      {lines && <LinesList lines={lines} />}
      {location && <PanelFooter location={location} onAdvance={onAdvance} />}
    </div>
  );
}

function PanelHeader({ location }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <div>
        <div className="flex items-center gap-2 text-xs tracking-[0.25em] uppercase text-ink2">
          Now Reading
          {location?.category && (
            <span
              className="px-2 py-0.5 border border-border1 text-[10px] tracking-[0.25em]"
              data-testid="category-badge"
            >
              {CATEGORY_LABELS[location.category] || location.category}
            </span>
          )}
        </div>
        <div className="font-display text-2xl mt-1">
          {location ? (
            <>
              <span className="text-ink">{location.book}</span>{" "}
              <span className="text-gold">{location.chapter}:{location.verse}</span>
            </>
          ) : "—"}
        </div>
        {location?.haftarah_for && (
          <div className="text-xs tracking-[0.2em] uppercase text-gold mt-1" data-testid="haftarah-label">
            Haftarah for {location.haftarah_for}
          </div>
        )}
      </div>
      <div className="text-right">
        {location?.parsha && (
          <div className="hebrew-line text-xl text-ink" dir="rtl">{location.parsha}</div>
        )}
        {location?.aliyah && (
          <div className="text-xs tracking-[0.25em] uppercase text-ink2 mt-1">Aliyah {location.aliyah}</div>
        )}
        {location?.book_he && !location?.parsha && (
          <div className="hebrew-line text-xl text-ink" dir="rtl">{location.book_he}</div>
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-12 text-ink2">
      <BookOpen size={32} className="mx-auto mb-3 opacity-50" />
      <div className="text-sm">Waiting for the yad to land on a verse…</div>
    </div>
  );
}

function LinesList({ lines }) {
  return (
    <div className="space-y-4 text-right" dir="rtl" data-testid="lines-panel">
      {lines.previous?.map((p) => (
        <div
          key={`prev-${p.book}-${p.chapter}-${p.verse}`}
          className="hebrew-line hebrew-context"
          data-testid={`prev-line-${p.verse}`}
        >
          {p.he_with_teamim}
        </div>
      ))}
      <div
        className="hebrew-line hebrew-active border-r-2 border-gold pr-4"
        data-testid="active-line"
      >
        {lines.active.he_with_teamim}
      </div>
      {lines.next?.map((n) => (
        <div
          key={`next-${n.book}-${n.chapter}-${n.verse}`}
          className="hebrew-line hebrew-context"
          data-testid={`next-line-${n.verse}`}
        >
          {n.he_with_teamim}
        </div>
      ))}
    </div>
  );
}

function PanelFooter({ location, onAdvance }) {
  return (
    <div className="flex items-center justify-between mt-6 pt-4 border-t border-border1">
      <button
        data-testid="prev-verse"
        onClick={() => onAdvance(-1)}
        className="inline-flex items-center gap-1 text-ink2 hover:text-ink"
      >
        <ChevronRight size={16} /> Previous
      </button>
      <span className="text-xs tracking-[0.25em] uppercase text-ink2">
        Confidence {(location.confidence * 100).toFixed(0)}%
      </span>
      <button
        data-testid="next-verse"
        onClick={() => onAdvance(1)}
        className="inline-flex items-center gap-1 text-ink2 hover:text-ink"
      >
        Next <ChevronLeft size={16} />
      </button>
    </div>
  );
}
