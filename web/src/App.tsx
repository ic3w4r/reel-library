import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, JobStatus, Overview, Settings } from "./api";
import { useRoute } from "./router";
import Sidebar from "./components/Sidebar";
import ReelDrawer from "./components/ReelDrawer";
import Library from "./pages/Library";
import Links from "./pages/Links";
import Analytics from "./pages/Analytics";
import Import from "./pages/Import";
import SettingsPage from "./pages/Settings";

type AppState = {
  overview: Overview | null;
  jobs: JobStatus | null;
  settings: Settings | null;
  /** Bumps whenever library data may have changed (import, analysis finished, edits). */
  version: number;
  refresh: () => void;
  refreshJobs: () => void;
  setSettings: (s: Settings) => void;
  openReel: (id: string) => void;
  toast: (msg: string, kind?: "ok" | "error") => void;
};

const Ctx = createContext<AppState>(null!);
export const useApp = () => useContext(Ctx);

export default function App() {
  const route = useRoute();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [jobs, setJobs] = useState<JobStatus | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [version, setVersion] = useState(0);
  const [openId, setOpenId] = useState<string | null>(null);
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: string }[]>([]);
  const finished = useRef(-1);

  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  const toast = useCallback((msg: string, kind: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);

  const refreshJobs = useCallback(() => {
    api.jobs().then((j) => {
      setJobs(j);
      const count = j.done + j.failed;
      if (finished.current !== -1 && count !== finished.current) refresh();
      finished.current = count;
    }).catch(() => {});
  }, [refresh]);

  useEffect(() => {
    api.overview().then(setOverview).catch(() => {});
  }, [version]);

  useEffect(() => {
    api.settings().then(setSettings).catch(() => {});
  }, []);

  useEffect(() => {
    refreshJobs();
    const t = setInterval(refreshJobs, jobs?.running ? 2500 : 8000);
    return () => clearInterval(t);
  }, [refreshJobs, jobs?.running]);

  const state: AppState = {
    overview, jobs, settings, version, refresh, refreshJobs, setSettings,
    openReel: setOpenId, toast,
  };

  let page;
  switch (route.page) {
    case "links": page = <Links params={route.params} />; break;
    case "analytics": page = <Analytics />; break;
    case "import": page = <Import />; break;
    case "settings": page = <SettingsPage />; break;
    default: page = <Library params={route.params} />;
  }

  return (
    <Ctx.Provider value={state}>
      <div className="app">
        <Sidebar route={route} />
        <main className="main">{page}</main>
      </div>
      {openId && <ReelDrawer id={openId} onClose={() => setOpenId(null)} />}
      <div className="toasts">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}
      </div>
    </Ctx.Provider>
  );
}
