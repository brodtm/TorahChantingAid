import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { BookOpen, ScanLine, Projector, ArrowRight, Loader2 } from "lucide-react";

export default function HomePage() {
  const nav = useNavigate();
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ ok: false }));
  }, []);

  const startSession = async () => {
    setBusy(true);
    setError("");
    try {
      const s = await api.createSession(name || "Reading Session");
      nav(`/session/${s.id}`);
    } catch (e) {
      setError(e?.message || "Failed to start session");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen parchment-bg" data-testid="home-page">
      <div className="max-w-3xl mx-auto px-6 pt-12 pb-24">
        {/* Header */}
        <div className="flex items-center justify-between mb-12">
          <div>
            <div className="text-xs tracking-[0.3em] uppercase text-ink2 mb-2">Bimah Companion</div>
            <h1 className="font-display text-4xl sm:text-5xl text-ink leading-none">
              Torah <span className="text-gold">Chanting</span> Aid
            </h1>
          </div>
          <span
            className={`status-pill ${health?.ok ? "ok" : "warn"}`}
            data-testid="health-pill"
          >
            <span className="dot" />
            {health?.ok ? "Online" : "Offline"}
          </span>
        </div>

        {/* Hebrew preview */}
        <div className="bg-surface border border-border1 px-8 py-10 mb-10">
          <div className="hebrew-line hebrew-active text-right" dir="rtl">
            בְּרֵאשִׁ֖ית בָּרָ֣א אֱלֹהִ֑ים אֵ֥ת הַשָּׁמַ֖יִם וְאֵ֥ת הָאָֽרֶץ׃
          </div>
          <div className="hebrew-line hebrew-context text-right mt-3" dir="rtl">
            וְהָאָ֗רֶץ הָיְתָ֥ה תֹ֙הוּ֙ וָבֹ֔הוּ
          </div>
          <div className="text-xs tracking-[0.2em] uppercase text-ink2 mt-6 text-right">
            Te'amim · Cantillation marks visible above & below letters
          </div>
        </div>

        {/* Steps */}
        <div className="grid sm:grid-cols-3 gap-4 mb-10">
          <Step n={1} icon={<BookOpen size={18} />} label="Mount phone above the bimah" />
          <Step n={2} icon={<ScanLine size={18} />} label="Camera locates the open Torah" />
          <Step n={3} icon={<Projector size={18} />} label="Trope projects onto the parchment" />
        </div>

        {/* Start session */}
        <div className="bg-surface border border-border1 p-6">
          <label className="text-xs tracking-[0.2em] uppercase text-ink2 block mb-2">Session name</label>
          <input
            data-testid="session-name-input"
            className="w-full bg-transparent border-b border-border1 py-2 text-lg focus:outline-none focus:border-gold"
            placeholder="Shabbat Bereshit · Morning"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          {error && <div className="text-warning text-sm mt-3">{error}</div>}
          <div className="flex justify-between items-center mt-6">
            <div className="text-xs text-ink2">
              {health?.indexed_verses ? `${health.indexed_verses.toLocaleString()} verses indexed · Torah · Nevi'im · Megillot` : "Index will load on first lookup"}
            </div>
            <button
              data-testid="start-session-button"
              onClick={startSession}
              disabled={busy}
              className="inline-flex items-center gap-2 bg-ink text-parchment px-6 py-3 hover:bg-gold transition-colors disabled:opacity-60"
            >
              {busy ? <Loader2 className="animate-spin" size={18} /> : <ArrowRight size={18} />}
              Start session
            </button>
          </div>
        </div>

        <div className="mt-8 text-xs text-ink2 text-center">
          Open the projector view on your secondary HDMI display: <span className="font-mono">/projector</span>
        </div>
      </div>
    </div>
  );
}

function Step({ n, icon, label }) {
  return (
    <div className="bg-surface border border-border1 p-5">
      <div className="flex items-center gap-2 text-gold mb-2">
        {icon}
        <span className="text-xs tracking-[0.25em] uppercase text-ink2">Step {n}</span>
      </div>
      <div className="text-sm text-ink leading-snug">{label}</div>
    </div>
  );
}
