import { AlertTriangle, Clock, Loader2 } from "lucide-react";
import { ReelSummary } from "../api";
import { useApp } from "../App";
import { categoryColor } from "./Sidebar";

export function reelState(reel: ReelSummary, queued: Set<string>, currentId?: string) {
  if (currentId === reel.id) return "analyzing";
  if (queued.has(reel.id)) return "queued";
  return reel.status;
}

export default function ReelCard({ reel, state }: { reel: ReelSummary; state: string }) {
  const { openReel } = useApp();
  const color = categoryColor(reel.category);
  return (
    <button className="reel-card" onClick={() => openReel(reel.id)}>
      <div className="reel-thumb" style={{ ["--cat" as string]: color }}>
        {reel.thumbnail
          ? <img src={reel.thumbnail} alt="" loading="lazy" />
          : <div className="thumb-placeholder"><span>{(reel.creator || "?").slice(0, 1).toUpperCase()}</span></div>}
        {state !== "analyzed" && <StatusBadge state={state} />}
        {reel.category && <span className="thumb-cat" style={{ background: color }}>{reel.category}</span>}
      </div>
      <div className="reel-body">
        <div className="reel-title">{reel.title || (reel.creator ? `Reel by @${reel.creator}` : reel.id)}</div>
        {reel.summary
          ? <p className="reel-summary">{reel.summary}</p>
          : <p className="reel-summary muted">{state === "failed" ? "Couldn't be analyzed — open for details." : "Not analyzed yet."}</p>}
        <div className="reel-meta">
          {reel.creator && <span>@{reel.creator}</span>}
          {reel.collections?.slice(0, 2).map((c) => <span key={c} className="chip chip-soft">{c}</span>)}
        </div>
      </div>
    </button>
  );
}

export function StatusBadge({ state }: { state: string }) {
  const map: Record<string, [string, JSX.Element]> = {
    pending: ["Not analyzed", <Clock size={12} />],
    queued: ["Queued", <Clock size={12} />],
    analyzing: ["Analyzing…", <Loader2 size={12} className="spin" />],
    failed: ["Failed", <AlertTriangle size={12} />],
  };
  const [label, icon] = map[state] || [state, <></>];
  return <span className={`status-badge s-${state}`}>{icon}{label}</span>;
}
