import { useEffect, useState } from "react";
import { BookOpen, FlaskConical, Route, Zap } from "lucide-react";
import { StoreProvider, useStore } from "./state/store";
import { Studio } from "./views/Studio";
import { DisruptionLab } from "./views/DisruptionLab";
import { Evidence } from "./views/Evidence";
import { DataMethod } from "./views/DataMethod";
import "./App.css";

type View = "studio" | "disrupt" | "evidence" | "method";

const VIEWS: { id: View; label: string; icon: typeof Route }[] = [
  { id: "studio", label: "Route Studio", icon: Route },
  { id: "disrupt", label: "Disruption Lab", icon: Zap },
  { id: "evidence", label: "Evidence", icon: FlaskConical },
  { id: "method", label: "Data & Method", icon: BookOpen },
];

function readHash(): View {
  const h = window.location.hash.replace("#", "") as View;
  return VIEWS.some((v) => v.id === h) ? h : "studio";
}

function Shell() {
  const [view, setView] = useState<View>(readHash);
  const { health, healthError } = useStore();
  useEffect(() => {
    const on = () => setView(readHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (v: View) => {
    window.location.hash = v;
    setView(v);
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <svg width="22" height="22" viewBox="0 0 22 22">
              <rect x="1" y="1" width="20" height="20" rx="5" fill="#0b1324" />
              <path d="M6 15.5 L10 9.5 L13 12.5 L16.5 6.5" stroke="#fff" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="16.5" cy="6.5" r="1.7" fill="#5b83ff" />
            </svg>
          </span>
          <span className="brand-name">KAIROS</span>
          <span className="brand-tag">Reliability-aware last-mile routing</span>
        </div>
        <nav className="nav" aria-label="Workspaces">
          {VIEWS.map(({ id, label, icon: Icon }) => (
            <button key={id} className={view === id ? "nav-item active" : "nav-item"} onClick={() => go(id)} aria-current={view === id ? "page" : undefined}>
              <Icon size={15} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="status" title={health ? `${health.solver} · LightGBM ${health.lightgbm}` : healthError}>
          <span className={`status-dot ${health ? "ok" : healthError ? "bad" : ""}`} />
          <span>{health ? health.solver : healthError ? "Backend offline" : "Connecting"}</span>
        </div>
      </header>
      <main className="main">
        {healthError && !health && (
          <div className="offline">
            The KAIROS backend is not reachable. Start it with <code>scripts\run_backend.ps1</code> (Windows) or{" "}
            <code>scripts/run_backend.sh</code>, then reload.
          </div>
        )}
        {view === "studio" && <Studio />}
        {view === "disrupt" && <DisruptionLab onNeedPlan={() => go("studio")} />}
        {view === "evidence" && <Evidence />}
        {view === "method" && <DataMethod />}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <StoreProvider>
      <Shell />
    </StoreProvider>
  );
}
