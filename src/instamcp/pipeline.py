"""Per-reel processing: download → frames + transcript → AI engine analysis → store."""

from __future__ import annotations

import logging
import re
import shutil
import time
from typing import Callable

from . import db, media
from .analyze import AccountError, analyze
from .config import Settings

log = logging.getLogger("instamcp")


def process_reel(conn, reel_id: str, settings: Settings) -> dict:
    row = conn.execute("SELECT * FROM reels WHERE id = ?", (reel_id,)).fetchone()
    if not row:
        raise KeyError(f"Unknown reel {reel_id}")
    workdir = settings.media_dir / reel_id
    try:
        try:
            bundle = media.prepare(row["url"], workdir, settings)
        except Exception as e:
            # Photo posts, private/deleted reels, or login walls: fall back to whatever text we have.
            if not row["caption"]:
                msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).removeprefix("ERROR: ")
                hint = "" if settings.cookies_file or settings.cookies_from_browser else \
                    " Instagram usually needs a login: connect it in Settings."
                raise RuntimeError(f"Could not download the video: {msg}.{hint}") from e
            log.warning("download failed for %s, analysing caption only: %s", reel_id, e)
            bundle = media.MediaBundle(caption=row["caption"])
        bundle.caption = bundle.caption or row["caption"]
        if bundle.frames:
            cover = bundle.frames[min(1, len(bundle.frames) - 1)]
            (settings.thumbs_dir / f"{reel_id}.jpg").write_bytes(cover)

        result = analyze(bundle, row["url"], row["username"], db.reel_collections(conn, reel_id), settings)
        fields = {
            "status": "analyzed",
            "error": None,
            "caption": bundle.caption,
            "uploader": bundle.uploader,
            "duration": bundle.duration,
            "thumbnail_url": bundle.thumbnail_url,
            "transcript": bundle.transcript,
            "language": result.get("language") or bundle.language,
            "analyzed_at": int(time.time()),
            "model": result.get("_model"),
            **{k: result.get(k) for k in (
                "title", "summary", "key_points", "category", "content_type", "topics", "tags",
                "why_saved", "on_screen_text",
            )},
        }
        db.save_analysis(conn, reel_id, fields, result.get("resources", []))
        _store_signals(conn, reel_id, result, settings)
        return {"id": reel_id, "status": "analyzed", "title": result.get("title"), "category": result.get("category")}
    except AccountError:
        raise  # not this reel's fault: leave it pending and let the caller stop
    except Exception as e:
        log.exception("failed to process %s", reel_id)
        db.mark_failed(conn, reel_id, str(e))
        return {"id": reel_id, "status": "failed", "error": str(e)[:500]}
    finally:
        if not settings.keep_media:
            shutil.rmtree(workdir, ignore_errors=True)


def _store_signals(conn, reel_id: str, result: dict, settings: Settings) -> None:
    """Laya signals for the analytics: reuse the Laya engine's own, or compute them if Laya is installed."""
    from . import decisions

    try:
        if result.get("_signals"):
            decisions.store_signals(conn, reel_id, result["_signals"], result.get("_model", "laya"))
        elif settings.auto_signals and decisions.available():
            decisions.compute_signals(conn, [reel_id])
    except Exception:
        log.exception("couldn't compute Laya signals for %s", reel_id)  # signals are optional


def pending_ids(conn, limit: int, include_failed: bool = False, collection: str | None = None) -> list[str]:
    statuses = ("pending", "failed") if include_failed else ("pending",)
    sql = f"SELECT r.id FROM reels r WHERE r.status IN ({','.join('?' * len(statuses))})"
    args: list = list(statuses)
    if collection:
        sql += """ AND r.id IN (SELECT rc.reel_id FROM reel_collections rc
                   JOIN collections c ON c.id = rc.collection_id WHERE c.name = ? COLLATE NOCASE)"""
        args.append(collection)
    sql += " ORDER BY r.saved_at DESC NULLS LAST LIMIT ?"
    args.append(limit)
    return [r["id"] for r in conn.execute(sql, args)]


def process_many(conn, ids: list[str], settings: Settings,
                 on_progress: Callable[[int, int, dict], None] | None = None) -> list[dict]:
    results = []
    for i, rid in enumerate(ids, 1):
        res = process_reel(conn, rid, settings)
        results.append(res)
        if on_progress:
            on_progress(i, len(ids), res)
    return results
