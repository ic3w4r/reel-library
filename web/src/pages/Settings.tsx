import { Bot, CheckCircle2, Copy, Instagram, SlidersHorizontal, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import EnginesCard from "../components/EnginesCard";

export default function SettingsPage() {
  const { settings, setSettings, toast } = useApp();
  const [session, setSession] = useState("");
  const cookieRef = useRef<HTMLInputElement>(null);

  if (!settings) return <div className="page"><div className="loading">Loading…</div></div>;

  const save = async (body: Parameters<typeof api.saveSettings>[0], msg = "Saved") => {
    try {
      setSettings(await api.saveSettings(body));
      toast(msg);
    } catch (e) { toast((e as Error).message, "error"); }
  };


  const mcpUrl = `${window.location.origin}/mcp`;
  const claudeCmd = `claude mcp add --transport http --scope user instagram ${mcpUrl}`;
  const jsonConfig = JSON.stringify({ mcpServers: { instagram: { url: mcpUrl } } }, null, 2);
  const copy = async (text: string) => { await navigator.clipboard.writeText(text); toast("Copied"); };

  return (
    <div className="page narrow">
      <header className="page-head">
        <div><div className="eyebrow">Configuration</div><h1>Settings</h1></div>
      </header>

      <EnginesCard />

      <section className="card">
        <h2><Instagram size={19} /> Instagram login</h2>
        <p className="muted">
          Instagram only serves reel videos to logged-in users. This app never sees your password — it uses your
          browser's session cookie, stored only in this app's data folder.
        </p>
        <div className={`status-line ${settings.instagram_login ? "ok" : "bad"}`}>
          {settings.instagram_login ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
          {settings.instagram_login ? `Connected (${settings.instagram_cookie_source})` : "Not connected"}
          {settings.instagram_cookie_source === "uploaded" && (
            <button className="btn btn-sm btn-ghost" onClick={async () => setSettings(await api.clearInstagram())}>Disconnect</button>
          )}
        </div>
        <div className="field">
          <label>Paste your <code>sessionid</code> cookie</label>
          <form className="row gap" onSubmit={async (e) => {
            e.preventDefault();
            try { setSettings(await api.setInstagramSession(session)); setSession(""); toast("Instagram connected"); }
            catch (err) { toast((err as Error).message, "error"); }
          }}>
            <input type="password" value={session} onChange={(e) => setSession(e.target.value)} placeholder="sessionid value" autoComplete="off" />
            <button className="btn btn-primary" disabled={!session.trim()}>Connect</button>
          </form>
          <details className="howto">
            <summary>Where do I find it?</summary>
            <ol>
              <li>In Chrome, open <strong>instagram.com</strong> while logged in.</li>
              <li>Press <kbd>⌥⌘I</kbd> (Mac) or <kbd>F12</kbd> to open DevTools → <strong>Application</strong> tab.</li>
              <li>Left side: <strong>Cookies → https://www.instagram.com</strong>. Copy the <strong>Value</strong> of <code>sessionid</code>.</li>
              <li>Treat it like a password. Logging out of Instagram in Chrome invalidates it.</li>
            </ol>
          </details>
        </div>
        <div className="row gap">
          <span className="muted small">Or upload a cookies.txt export:</span>
          <button className="btn btn-sm" onClick={() => cookieRef.current?.click()}>Upload cookies.txt</button>
          <input ref={cookieRef} type="file" accept=".txt" hidden onChange={async (e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (!f) return;
            try { setSettings(await api.uploadCookies(f)); toast("Cookies uploaded"); }
            catch (err) { toast((err as Error).message, "error"); }
          }} />
        </div>
      </section>

      <section className="card">
        <h2><SlidersHorizontal size={19} /> Video analysis</h2>
        <div className="field-grid">
          <div className="field">
            <label>Speech-to-text model</label>
            <select value={settings.whisper_model} onChange={(e) => save({ whisper_model: e.target.value })}>
              {settings.options.whisper_models.map((x) => <option key={x}>{x}</option>)}
            </select>
            <small className="muted">“small” is a good balance; “medium” is better for non-English.</small>
          </div>
          <div className="field">
            <label>Frames per reel</label>
            <input type="number" min={1} max={20} defaultValue={settings.num_frames}
                   onBlur={(e) => Number(e.target.value) !== settings.num_frames && save({ num_frames: Number(e.target.value) })} />
            <small className="muted">More frames catch more on-screen text.</small>
          </div>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={settings.verify_links} onChange={(e) => save({ verify_links: e.target.checked })} />
          Check that extracted links actually work
        </label>
        <label className="toggle">
          <input type="checkbox" checked={settings.auto_signals} onChange={(e) => save({ auto_signals: e.target.checked })} />
          Add Laya signals (actionable, revisit value, purpose) after each analysis
        </label>
      </section>

      <section className="card">
        <h2><Bot size={19} /> Connect an AI assistant (MCP)</h2>
        <p className="muted">This app is also an MCP server, so any MCP-capable assistant (Claude Code, Claude Desktop, Cursor, VS Code, …) can search and use your saved reels in chat.</p>
        <div className="field">
          <label>MCP endpoint</label>
          <div className="code-row"><code>{mcpUrl}</code><button className="icon-btn" onClick={() => copy(mcpUrl)}><Copy size={15} /></button></div>
        </div>
        <div className="field">
          <label>Claude Code</label>
          <div className="code-row"><code>{claudeCmd}</code><button className="icon-btn" onClick={() => copy(claudeCmd)}><Copy size={15} /></button></div>
        </div>
        <div className="field">
          <label>Other MCP clients (Cursor, VS Code, …)</label>
          <div className="code-row"><code className="pre-code">{jsonConfig}</code><button className="icon-btn" onClick={() => copy(jsonConfig)}><Copy size={15} /></button></div>
        </div>
      </section>

      <p className="muted small center">Data folder: <code>{settings.data_dir}</code></p>
    </div>
  );
}
