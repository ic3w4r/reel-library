import { Copy, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, LinkItem } from "../api";
import { useApp } from "../App";
import { LinkRow } from "../components/ReelDrawer";

export default function Links({ params }: { params: URLSearchParams }) {
  const { overview, version, openReel, toast } = useApp();
  const [q, setQ] = useState(params.get("q") || "");
  const [debounced, setDebounced] = useState(q);
  const [kind, setKind] = useState("");
  const [category, setCategory] = useState("");
  const [verifiedOnly, setVerifiedOnly] = useState(false);
  const [links, setLinks] = useState<LinkItem[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    api.links({ q: debounced, kind, category, verified_only: verifiedOnly || undefined, limit: 500 })
      .then((r) => { setLinks(r.links); setTotal(r.total); })
      .catch((e) => toast(e.message, "error"));
  }, [debounced, kind, category, verifiedOnly, version, toast]);

  const copyMarkdown = async () => {
    const md = links.map((l) => {
      const target = l.url || l.search_url;
      const from = l.from_reel ? ` (from [reel](${l.from_reel.url}))` : "";
      return `- [${l.name}](${target})${l.description ? ` — ${l.description}` : ""}${from}`;
    }).join("\n");
    await navigator.clipboard.writeText(md);
    toast(`Copied ${links.length} links as Markdown`);
  };

  const kinds = overview?.link_kinds || {};

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <div className="eyebrow">Everything mentioned in your reels</div>
          <h1>Links & resources</h1>
        </div>
        <button className="btn" onClick={copyMarkdown} disabled={!links.length}><Copy size={15} /> Copy as Markdown</button>
      </header>

      <div className="toolbar">
        <label className="search">
          <Search size={17} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a tool, product, place, book…" />
          {q && <button className="icon-btn" onClick={() => setQ("")} aria-label="Clear"><X size={15} /></button>}
        </label>
        {overview && (
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">Any category</option>
            {Object.keys(overview.categories).map((c) => <option key={c}>{c}</option>)}
          </select>
        )}
        <label className="toggle">
          <input type="checkbox" checked={verifiedOnly} onChange={(e) => setVerifiedOnly(e.target.checked)} />
          Working links only
        </label>
      </div>

      <div className="chips filter-chips">
        <button className={`chip chip-btn ${kind === "" ? "on" : ""}`} onClick={() => setKind("")}>All</button>
        {Object.entries(kinds).map(([k, n]) => (
          <button key={k} className={`chip chip-btn ${kind === k ? "on" : ""}`} onClick={() => setKind(k === kind ? "" : k)}>
            {k} <span className="muted">{n}</span>
          </button>
        ))}
      </div>

      <div className="result-count">{total} {total === 1 ? "resource" : "resources"}</div>

      {links.length === 0
        ? <div className="empty-small">No links yet. They appear here as reels get analyzed.</div>
        : <div className="link-list card">{links.map((l, i) => <LinkRow key={i} link={l} showReel={openReel} />)}</div>}
    </div>
  );
}
