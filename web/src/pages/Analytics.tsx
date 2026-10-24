import { BrainCircuit, Loader2, MessageCircleQuestion, Play, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Analytics as AnalyticsData, api, AskResult } from "../api";
import { useApp } from "../App";
import { href } from "../router";

const PURPOSE_LABELS: Record<string, string> = { learn: "To learn", entertain: "Entertainment", inspire: "Inspiration", shop: "Shopping" };

export default function Analytics() {
  const { version, toast } = useApp();
  const [data, setData] = useState<AnalyticsData | null>(null);

  const load = () => api.analytics().then(setData).catch((e) => toast(e.message, "error"));
  useEffect(() => { load(); }, [version]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll while Laya computes signals.
  useEffect(() => {
    if (!data?.signals_job.running) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [data?.signals_job.running]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data) return <div className="page"><div className="loading">Loading…</div></div>;

  const job = data.signals_job;
  const categories = Object.keys(data.categories).length ? data.categories : data.signal_categories;
  const actionableYes = data.actionable.yes || 0;
  const actionableTotal = actionableYes + (data.actionable.no || 0);

  const runSignals = async () => {
    try {
      const r = await api.runSignals();
      toast(r.started ? `Laya is reading ${r.count} reels` : r.message || "Nothing to do");
      load();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <div className="page analytics">
      <header className="page-head">
        <div>
          <div className="eyebrow">What you save, and what it's good for</div>
          <h1>Analytics</h1>
        </div>
      </header>

      <div className="stats">
        <Stat label="Saved" value={data.total_reels.toLocaleString()} />
        <Stat label="Have text to read" value={data.with_text.toLocaleString()} />
        <Stat label="Read by Laya" value={data.with_signals.toLocaleString()} />
        <Stat label="Actionable" value={actionableTotal ? `${Math.round((actionableYes / actionableTotal) * 100)}%` : "–"}
              hint={actionableTotal ? `${actionableYes} of ${actionableTotal} teach something you can do` : "needs Laya signals"} />
      </div>

      <LayaPanel data={data} job={job} onRun={runSignals} />

      <div className="chart-grid">
        <section className="card chart-card wide">
          <h2>Saves per month</h2>
          <MonthBars months={data.saves_by_month} />
        </section>

        <section className="card chart-card">
          <h2>Categories</h2>
          <p className="muted small">{Object.keys(data.categories).length ? "From AI analysis" : "From Laya signals"}</p>
          <BarList data={categories} linkTo={(k) => href("library", { category: k })} />
        </section>

        <section className="card chart-card">
          <h2>Why you save</h2>
          <p className="muted small">Laya's read of each reel's purpose</p>
          <BarList data={data.purposes} label={(k) => PURPOSE_LABELS[k] || k} empty="Compute signals to see this." />
          <h3 className="chart-subhead">Worth coming back to</h3>
          <RevisitScale data={data.revisit} />
        </section>

        <section className="card chart-card">
          <h2>Kinds of reels</h2>
          <BarList data={data.content_types} label={(k) => k.replace(/_/g, " ")} empty="Compute signals to see this." max={10} />
        </section>

        <section className="card chart-card wide">
          <h2>Collections</h2>
          <CollectionsTable rows={data.collections} />
        </section>
      </div>

      <AskCard data={data} />
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function LayaPanel({ data, job, onRun }: { data: AnalyticsData; job: AnalyticsData["signals_job"]; onRun: () => void }) {
  if (!data.laya_available) {
    return (
      <div className="banner warn">
        <BrainCircuit size={18} />
        <div><strong>Laya isn't installed in this build,</strong> so signals and “Ask your library” are off. Install the <code>decisions</code> extra to enable them.</div>
      </div>
    );
  }
  if (job.running) {
    const pct = job.total ? (job.done / job.total) * 100 : 0;
    return (
      <div className="banner">
        <Loader2 size={18} className="spin" />
        <div style={{ flex: 1 }}>
          <strong>Laya is reading your reels…</strong> {job.done} of {job.total}
          <div className="progress big"><div style={{ width: `${pct}%` }} /></div>
        </div>
      </div>
    );
  }
  return (
    <div className="banner">
      <BrainCircuit size={18} />
      <div>
        <strong>Laya</strong> is a fast local decision model. It reads each reel's text and estimates its category,
        purpose, whether it's actionable and how worth revisiting it is. Free, and runs on this machine.
        {data.with_text < data.total_reels && (
          <> <span className="muted">{(data.total_reels - data.with_text).toLocaleString()} reels have no text yet; they need analyzing first.</span></>
        )}
        {job.error && <div className="bad small">Last run failed: {job.error}</div>}
      </div>
      <button className="btn btn-primary" onClick={onRun} disabled={!data.missing_signals}>
        <Play size={14} /> {data.missing_signals ? `Read ${data.missing_signals.toLocaleString()} reels` : "All read"}
      </button>
    </div>
  );
}

/* ---------- charts (single series, values on hover, table-friendly) */

function useTip() {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const el = tip && <div className="chart-tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>;
  const bind = (text: string) => ({
    onMouseMove: (e: React.MouseEvent) => {
      const box = (e.currentTarget.closest(".chart-card") as HTMLElement).getBoundingClientRect();
      setTip({ x: e.clientX - box.left + 12, y: e.clientY - box.top - 34, text });
    },
    onMouseLeave: () => setTip(null),
  });
  return { el, bind };
}

function MonthBars({ months }: { months: AnalyticsData["saves_by_month"] }) {
  const { el, bind } = useTip();
  if (!months.length) return <div className="empty-small">No save dates yet. They come from the Instagram export.</div>;
  const max = Math.max(...months.map((m) => m.total));
  const fmt = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  const peak = months.reduce((a, b) => (b.total > a.total ? b : a));
  const labelEvery = Math.max(1, Math.ceil(months.length / 12));
  return (
    <div className="month-chart">
      {el}
      <div className="month-axis-max muted small">{max}</div>
      <div className="month-bars" role="img" aria-label={`Saves per month, peak ${peak.total} in ${fmt(peak.month)}`}>
        {months.map((m, i) => {
          const top = Object.entries(m.by_category).filter(([c]) => c !== "(not analyzed)").sort((a, b) => b[1] - a[1])[0];
          const text = `${fmt(m.month)}: ${m.total} saved${top ? ` · most: ${top[0]}` : ""}`;
          return (
            <div key={m.month} className="month-col" {...bind(text)}>
              <div className="month-bar" style={{ height: `${Math.max(2, (m.total / max) * 100)}%` }} />
              <div className="month-label">{i % labelEvery === 0 ? fmt(m.month) : ""}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BarList({ data, label = (k) => k, linkTo, empty = "Nothing yet.", max = 12 }: {
  data: Record<string, number>; label?: (k: string) => string; linkTo?: (k: string) => string; empty?: string; max?: number;
}) {
  const { el, bind } = useTip();
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return <div className="empty-small">{empty}</div>;
  const shown = entries.slice(0, max);
  const rest = entries.slice(max).reduce((s, [, n]) => s + n, 0);
  if (rest) shown.push(["Other", rest]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  const top = shown[0][1];
  return (
    <div className="barlist">
      {el}
      {shown.map(([k, n]) => {
        const row = (
          <>
            <span className="barlist-label truncate">{label(k)}</span>
            <span className="barlist-track"><span className="barlist-bar" style={{ width: `${(n / top) * 100}%` }} /></span>
            <span className="barlist-value">{n.toLocaleString()}</span>
          </>
        );
        const tip = `${label(k)}: ${n.toLocaleString()} (${Math.round((n / total) * 100)}%)`;
        return linkTo && k !== "Other"
          ? <a key={k} className="barlist-row" href={linkTo(k)} {...bind(tip)}>{row}</a>
          : <div key={k} className="barlist-row" {...bind(tip)}>{row}</div>;
      })}
    </div>
  );
}

function RevisitScale({ data }: { data: Record<string, number> }) {
  const { el, bind } = useTip();
  const levels = ["low", "medium", "high"];
  const total = levels.reduce((s, l) => s + (data[l] || 0), 0);
  if (!total) return <div className="empty-small">Compute signals to see this.</div>;
  return (
    <div className="revisit">
      {el}
      <div className="revisit-bar" role="img" aria-label={levels.map((l) => `${l}: ${data[l] || 0}`).join(", ")}>
        {levels.map((l) => (data[l] ? (
          <span key={l} className={`revisit-seg r-${l}`} style={{ flexGrow: data[l] }}
                {...bind(`${l} value: ${data[l]} (${Math.round((data[l] / total) * 100)}%)`)} />
        ) : null))}
      </div>
      <div className="revisit-legend">
        {levels.map((l) => (
          <span key={l}><i className={`r-${l}`} />{l} <strong>{Math.round(((data[l] || 0) / total) * 100)}%</strong></span>
        ))}
      </div>
    </div>
  );
}

function CollectionsTable({ rows }: { rows: AnalyticsData["collections"] }) {
  if (!rows.length) return <div className="empty-small">No collections yet.</div>;
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr><th>Collection</th><th className="num">Reels</th><th>Analyzed</th><th>Main category</th><th className="num">Actionable</th></tr>
        </thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.name}>
              <td><a href={href("library", { collection: c.name })}>{c.name}</a></td>
              <td className="num">{c.reels}</td>
              <td>
                <span className="mini-progress"><span style={{ width: `${(c.analyzed / c.reels) * 100}%` }} /></span>
                <span className="muted small"> {Math.round((c.analyzed / c.reels) * 100)}%</span>
              </td>
              <td>{c.top_category || <span className="muted">–</span>}</td>
              <td className="num">{c.with_signals ? `${Math.round((c.actionable / c.with_signals) * 100)}%` : <span className="muted">–</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ---------- Ask your library */

const EXAMPLES = [
  { q: "Is this an activity to do with a toddler?", t: "yes_no" },
  { q: "Does this need special equipment or ingredients?", t: "yes_no" },
  { q: "Who is this mainly for?", t: "choice", o: "kids, parents, investors, developers, everyone" },
  { q: "How much effort does it take to try this?", t: "scale", o: "very little, some, a lot" },
];

function AskCard({ data }: { data: AnalyticsData }) {
  const { toast, openReel, overview } = useApp();
  const [question, setQuestion] = useState("");
  const [type, setType] = useState("yes_no");
  const [options, setOptions] = useState("");
  const [collection, setCollection] = useState("");
  const [limit, setLimit] = useState(200);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AskResult | null>(null);
  const [filter, setFilter] = useState<string | null>(null);

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    setBusy(true);
    setFilter(null);
    try {
      setResult(await api.ask({
        question, answer_type: type, limit, collection: collection || undefined,
        options: type === "yes_no" ? undefined : options.split(",").map((o) => o.trim()).filter(Boolean),
      }));
    } catch (err) { toast((err as Error).message, "error"); }
    finally { setBusy(false); }
  };

  const shown = useMemo(() => (result?.results || []).filter((r) => !filter || r.answer === filter), [result, filter]);

  return (
    <section className="card ask-card">
      <h2><MessageCircleQuestion size={19} /> Ask your library</h2>
      <p className="muted">
        Ask one question and Laya answers it for every reel in seconds, then ranks them. Answers are quick
        estimates: great for finding and sorting, worth a glance before relying on them.
      </p>
      {!data.laya_available ? <div className="muted">Needs Laya.</div> : (
        <>
          <form className="ask-form" onSubmit={run}>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Is this an activity to do with a toddler?" required />
            <select value={type} onChange={(e) => setType(e.target.value)}>
              <option value="yes_no">Yes / no</option>
              <option value="choice">Pick one</option>
              <option value="scale">Scale</option>
            </select>
            {type !== "yes_no" && (
              <input value={options} onChange={(e) => setOptions(e.target.value)}
                     placeholder={type === "choice" ? "Options, comma separated" : "Levels, lowest first (default: low, medium, high)"}
                     required={type === "choice"} />
            )}
            <select value={collection} onChange={(e) => setCollection(e.target.value)}>
              <option value="">All collections</option>
              {overview?.collections.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select>
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} title="How many reels to ask (newest first)">
              {[50, 200, 500, 2000].map((n) => <option key={n} value={n}>{n} reels</option>)}
            </select>
            <button className="btn btn-primary" disabled={busy}>
              {busy ? <Loader2 size={15} className="spin" /> : <RefreshCw size={15} />} Ask
            </button>
          </form>
          <div className="chips ask-examples">
            <span className="muted small">Try:</span>
            {EXAMPLES.map((x) => (
              <button key={x.q} className="chip chip-btn" onClick={() => { setQuestion(x.q); setType(x.t); setOptions(x.o || ""); }}>{x.q}</button>
            ))}
          </div>

          {busy && <div className="muted small">Asking… the first question also loads the model (up to a minute).</div>}
          {result && (
            <div className="ask-results">
              <div className="row between wrap gap">
                <div className="muted small">
                  Asked {result.asked} reels in {result.seconds}s
                  {result.skipped_without_text ? ` · ${result.skipped_without_text} skipped (no text yet)` : ""}
                </div>
                {result.summary && (
                  <div className="chips">
                    <button className={`chip chip-btn ${!filter ? "on" : ""}`} onClick={() => setFilter(null)}>All</button>
                    {Object.entries(result.summary).map(([a, n]) => (
                      <button key={a} className={`chip chip-btn ${filter === a ? "on" : ""}`} onClick={() => setFilter(filter === a ? null : a)}>
                        {a} <span className="muted">{n}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {shown.slice(0, 100).map((r) => (
                <button key={r.reel.id} className="ask-row" onClick={() => openReel(r.reel.id)}>
                  {r.reel.thumbnail ? <img src={r.reel.thumbnail} alt="" /> : <span className="ask-thumb" />}
                  <span className="ask-main">
                    <strong className="truncate">{r.reel.title || (r.reel.creator ? `Reel by @${r.reel.creator}` : r.reel.id)}</strong>
                    <span className="muted small truncate">{r.reel.summary || r.reel.collections?.join(", ")}</span>
                  </span>
                  <span className="ask-answer">
                    {result.answer_type === "yes_no" ? (
                      <>
                        <span className="mini-progress"><span style={{ width: `${(r.probability || 0) * 100}%` }} /></span>
                        <span className="small">{Math.round((r.probability || 0) * 100)}% yes</span>
                      </>
                    ) : <span className="chip chip-soft">{r.answer}</span>}
                  </span>
                </button>
              ))}
              {shown.length > 100 && <div className="muted small center">Showing the top 100 of {shown.length}.</div>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
