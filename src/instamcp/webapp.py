"""Web application: REST API + React UI + MCP over HTTP (at /mcp), all on one port."""

from __future__ import annotations

import logging
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, db, decisions, engines, ingest, library, pipeline, providers
from .analyze import CATEGORIES, CONTENT_TYPES, RESOURCE_KINDS
from .config import (cookies_path, load_settings, public_settings, save_overrides,
                     write_session_cookie)
from .jobs import jobs
from .server import mcp

log = logging.getLogger("instamcp.web")

mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", host="0.0.0.0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs.start()
    async with mcp_app.router.lifespan_context(mcp_app):
        yield


app = FastAPI(title="instamcp", version=__version__, lifespan=lifespan)


def get_conn() -> Iterator:
    conn = db.connect(load_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


def thumbs() -> Path:
    return load_settings().thumbs_dir


@app.exception_handler(KeyError)
async def not_found(_, exc: KeyError):
    return JSONResponse({"detail": str(exc.args[0]) if exc.args else "Not found"}, status_code=404)


@app.exception_handler(ValueError)
async def bad_request(_, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ------------------------------------------------------------------ library

@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/overview")
def overview(conn=Depends(get_conn)):
    out = library.overview(conn)
    out["link_kinds"] = library.link_kinds(conn)
    return out


@app.get("/api/reels")
def reels(q: str | None = None, collection: str | None = None, category: str | None = None,
          content_type: str | None = None, creator: str | None = None, tag: str | None = None,
          status: str | None = None, limit: int = 48, offset: int = 0, conn=Depends(get_conn)):
    return library.query_reels(conn, q, collection, category, content_type, creator, tag, status,
                               limit, offset, thumbs())


@app.get("/api/reels/{reel_id}")
def reel(reel_id: str, conn=Depends(get_conn)):
    return library.get_reel(conn, reel_id, thumbs_dir=thumbs())


@app.get("/api/reels/{reel_id}/thumb")
def reel_thumb(reel_id: str):
    path = thumbs() / f"{library.resolve_id(reel_id)}.jpg"
    if not path.exists() or path.parent != thumbs():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


class AddReel(BaseModel):
    url: str
    collection: str | None = None
    analyze: bool = True


@app.post("/api/reels")
def add_reel(body: AddReel, conn=Depends(get_conn)):
    code = ingest.add_url(conn, body.url, body.collection or None)
    queued = jobs.enqueue([code]) if body.analyze else 0
    return {"id": code, "queued": bool(queued)}


@app.delete("/api/reels/{reel_id}")
def delete_reel(reel_id: str, conn=Depends(get_conn)):
    library.delete_reel(conn, reel_id, thumbs())
    return {"deleted": reel_id}


class CollectionBody(BaseModel):
    name: str


@app.post("/api/reels/{reel_id}/collections")
def add_collection(reel_id: str, body: CollectionBody, conn=Depends(get_conn)):
    if not body.name.strip():
        raise ValueError("Collection name is empty")
    return {"collections": library.add_to_collection(conn, reel_id, body.name)}


@app.delete("/api/reels/{reel_id}/collections/{name}")
def remove_collection(reel_id: str, name: str, conn=Depends(get_conn)):
    return {"collections": library.remove_from_collection(conn, reel_id, name)}


@app.get("/api/links")
def links(q: str | None = None, kind: str | None = None, category: str | None = None,
          collection: str | None = None, verified_only: bool = False, limit: int = 100, offset: int = 0,
          conn=Depends(get_conn)):
    return library.find_links(conn, q, kind, category, collection, verified_only, limit, offset)


@app.get("/api/meta")
def meta():
    return {"categories": CATEGORIES, "content_types": CONTENT_TYPES, "resource_kinds": RESOURCE_KINDS}


# ------------------------------------------------------------------ import & analysis

@app.post("/api/import")
def import_export(file: UploadFile = File(...), analyze: bool = False, conn=Depends(get_conn)):
    name = Path(file.filename or "upload").name
    if not name.lower().endswith((".zip", ".json")):
        raise ValueError("Upload the Instagram export .zip, or saved_posts.json / saved_collections.json")
    dest_dir = load_settings().data_dir / "imports"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / f"{int(time.time())}-{name}"
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        stats = ingest.import_export(conn, dest)
    finally:
        if dest.suffix == ".zip":
            dest.unlink(missing_ok=True)  # the zip can be large; keep only small json uploads
    stats["files"] = [Path(f).name for f in stats["files"]]
    pending = pipeline.pending_ids(conn, 100000)
    stats["pending_analysis"] = len(pending)
    if analyze:
        stats["queued"] = jobs.enqueue(pending)
    return stats


class AnalyzeBody(BaseModel):
    ids: list[str] | None = None
    limit: int = 20
    collection: str | None = None
    retry_failed: bool = False


@app.post("/api/analyze")
def analyze(body: AnalyzeBody, conn=Depends(get_conn)):
    if not engines.summary()["ai_ready"]:
        raise ValueError("Set up an AI engine in Settings → AI engines first.")
    if body.ids:
        ids = [library.resolve_id(i) for i in body.ids]
    else:
        ids = pipeline.pending_ids(conn, max(1, min(body.limit, 5000)), body.retry_failed, body.collection)
    return {"queued": jobs.enqueue(ids)}


@app.get("/api/jobs")
def job_status(conn=Depends(get_conn)):
    return {**jobs.status(), "library": library.counts_by_status(conn)}


@app.post("/api/jobs/cancel")
def cancel_jobs():
    return {"cancelled": jobs.cancel()}


# ------------------------------------------------------------------ settings

@app.get("/api/settings")
def get_settings():
    s = load_settings()
    return {
        **public_settings(s),
        **engines.summary(),
        "instagram_cookie_source": "uploaded" if cookies_path().exists()
        else ("browser" if s.cookies_from_browser else ("file" if s.cookies_file else "none")),
        "options": {"whisper_models": ["tiny", "base", "small", "medium", "large-v3"]},
    }


class SettingsBody(BaseModel):
    whisper_model: str | None = None
    num_frames: int | None = None
    verify_links: bool | None = None
    auto_signals: bool | None = None


@app.put("/api/settings")
def put_settings(body: SettingsBody):
    updates = body.model_dump(exclude_none=True)
    if "num_frames" in updates and not 1 <= updates["num_frames"] <= 20:
        raise ValueError("Frames per reel must be between 1 and 20")
    save_overrides(updates)
    return get_settings()


# ------------------------------------------------------------------ analytics & Laya decisions

@app.get("/api/analytics")
def analytics(conn=Depends(get_conn)):
    return decisions.analytics(conn)


class SignalsBody(BaseModel):
    limit: int = 100000
    collection: str | None = None
    recompute: bool = False


@app.post("/api/signals/run")
def run_signals(body: SignalsBody, conn=Depends(get_conn)):
    if not decisions.available():
        raise ValueError("Laya isn't installed in this build.")
    if body.recompute:
        sql = f"SELECT r.id FROM reels r WHERE {decisions.TEXT_SQL}"
        ids = [r["id"] for r in conn.execute(sql + " LIMIT ?", (body.limit,))]
    else:
        ids = decisions.ids_missing_signals(conn, body.limit, body.collection)
    if not ids:
        return {"started": False, "message": "Every reel with text already has signals."}
    started = decisions.signals_job.start(load_settings().db_path, ids)
    return {"started": started, "count": len(ids),
            "message": None if started else "Signals are already being computed."}


@app.get("/api/signals/status")
def signals_status():
    return decisions.signals_job.status()


class AskBody(BaseModel):
    question: str
    answer_type: str = "yes_no"
    options: list[str] | None = None
    collection: str | None = None
    category: str | None = None
    limit: int = 200


@app.post("/api/ask")
def ask(body: AskBody, conn=Depends(get_conn)):
    if not decisions.available():
        raise ValueError("Laya isn't installed in this build.")
    return decisions.ask(conn, body.question, body.answer_type, body.options, body.collection or None,
                         body.category or None, body.limit, thumbs())


# ------------------------------------------------------------------ AI engines

def _engines_response() -> dict:
    cfg = engines.load()
    return {
        "engines": [engines.public(e) for e in cfg["engines"]],
        "active": cfg["active"],
        "fallback": cfg["fallback"],
        "presets": engines.PRESETS,
    }


@app.get("/api/engines")
def list_engines():
    return _engines_response()


class EngineBody(BaseModel):
    preset: str | None = None
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # omitted/None = keep current; "" = clear
    model: str | None = None
    effort: str | None = None
    vision: bool | None = None
    json_mode: str | None = None


def _clean(body: EngineBody) -> dict:
    d = body.model_dump(exclude_none=True)
    for k in ("name", "base_url", "api_key", "model"):
        if k in d:
            d[k] = d[k].strip()
    if d.get("effort") and d["effort"] not in ("low", "medium", "high", "xhigh", "max"):
        raise ValueError("Effort must be low, medium, high, xhigh or max")
    if d.get("json_mode") and d["json_mode"] not in ("auto", "schema", "object", "none"):
        raise ValueError("JSON mode must be auto, schema, object or none")
    return d


@app.post("/api/engines")
def create_engine(body: EngineBody):
    d = _clean(body)
    eng = engines.make_engine(d.pop("preset", None) or "custom", **d)
    cfg = engines.load()
    first_ready = not any(engines.is_ready(e) for e in cfg["engines"])
    cfg["engines"].append(eng)
    active = eng["id"] if (first_ready and engines.is_ready(eng)) or not cfg["active"] else cfg["active"]
    engines.save(cfg["engines"], active, cfg["fallback"])
    return {**_engines_response(), "created": eng["id"]}


@app.put("/api/engines/{engine_id}")
def update_engine(engine_id: str, body: EngineBody):
    d = _clean(body)
    d.pop("preset", None)
    cfg = engines.load()
    for e in cfg["engines"]:
        if e["id"] == engine_id:
            e.update(d)
            providers._learned.pop(engine_id, None)  # endpoint may have changed: re-probe capabilities
            break
    else:
        raise KeyError(f"No such engine: {engine_id}")
    engines.save(cfg["engines"], cfg["active"], cfg["fallback"])
    return _engines_response()


@app.delete("/api/engines/{engine_id}")
def delete_engine(engine_id: str):
    cfg = engines.load()
    remaining = [e for e in cfg["engines"] if e["id"] != engine_id]
    if len(remaining) == len(cfg["engines"]):
        raise KeyError(f"No such engine: {engine_id}")
    active = cfg["active"] if cfg["active"] != engine_id else (remaining[0]["id"] if remaining else None)
    fallback = cfg["fallback"] if cfg["fallback"] != engine_id else None
    engines.save(remaining, active, fallback if fallback != active else None)
    return _engines_response()


class RolesBody(BaseModel):
    active: str
    fallback: str | None = None


@app.put("/api/engines-roles")
def set_roles(body: RolesBody):
    cfg = engines.load()
    ids = {e["id"] for e in cfg["engines"]}
    if body.active not in ids or (body.fallback and body.fallback not in ids):
        raise ValueError("Unknown engine")
    engines.save(cfg["engines"], body.active, body.fallback if body.fallback != body.active else None)
    return _engines_response()


@app.post("/api/engines/{engine_id}/test")
def test_engine(engine_id: str):
    eng = engines.get(engine_id)
    try:
        model = providers.check(eng)
    except providers.AccountError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:300]}"}
    return {"ok": True, "message": f"Working. Responded as {model}."}


@app.get("/api/engines/{engine_id}/models")
def engine_models(engine_id: str):
    eng = engines.get(engine_id)
    try:
        return {"models": providers.list_models(eng)}
    except providers.AccountError as e:
        raise ValueError(str(e)) from None
    except Exception as e:
        raise ValueError(f"Couldn't list models: {str(e)[:300]}") from None


class SessionBody(BaseModel):
    sessionid: str


@app.post("/api/settings/instagram")
def set_instagram_session(body: SessionBody):
    if len(body.sessionid.strip()) < 10:
        raise ValueError("That doesn't look like an Instagram sessionid cookie value.")
    write_session_cookie(body.sessionid)
    return get_settings()


@app.post("/api/settings/cookies")
def upload_cookies(file: UploadFile = File(...)):
    data = file.file.read()
    if b"instagram.com" not in data:
        raise ValueError("This cookies.txt has no instagram.com cookies.")
    cookies_path().write_bytes(data)
    cookies_path().chmod(0o600)
    return get_settings()


@app.delete("/api/settings/instagram")
def clear_instagram_session():
    cookies_path().unlink(missing_ok=True)
    return get_settings()


# ------------------------------------------------------------------ MCP + UI

for route in mcp_app.routes:  # MCP streamable HTTP endpoint at /mcp
    app.router.routes.append(route)


def _web_dist() -> Path | None:
    candidates = [os.environ.get("INSTAMCP_WEB_DIST"), Path(__file__).resolve().parents[2] / "web" / "dist"]
    for c in candidates:
        if c and (Path(c) / "index.html").exists():
            return Path(c)
    return None


_dist = _web_dist()
if _dist:
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
else:
    @app.get("/")
    def no_ui():
        return JSONResponse({"detail": "UI not built. Run `npm run build` in web/, or use the Docker image."})


def run(host: str = "127.0.0.1", port: int = 8080) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
