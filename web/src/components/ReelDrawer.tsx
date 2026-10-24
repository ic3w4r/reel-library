import { BadgeCheck, BrainCircuit, ExternalLink, FolderPlus, Lightbulb, RefreshCw, Search, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, LinkItem, ReelDetail } from "../api";
import { useApp } from "../App";
import { StatusBadge } from "./ReelCard";
import { categoryColor } from "./Sidebar";

export default function ReelDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const { version, toast, refresh, refreshJobs, jobs, overview } = useApp();
  const [reel, setReel] = useState<ReelDetail | null>(null);
  const [error, setError] = useState("");
  const [newCol, setNewCol] = useState("");

  useEffect(() => {
    api.reel(id).then(setReel).catch((e) => setError(e.message));
  }, [id, version]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const state = jobs?.current?.id === id ? "analyzing" : jobs?.queued_ids.includes(id) ? "queued" : reel?.status;

  const reanalyze = async () => {
    try {
      await api.analyze({ ids: [id] });
      toast("Queued for analysis");
      refreshJobs();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const remove = async () => {
    if (!confirm("Remove this reel from the library? (It stays saved on Instagram.)")) return;
    await api.deleteReel(id);
    toast("Removed from library");
    refresh();
    onClose();
  };

  const addCol = async (name: string) => {
    if (!name.trim()) return;
    const r = await api.addToCollection(id, name.trim());
    setReel((x) => x && { ...x, collections: r.collections });
    setNewCol("");
    refresh();
  };

  const removeCol = async (name: string) => {
    const r = await api.removeFromCollection(id, name);
    setReel((x) => x && { ...x, collections: r.collections });
    refresh();
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <button className="icon-btn drawer-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
        {error && <div className="error-box">{error}</div>}
        {!reel && !error && <div className="loading">Loading…</div>}
        {reel && (
          <>
            <div className="drawer-hero">
              {reel.thumbnail
                ? <img src={reel.thumbnail} alt="" />
                : <div className="thumb-placeholder big" style={{ ["--cat" as string]: categoryColor(reel.category) }}>
                    <span>{(reel.creator || "?").slice(0, 1).toUpperCase()}</span></div>}
              <div className="drawer-hero-text">
                <div className="chips">
                  {state && state !== "analyzed" && <StatusBadge state={state} />}
                  {reel.category && <span className="chip" style={{ background: categoryColor(reel.category), color: "#fff" }}>{reel.category}</span>}
                  {reel.content_type && <span className="chip chip-soft">{reel.content_type.replace(/_/g, " ")}</span>}
                  {reel.duration_seconds ? <span className="chip chip-soft">{Math.round(reel.duration_seconds)}s</span> : null}
                </div>
                <h2>{reel.title || `Reel by @${reel.creator || reel.id}`}</h2>
                <div className="muted small">
                  {reel.creator && <a href={`https://www.instagram.com/${reel.creator}/`} target="_blank" rel="noreferrer">@{reel.creator}</a>}
                  {reel.saved_at && <> · saved {reel.saved_at}</>}
                </div>
                <div className="row gap">
                  <a className="btn btn-primary" href={reel.url} target="_blank" rel="noreferrer"><ExternalLink size={15} /> Open on Instagram</a>
                  <button className="btn" onClick={reanalyze} disabled={state === "queued" || state === "analyzing"}>
                    <RefreshCw size={15} /> {reel.status === "analyzed" ? "Re-analyze" : "Analyze"}
                  </button>
                </div>
              </div>
            </div>

            {reel.status === "failed" && reel.error && (
              <div className="error-box"><strong>Analysis failed.</strong> {reel.error}</div>
            )}

            {reel.why_saved && (
              <div className="callout"><Lightbulb size={17} /><div><strong>Why you saved it:</strong> {reel.why_saved}</div></div>
            )}

            {reel.signals && <SignalChips signals={reel.signals} />}

            {reel.summary && <Section title="Summary"><p>{reel.summary}</p></Section>}

            {reel.key_points && reel.key_points.length > 0 && (
              <Section title="Key points">
                <ul className="points">{reel.key_points.map((p, i) => <li key={i}>{p}</li>)}</ul>
              </Section>
            )}

            {reel.links && reel.links.length > 0 && (
              <Section title={`Links & resources (${reel.links.length})`}>
                <div className="link-list">{reel.links.map((l, i) => <LinkRow key={i} link={l} />)}</div>
              </Section>
            )}

            <Section title="Collections">
              <div className="chips">
                {(reel.collections || []).map((c) => (
                  <span key={c} className="chip chip-soft removable">{c}
                    <button onClick={() => removeCol(c)} aria-label={`Remove from ${c}`}><X size={12} /></button>
                  </span>
                ))}
                <form className="inline-form" onSubmit={(e) => { e.preventDefault(); addCol(newCol); }}>
                  <FolderPlus size={15} />
                  <input list="collection-names" value={newCol} onChange={(e) => setNewCol(e.target.value)} placeholder="Add to collection…" />
                  <datalist id="collection-names">
                    {overview?.collections.map((c) => <option key={c.name} value={c.name} />)}
                  </datalist>
                </form>
              </div>
            </Section>

            {reel.tags && reel.tags.length > 0 && (
              <Section title="Tags">
                <div className="chips">{reel.tags.map((t) => <span key={t} className="chip chip-outline">#{t}</span>)}</div>
              </Section>
            )}

            {reel.on_screen_text && <Collapsible title="On-screen text" text={reel.on_screen_text} />}
            {reel.transcript && <Collapsible title="Transcript" text={reel.transcript} />}
            {reel.caption && <Collapsible title="Caption" text={reel.caption} />}

            <div className="drawer-foot">
              <span className="muted small">{reel.analyzed_at ? `Analyzed ${reel.analyzed_at}` : ""}</span>
              <button className="btn btn-ghost danger" onClick={remove}><Trash2 size={15} /> Remove from library</button>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}

function SignalChips({ signals }: { signals: NonNullable<ReelDetail["signals"]> }) {
  const purpose: Record<string, string> = { learn: "to learn", entertain: "entertainment", inspire: "inspiration", shop: "shopping" };
  const a = signals.actionable;
  return (
    <div className="signal-row" title="Quick estimates from the local Laya decision model">
      <span className="signal-src"><BrainCircuit size={13} /> Laya</span>
      {a && <span className="chip chip-outline">{a.answer === "yes" ? "Actionable" : "Not actionable"} · {Math.round((a.value || 0) * 100)}%</span>}
      {signals.revisit && <span className="chip chip-outline">Revisit value: {signals.revisit.answer}</span>}
      {signals.purpose && <span className="chip chip-outline">Watched for {purpose[signals.purpose.answer] || signals.purpose.answer}</span>}
      {signals.category && <span className="chip chip-outline">{signals.category.answer}</span>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="section"><h3>{title}</h3>{children}</section>;
}

function Collapsible({ title, text }: { title: string; text: string }) {
  return (
    <details className="collapsible">
      <summary>{title}</summary>
      <p className="pre">{text}</p>
    </details>
  );
}

export function LinkRow({ link, showReel }: { link: LinkItem; showReel?: (id: string) => void }) {
  return (
    <div className="link-row">
      <div className="link-main">
        <div className="link-name">
          {link.name}
          {link.kind && <span className="chip chip-outline tiny">{link.kind}</span>}
        </div>
        {link.description && <div className="muted small">{link.description}</div>}
        {link.url && (
          <a className="link-url" href={link.url} target="_blank" rel="noreferrer">
            {link.verified && <BadgeCheck size={13} className="ok" />}{prettyUrl(link.url)}
          </a>
        )}
        {showReel && link.from_reel && (
          <button className="from-reel" onClick={() => showReel(link.from_reel!.id)}>
            from: {link.from_reel.title || link.from_reel.id}
          </button>
        )}
      </div>
      <div className="link-actions">
        {link.url && <a className="btn btn-sm btn-primary" href={link.url} target="_blank" rel="noreferrer"><ExternalLink size={13} /> Open</a>}
        {link.search_url && <a className="btn btn-sm" href={link.search_url} target="_blank" rel="noreferrer"><Search size={13} /> Search</a>}
      </div>
    </div>
  );
}

function prettyUrl(u: string) {
  return u.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}
