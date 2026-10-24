import { Search, Sparkles, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, ReelSummary } from "../api";
import { useApp } from "../App";
import ReelCard, { reelState } from "../components/ReelCard";
import { href, navigate } from "../router";

const PAGE = 48;

export default function Library({ params }: { params: URLSearchParams }) {
  const { overview, jobs, version, toast, refreshJobs } = useApp();
  const collection = params.get("collection") || "";
  const category = params.get("category") || "";
  const [q, setQ] = useState(params.get("q") || "");
  const [debounced, setDebounced] = useState(q);
  const [contentType, setContentType] = useState("");
  const [status, setStatus] = useState("");
  const [reels, setReels] = useState<ReelSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  const filters = { q: debounced, collection, category, content_type: contentType, status };
  const key = JSON.stringify(filters);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.reels({ ...filters, limit: Math.max(PAGE, reels.length), offset: 0 })
      .then((r) => { if (alive) { setReels(r.reels); setTotal(r.total); } })
      .catch((e) => toast(e.message, "error"))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version]);

  const loadMore = () =>
    api.reels({ ...filters, limit: PAGE, offset: reels.length }).then((r) => setReels((x) => [...x, ...r.reels]));

  const queued = useMemo(() => new Set(jobs?.queued_ids || []), [jobs?.queued_ids]);
  const pending = overview?.by_status?.pending || 0;

  const title = collection === "__none__" ? "Not in a collection" : collection || category || "All saved";
  const subtitle = collection && collection !== "__none__"
    ? "Instagram collection"
    : category ? "Category" : "Every reel and post you've saved";

  const analyzePending = async () => {
    try {
      const r = await api.analyze({ limit: 5000, collection: collection && collection !== "__none__" ? collection : undefined });
      toast(r.queued ? `Queued ${r.queued} reels for analysis` : "Nothing to analyze");
      refreshJobs();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  if (overview && overview.total_reels === 0) return <EmptyLibrary />;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">{subtitle}</div>
          <h1>{title}</h1>
        </div>
        {(collection || category) && (
          <a className="btn btn-ghost" href={href("library")}><X size={15} /> Clear filter</a>
        )}
      </header>

      {overview && !collection && !category && (
        <div className="stats">
          <Stat label="Saved" value={overview.total_reels} />
          <Stat label="Analyzed" value={overview.by_status.analyzed || 0} />
          <Stat label="Collections" value={overview.collections.length} />
          <Stat label="Links found" value={overview.extracted_links} />
        </div>
      )}

      {pending > 0 && !jobs?.running && (
        <div className="banner">
          <Sparkles size={18} />
          <div><strong>{pending} reels haven't been analyzed yet.</strong> Analysis watches each video, transcribes it and pulls out the links.</div>
          <button className="btn btn-primary" onClick={analyzePending}>
            Analyze {collection && collection !== "__none__" ? "this collection" : "all"}
          </button>
        </div>
      )}

      <div className="toolbar">
        <label className="search">
          <Search size={17} />
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search summaries, transcripts, captions, links…" autoFocus />
          {q && <button className="icon-btn" onClick={() => setQ("")} aria-label="Clear"><X size={15} /></button>}
        </label>
        {!category && overview && (
          <select value="" onChange={(e) => navigate("library", { category: e.target.value, collection: collection || undefined })}>
            <option value="">Any category</option>
            {Object.keys(overview.categories).map((c) => <option key={c}>{c}</option>)}
          </select>
        )}
        {overview && Object.keys(overview.content_types).length > 0 && (
          <select value={contentType} onChange={(e) => setContentType(e.target.value)}>
            <option value="">Any type</option>
            {Object.keys(overview.content_types).map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
          </select>
        )}
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          <option value="analyzed">Analyzed</option>
          <option value="pending">Not analyzed</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      <div className="result-count">
        {loading ? "Loading…" : `${total} ${total === 1 ? "reel" : "reels"}${debounced ? ` matching “${debounced}”` : ""}`}
      </div>

      {!loading && reels.length === 0 ? (
        <div className="empty-small">No reels match. Try different words or clear the filters.</div>
      ) : (
        <div className="grid">
          {reels.map((r) => <ReelCard key={r.id} reel={r} state={reelState(r, queued, jobs?.current?.id)} />)}
        </div>
      )}

      {reels.length < total && (
        <div className="center"><button className="btn" onClick={loadMore}>Load more</button></div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="stat"><div className="stat-value">{value.toLocaleString()}</div><div className="stat-label">{label}</div></div>;
}

function EmptyLibrary() {
  return (
    <div className="page">
      <div className="empty">
        <div className="empty-art"><Upload size={34} /></div>
        <h1>Bring in your saved reels</h1>
        <p>Upload your Instagram data export (it contains every saved post and your collections), or add reels one link at a time.</p>
        <a className="btn btn-primary btn-lg" href={href("import")}>Get started</a>
      </div>
    </div>
  );
}
