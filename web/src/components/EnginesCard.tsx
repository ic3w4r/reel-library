import { CheckCircle2, ChevronDown, Cpu, ExternalLink, Pencil, Plus, RefreshCw, Trash2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, Engine, EnginesState } from "../api";
import { useApp } from "../App";

type TestResult = { ok: boolean; message: string; busy?: boolean };

export default function EnginesCard() {
  const { toast, setSettings } = useApp();
  const [state, setState] = useState<EnginesState | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [tests, setTests] = useState<Record<string, TestResult>>({});

  const apply = (s: EnginesState) => {
    setState(s);
    api.settings().then(setSettings).catch(() => {});
  };

  useEffect(() => { api.engines().then(setState).catch((e) => toast(e.message, "error")); }, [toast]);

  if (!state) return <section className="card"><div className="loading">Loading engines…</div></section>;

  const run = async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    try {
      const r = await fn();
      if (ok) toast(ok);
      return r;
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const add = async (preset: string) => {
    const r = await run(() => api.createEngine({ preset }));
    if (r) { apply(r); setAdding(false); setEditing(r.created || null); }
  };

  const test = async (id: string) => {
    setTests((t) => ({ ...t, [id]: { ok: false, message: "Testing…", busy: true } }));
    const r = await api.testEngine(id).catch((e) => ({ ok: false, message: (e as Error).message }));
    setTests((t) => ({ ...t, [id]: r }));
  };

  const setRoles = async (active: string, fallback: string | null) => {
    const r = await run(() => api.setEngineRoles(active, fallback), "Saved");
    if (r) apply(r);
  };

  return (
    <section className="card">
      <h2><Cpu size={19} /> AI engines</h2>
      <p className="muted">
        Any of these can watch and summarize your reels. The <strong>primary</strong> engine does the work; the
        optional <strong>fallback</strong> takes over automatically if the primary fails (no credits, bad key, model gone).
      </p>

      {state.engines.length > 0 && (
        <div className="field-grid roles">
          <div className="field">
            <label>Primary engine</label>
            <select value={state.active || ""} onChange={(e) => setRoles(e.target.value, state.fallback)}>
              {state.engines.map((e) => <option key={e.id} value={e.id}>{e.label}{e.ready ? "" : " (not set up)"}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Fallback engine</label>
            <select value={state.fallback || ""} onChange={(e) => setRoles(state.active!, e.target.value || null)}>
              <option value="">None</option>
              {state.engines.filter((e) => e.id !== state.active).map((e) =>
                <option key={e.id} value={e.id}>{e.label}{e.ready ? "" : " (not set up)"}</option>)}
            </select>
          </div>
        </div>
      )}

      <div className="engine-list">
        {state.engines.map((e) => (
          <div key={e.id} className={`engine ${editing === e.id ? "open" : ""}`}>
            <div className="engine-row">
              <span className={`engine-avatar p-${e.preset}`}>{e.name.slice(0, 1).toUpperCase()}</span>
              <div className="engine-main">
                <div className="engine-name">
                  {e.name}
                  {state.active === e.id && <span className="chip role-primary">Primary</span>}
                  {state.fallback === e.id && <span className="chip chip-outline">Fallback</span>}
                </div>
                <div className="muted small truncate">
                  {e.model || "no model chosen"}
                  {e.type === "openai" && e.base_url ? ` · ${e.base_url.replace(/^https?:\/\//, "").replace(/\/$/, "")}` : ""}
                </div>
                {tests[e.id] && (
                  <div className={`small ${tests[e.id].busy ? "muted" : tests[e.id].ok ? "ok" : "bad"}`}>
                    {!tests[e.id].busy && (tests[e.id].ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />)} {tests[e.id].message}
                  </div>
                )}
              </div>
              {!e.ready && <span className="chip chip-warn">Needs setup</span>}
              <div className="engine-actions">
                <button className="btn btn-sm" onClick={() => test(e.id)} disabled={!e.ready || tests[e.id]?.busy}>Test</button>
                <button className="icon-btn" onClick={() => setEditing(editing === e.id ? null : e.id)} aria-label="Edit"><Pencil size={15} /></button>
                <button className="icon-btn" aria-label="Delete" onClick={async () => {
                  if (!confirm(`Remove ${e.name}?`)) return;
                  const r = await run(() => api.deleteEngine(e.id), "Engine removed");
                  if (r) apply(r);
                }}><Trash2 size={15} /></button>
              </div>
            </div>
            {editing === e.id && (
              <EngineForm engine={e} preset={state.presets[e.preset]} onDone={(r) => { if (r) apply(r); setEditing(null); }} />
            )}
          </div>
        ))}
      </div>

      {adding ? (
        <div className="preset-grid">
          {Object.entries(state.presets).map(([key, p]) => (
            <button key={key} className="preset" onClick={() => add(key)}>
              <span className={`engine-avatar p-${key}`}>{p.label.slice(0, 1)}</span>
              <span>
                <strong>{p.label}</strong>
                <small className="muted">{p.needs_key ? "API key" : "No key needed"}{p.type === "anthropic" ? " · native" : " · OpenAI-compatible"}</small>
              </span>
            </button>
          ))}
          <button className="btn btn-ghost" onClick={() => setAdding(false)}>Cancel</button>
        </div>
      ) : (
        <button className="btn" onClick={() => setAdding(true)}><Plus size={15} /> Add engine</button>
      )}
    </section>
  );
}

function EngineForm({ engine, preset, onDone }: {
  engine: Engine;
  preset?: { key_url: string; needs_key: boolean; key_env: string };
  onDone: (r?: EnginesState) => void;
}) {
  const { toast } = useApp();
  const [name, setName] = useState(engine.name);
  const [baseUrl, setBaseUrl] = useState(engine.base_url);
  const [key, setKey] = useState("");
  const [model, setModel] = useState(engine.model);
  const [effort, setEffort] = useState(engine.effort || "medium");
  const [vision, setVision] = useState(engine.vision);
  const [jsonMode, setJsonMode] = useState(engine.json_mode || "auto");
  const [models, setModels] = useState<string[] | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const body = () => ({
    name, model, effort, vision, json_mode: jsonMode,
    ...(engine.type === "openai" ? { base_url: baseUrl } : {}),
    ...(key.trim() ? { api_key: key.trim() } : {}),
  });

  const fetchModels = async () => {
    setLoadingModels(true);
    try {
      // Save first so the server lists models with the key / URL just typed.
      await api.updateEngine(engine.id, body());
      setKey("");
      const r = await api.engineModels(engine.id);
      setModels(r.models);
      if (!r.models.length) toast("The server returned no models", "error");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setLoadingModels(false); }
  };

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      onDone(await api.updateEngine(engine.id, body()));
      toast("Engine saved");
    } catch (err) { toast((err as Error).message, "error"); }
  };

  return (
    <form className="engine-form" onSubmit={save}>
      <div className="field-grid">
        <div className="field">
          <label>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        {engine.type === "openai" && (
          <div className="field">
            <label>Base URL</label>
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://…/v1" required />
          </div>
        )}
      </div>
      {engine.type === "laya" ? (
        <p className="muted small laya-note">
          Runs on this machine, no key needed. Laya can't write summaries: it files each reel (category, type)
          and adds signals from the reel's caption and speech, so it works best as a <strong>fallback</strong> behind an
          LLM engine, or to file a big backlog for free. First use downloads its model (~1–2 GB).
        </p>
      ) : (<>
      <div className="field">
        <label>
          API key {preset?.needs_key === false && <span className="muted">(optional)</span>}
          {preset?.key_url && <a className="key-link" href={preset.key_url} target="_blank" rel="noreferrer">get one <ExternalLink size={11} /></a>}
        </label>
        <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off"
               placeholder={engine.key_set ? `Saved: ${engine.key_hint}${engine.key_from_env ? " (from environment)" : ""} — type to replace` : "Paste API key"} />
      </div>
      <div className="field">
        <label>Model</label>
        <div className="row gap">
          {models && models.length ? (
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              {!models.includes(model) && model && <option value={model}>{model}</option>}
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          ) : (
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="model id" required />
          )}
          <button type="button" className="btn" onClick={fetchModels} disabled={loadingModels}>
            <RefreshCw size={14} className={loadingModels ? "spin" : ""} /> Fetch models
          </button>
        </div>
        <small className="muted">Pick a model that can see images (vision) for the best results.</small>
      </div>
      </>)}
      {engine.type === "anthropic" && (
        <div className="field">
          <label>Effort</label>
          <select value={effort} onChange={(e) => setEffort(e.target.value)}>
            {["low", "medium", "high"].map((x) => <option key={x}>{x}</option>)}
          </select>
          <small className="muted">Higher = more thorough, slower, costs more.</small>
        </div>
      )}
      {engine.type !== "laya" && <button type="button" className="linklike advanced-toggle" onClick={() => setShowAdvanced(!showAdvanced)}>
        Advanced <ChevronDown size={14} style={{ transform: showAdvanced ? "rotate(180deg)" : undefined }} />
      </button>}
      {showAdvanced && engine.type !== "laya" && (
        <div className="field-grid">
          <label className="toggle">
            <input type="checkbox" checked={vision} onChange={(e) => setVision(e.target.checked)} />
            Send video frames (model supports images)
          </label>
          {engine.type === "openai" && (
            <div className="field">
              <label>JSON output mode</label>
              <select value={jsonMode} onChange={(e) => setJsonMode(e.target.value as Engine["json_mode"])}>
                <option value="auto">Auto-detect</option>
                <option value="schema">Strict JSON schema</option>
                <option value="object">JSON mode</option>
                <option value="none">Prompt only</option>
              </select>
            </div>
          )}
        </div>
      )}
      <div className="row gap">
        <button className="btn btn-primary" type="submit">Save</button>
        <button className="btn btn-ghost" type="button" onClick={() => onDone()}>Cancel</button>
      </div>
    </form>
  );
}
