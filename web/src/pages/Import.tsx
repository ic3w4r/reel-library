import { AlertTriangle, CheckCircle2, FileArchive, Link as LinkIcon, Loader2, Play, RotateCcw, Square, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { api, ImportResult } from "../api";
import { useApp } from "../App";
import { href } from "../router";

export default function Import() {
  const { settings, jobs, refresh, refreshJobs, toast, openReel } = useApp();
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [autoAnalyze, setAutoAnalyze] = useState(true);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [url, setUrl] = useState("");
  const [collection, setCollection] = useState("");
  const [batch, setBatch] = useState(20);
  const fileRef = useRef<HTMLInputElement>(null);

  const lib = jobs?.library || {};
  const hasKey = settings?.ai_ready;
  const hasLogin = settings?.instagram_login;

  const upload = async (file: File) => {
    setUploading(true);
    setResult(null);
    try {
      const r = await api.importExport(file, autoAnalyze && !!hasKey);
      setResult(r);
      toast(`Imported ${r.new_reels} new reels`);
      refresh();
      refreshJobs();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setUploading(false);
    }
  };

  const addUrl = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api.addReel(url.trim(), collection.trim() || undefined, !!hasKey);
      toast(r.queued ? "Added and queued for analysis" : "Added to library");
      setUrl("");
      refresh();
      refreshJobs();
      openReel(r.id);
    } catch (err) { toast((err as Error).message, "error"); }
  };

  const analyze = async (body: Parameters<typeof api.analyze>[0]) => {
    try {
      const r = await api.analyze(body);
      toast(r.queued ? `Queued ${r.queued} reels` : "Nothing to analyze");
      refreshJobs();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const progress = jobs && jobs.batch_total ? ((jobs.done + jobs.failed) / jobs.batch_total) * 100 : 0;

  return (
    <div className="page narrow">
      <header className="page-head">
        <div>
          <div className="eyebrow">Bring reels in, then let AI watch them</div>
          <h1>Add & analyze</h1>
        </div>
      </header>

      {jobs?.halted && (
        <div className="banner error">
          <XCircle size={18} />
          <div><strong>Analysis stopped.</strong> {jobs.halted} Your reels are still waiting and nothing was marked failed.</div>
          <a className="btn" href={href("settings")}>Open settings</a>
        </div>
      )}

      {(!hasKey || !hasLogin) && settings && (
        <div className="banner warn">
          <AlertTriangle size={18} />
          <div>
            {!hasKey && <div><strong>Set up an AI engine</strong> (Claude, OpenAI, Gemini, a local model…) so reels can be analyzed.</div>}
            {!hasLogin && <div><strong>Connect your Instagram login</strong> — Instagram usually blocks video downloads without it.</div>}
          </div>
          <a className="btn" href={href("settings")}>Open settings</a>
        </div>
      )}

      <section className="card">
        <h2><FileArchive size={19} /> Import your Instagram export</h2>
        <p className="muted">Contains every saved post <em>and</em> your collections. Re-importing a newer export only adds what's new.</p>
        <div
          className={`dropzone ${dragging ? "drag" : ""}`}
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) upload(f); }}
        >
          {uploading
            ? <><Loader2 className="spin" size={26} /><div>Importing…</div></>
            : <><FileArchive size={26} /><div><strong>Drop the export .zip here</strong> or click to choose</div>
                <div className="muted small">or saved_posts.json / saved_collections.json</div></>}
          <input ref={fileRef} type="file" accept=".zip,.json" hidden
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
        </div>
        <label className="toggle">
          <input type="checkbox" checked={autoAnalyze} onChange={(e) => setAutoAnalyze(e.target.checked)} disabled={!hasKey} />
          Start analyzing right after import
        </label>
        {result && (
          <div className="import-result">
            <CheckCircle2 size={18} className="ok" />
            <div>
              Found <strong>{result.reels_seen}</strong> saved items, <strong>{result.new_reels}</strong> new.
              {result.collections.length > 0 && <> Collections: {result.collections.join(", ")}.</>}
              {result.queued ? <> Queued <strong>{result.queued}</strong> for analysis.</> : null}
            </div>
          </div>
        )}
        <details className="howto">
          <summary>How do I get the export?</summary>
          <ol>
            <li>Instagram → <strong>Settings</strong> → <strong>Accounts Center</strong> → <strong>Your information and permissions</strong>.</li>
            <li><strong>Download your information</strong> → choose your Instagram account → <strong>Some of your information</strong> → tick <strong>Saved</strong>.</li>
            <li>Download to device, format <strong>JSON</strong> (not HTML), date range <strong>All time</strong>.</li>
            <li>Instagram emails you when it's ready (minutes to a few hours). Drop the zip above.</li>
          </ol>
        </details>
      </section>

      <section className="card">
        <h2><LinkIcon size={19} /> Add a single reel</h2>
        <form className="add-form" onSubmit={addUrl}>
          <input value={url} onChange={(e) => setUrl(e.target.value)} required
                 placeholder="https://www.instagram.com/reel/…" />
          <input value={collection} onChange={(e) => setCollection(e.target.value)} placeholder="Collection (optional)" />
          <button className="btn btn-primary" type="submit">Add</button>
        </form>
      </section>

      <section className="card">
        <h2><Play size={19} /> Analysis queue</h2>
        <div className="queue-stats">
          <span><strong>{lib.analyzed || 0}</strong> analyzed</span>
          <span><strong>{lib.pending || 0}</strong> waiting</span>
          <span className={lib.failed ? "bad" : ""}><strong>{lib.failed || 0}</strong> failed</span>
        </div>

        {jobs?.running ? (
          <div className="queue-live">
            <div className="row between">
              <div>
                <Loader2 size={15} className="spin" /> Analyzing{" "}
                {jobs.current ? <button className="linklike" onClick={() => openReel(jobs.current!.id)}>{jobs.current.creator ? `@${jobs.current.creator}` : jobs.current.id}</button> : "…"}
                {jobs.current && <span className="muted"> · {Math.round(jobs.current.elapsed_seconds)}s</span>}
              </div>
              <div className="muted">{jobs.done + jobs.failed} / {jobs.batch_total} · {jobs.queued} left</div>
            </div>
            <div className="progress big"><div style={{ width: `${progress}%` }} /></div>
            <button className="btn btn-ghost" onClick={async () => { await api.cancelJobs(); refreshJobs(); }}>
              <Square size={14} /> Stop after current reel
            </button>
          </div>
        ) : (
          <div className="row gap wrap">
            <div className="split-btn">
              <button className="btn btn-primary" disabled={!lib.pending || !hasKey} onClick={() => analyze({ limit: batch })}>
                <Play size={15} /> Analyze next
              </button>
              <select value={batch} onChange={(e) => setBatch(Number(e.target.value))}>
                {[5, 10, 20, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <button className="btn" disabled={!lib.pending || !hasKey} onClick={() => analyze({ limit: 5000 })}>
              Analyze all {lib.pending || 0}
            </button>
            <button className="btn" disabled={!lib.failed || !hasKey} onClick={() => analyze({ limit: 5000, retry_failed: true })}>
              <RotateCcw size={15} /> Retry failed
            </button>
          </div>
        )}
        <p className="muted small">Each reel takes about 20–60 seconds: download → keyframes → speech-to-text → your AI engine. The first run also downloads the speech model (~500 MB).</p>

        {jobs && jobs.recent.length > 0 && (
          <div className="recent">
            <h3>Recently finished</h3>
            {jobs.recent.map((r) => (
              <button key={`${r.id}-${r.finished_at}`} className="recent-row" onClick={() => openReel(r.id)}>
                {r.status === "analyzed" ? <CheckCircle2 size={15} className="ok" /> : <XCircle size={15} className="bad" />}
                <span className="truncate">{r.title || r.id}</span>
                <span className="muted small truncate">{r.status === "analyzed" ? r.category : r.error}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
