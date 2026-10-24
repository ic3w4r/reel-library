import { AlertTriangle, BarChart3, Clapperboard, FolderOpen, Inbox, Library, Link2, Settings, Sparkles, Upload } from "lucide-react";
import { useApp } from "../App";
import { href, Route } from "../router";

export default function Sidebar({ route }: { route: Route }) {
  const { overview, jobs } = useApp();
  const collection = route.params.get("collection");
  const category = route.params.get("category");
  const onLibrary = route.page === "library";

  const nav = (page: string, label: string, Icon: typeof Library, badge?: number) => (
    <a className={`nav-item ${route.page === page && !(page === "library" && (collection || category)) ? "active" : ""}`}
       href={href(page)}>
      <Icon size={17} /> <span>{label}</span>
      {badge ? <span className="nav-badge">{badge}</span> : null}
    </a>
  );

  const progress = jobs && jobs.batch_total ? (jobs.done + jobs.failed) / jobs.batch_total : 0;

  return (
    <aside className="sidebar">
      <a className="brand" href={href("library")}>
        <span className="brand-mark"><Clapperboard size={18} /></span>
        <span>
          <strong>Reel Library</strong>
          <small>your Instagram saves, understood</small>
        </span>
      </a>

      <nav className="nav">
        {nav("library", "All saved", Library, overview?.total_reels)}
        {nav("links", "Links & resources", Link2, overview?.extracted_links)}
        {nav("analytics", "Analytics", BarChart3)}
        {nav("import", "Add & analyze", Upload, overview?.by_status?.pending)}
        {nav("settings", "Settings", Settings)}
      </nav>

      {jobs?.running && (
        <a className="job-pill" href={href("import")}>
          <div className="job-pill-row">
            <Sparkles size={14} className="spin-slow" />
            <span>Analyzing {Math.min(jobs.done + jobs.failed + 1, jobs.batch_total)} of {jobs.batch_total}</span>
          </div>
          <div className="progress"><div style={{ width: `${progress * 100}%` }} /></div>
        </a>
      )}

      {jobs?.halted && !jobs.running && (
        <a className="job-pill halted" href={href("import")}>
          <div className="job-pill-row"><AlertTriangle size={14} /><span>Analysis stopped — see why</span></div>
        </a>
      )}

      {overview && overview.collections.length > 0 && (
        <div className="side-section">
          <div className="side-title">Your collections</div>
          {overview.collections.map((c) => (
            <a key={c.name}
               className={`side-link ${onLibrary && collection === c.name ? "active" : ""}`}
               href={href("library", { collection: c.name })}>
              <FolderOpen size={15} /> <span className="truncate">{c.name}</span>
              <span className="count">{c.reels}</span>
            </a>
          ))}
          {overview.not_in_any_collection > 0 && (
            <a className={`side-link ${onLibrary && collection === "__none__" ? "active" : ""}`}
               href={href("library", { collection: "__none__" })}>
              <Inbox size={15} /> <span className="truncate">Not in a collection</span>
              <span className="count">{overview.not_in_any_collection}</span>
            </a>
          )}
        </div>
      )}

      {overview && Object.keys(overview.categories).length > 0 && (
        <div className="side-section">
          <div className="side-title">Categories</div>
          {Object.entries(overview.categories).map(([name, n]) => (
            <a key={name}
               className={`side-link ${onLibrary && category === name ? "active" : ""}`}
               href={href("library", { category: name })}>
              <span className="cat-dot" style={{ background: categoryColor(name) }} />
              <span className="truncate">{name}</span>
              <span className="count">{n}</span>
            </a>
          ))}
        </div>
      )}
    </aside>
  );
}

const PALETTE = ["#e4405f", "#f77737", "#fcaf45", "#2bb673", "#1fa2ff", "#7b61ff", "#c13584", "#00a3a3",
  "#ff6f91", "#8e7dff", "#3fb950", "#d29922", "#58a6ff", "#db61a2", "#f0883e", "#56d4dd", "#a371f7", "#8b949e"];

export function categoryColor(name?: string): string {
  if (!name) return "#8b949e";
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
