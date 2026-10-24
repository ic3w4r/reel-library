"""SQLite storage: reels, collections, extracted resources/links, and a full-text index."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id            TEXT PRIMARY KEY,          -- Instagram shortcode
    url           TEXT NOT NULL,
    media_kind    TEXT,                      -- reel | post | tv
    username      TEXT,
    saved_at      INTEGER,                   -- unix seconds, from the export
    added_at      INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | analyzed | failed
    error         TEXT,
    -- raw media facts
    caption       TEXT,
    uploader      TEXT,
    duration      REAL,
    thumbnail_url TEXT,
    transcript    TEXT,
    -- analysis
    title         TEXT,
    summary       TEXT,
    key_points    TEXT,                      -- JSON list
    category      TEXT,
    content_type  TEXT,
    topics        TEXT,                      -- JSON list
    tags          TEXT,                      -- JSON list
    why_saved     TEXT,
    on_screen_text TEXT,
    language      TEXT,
    analyzed_at   INTEGER,
    model         TEXT
);

CREATE TABLE IF NOT EXISTS collections (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS reel_collections (
    reel_id       TEXT NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    added_at      INTEGER,
    PRIMARY KEY (reel_id, collection_id)
);

CREATE TABLE IF NOT EXISTS resources (
    id          INTEGER PRIMARY KEY,
    reel_id     TEXT NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    kind        TEXT,
    url         TEXT,
    source      TEXT,                        -- caption | spoken | on_screen | inferred
    description TEXT,
    verified    INTEGER,                     -- 1 reachable, 0 unreachable, NULL unchecked
    search_url  TEXT
);
CREATE INDEX IF NOT EXISTS resources_reel ON resources(reel_id);

CREATE TABLE IF NOT EXISTS decisions (     -- Laya decision signals per reel
    reel_id    TEXT NOT NULL REFERENCES reels(id) ON DELETE CASCADE,
    qid        TEXT NOT NULL,                -- category | content_type | purpose | actionable | revisit
    answer     TEXT,
    value      REAL,                         -- P(yes) for yes/no, expected level for scales
    confidence REAL,
    model      TEXT,
    created_at INTEGER,
    PRIMARY KEY (reel_id, qid)
);
CREATE INDEX IF NOT EXISTS decisions_qid ON decisions(qid, answer);

CREATE VIRTUAL TABLE IF NOT EXISTS reels_fts USING fts5(
    reel_id UNINDEXED, title, summary, caption, transcript, tags, resources, collections,
    tokenize = 'porter unicode61'
);
"""

JSON_FIELDS = ("key_points", "topics", "tags")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.executescript(SCHEMA)
    return conn


SHORTCODE_RE = re.compile(r"instagram\.com/(?:[\w.]+/)?(reel|reels|p|tv)/([A-Za-z0-9_-]+)")


def parse_instagram_url(url: str) -> tuple[str, str] | None:
    """Return (shortcode, kind) for an Instagram post/reel URL, else None."""
    m = SHORTCODE_RE.search(url or "")
    if not m:
        return None
    kind = {"reels": "reel", "p": "post"}.get(m.group(1), m.group(1))
    return m.group(2), kind


def canonical_url(shortcode: str, kind: str) -> str:
    return f"https://www.instagram.com/{'reel' if kind == 'reel' else 'p'}/{shortcode}/"


# ---------------------------------------------------------------- writes

def upsert_reel(conn, url: str, username: str | None = None, saved_at: int | None = None) -> str | None:
    parsed = parse_instagram_url(url)
    if not parsed:
        return None
    code, kind = parsed
    conn.execute(
        """INSERT INTO reels (id, url, media_kind, username, saved_at, added_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             username = COALESCE(reels.username, excluded.username),
             saved_at = COALESCE(reels.saved_at, excluded.saved_at)""",
        (code, canonical_url(code, kind), kind, username, saved_at, int(time.time())),
    )
    return code


def add_to_collection(conn, reel_id: str, name: str, added_at: int | None = None,
                      created_at: int | None = None) -> None:
    conn.execute(
        "INSERT INTO collections (name, created_at) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
        (name, created_at),
    )
    cid = conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()["id"]
    conn.execute(
        "INSERT OR IGNORE INTO reel_collections (reel_id, collection_id, added_at) VALUES (?, ?, ?)",
        (reel_id, cid, added_at),
    )
    reindex(conn, reel_id)


def save_analysis(conn, reel_id: str, fields: dict[str, Any], resources: Iterable[dict]) -> None:
    fields = dict(fields)
    for k in JSON_FIELDS:
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE reels SET {cols} WHERE id = ?", (*fields.values(), reel_id))
    conn.execute("DELETE FROM resources WHERE reel_id = ?", (reel_id,))
    conn.executemany(
        """INSERT INTO resources (reel_id, name, kind, url, source, description, verified, search_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (reel_id, r["name"], r.get("kind"), r.get("url") or None, r.get("source"),
             r.get("description"), r.get("verified"), r.get("search_url"))
            for r in resources
        ],
    )
    reindex(conn, reel_id)
    conn.commit()


def mark_failed(conn, reel_id: str, error: str) -> None:
    conn.execute("UPDATE reels SET status = 'failed', error = ? WHERE id = ?", (error[:2000], reel_id))
    conn.commit()


def reindex(conn, reel_id: str) -> None:
    row = conn.execute("SELECT * FROM reels WHERE id = ?", (reel_id,)).fetchone()
    if not row:
        return
    res = conn.execute(
        "SELECT name, kind, url, description FROM resources WHERE reel_id = ?", (reel_id,)
    ).fetchall()
    cols = conn.execute(
        """SELECT c.name FROM collections c JOIN reel_collections rc ON rc.collection_id = c.id
           WHERE rc.reel_id = ?""", (reel_id,)
    ).fetchall()
    tags = " ".join(_loads(row["tags"]) + _loads(row["topics"]) + [row["category"] or "", row["content_type"] or ""])
    conn.execute("DELETE FROM reels_fts WHERE reel_id = ?", (reel_id,))
    conn.execute(
        "INSERT INTO reels_fts (reel_id, title, summary, caption, transcript, tags, resources, collections)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            reel_id, row["title"] or "", " ".join(filter(None, [row["summary"], row["why_saved"]])),
            " ".join(filter(None, [row["caption"], row["username"], row["uploader"]])),
            " ".join(filter(None, [row["transcript"], row["on_screen_text"]])), tags,
            " ".join(" ".join(filter(None, tuple(r))) for r in res),
            " ".join(c["name"] for c in cols),
        ),
    )


# ---------------------------------------------------------------- reads

def _loads(v: str | None) -> list:
    if not v:
        return []
    try:
        out = json.loads(v)
        return out if isinstance(out, list) else []
    except json.JSONDecodeError:
        return []


def reel_collections(conn, reel_id: str) -> list[str]:
    return [
        r["name"] for r in conn.execute(
            """SELECT c.name FROM collections c JOIN reel_collections rc ON rc.collection_id = c.id
               WHERE rc.reel_id = ? ORDER BY c.name""", (reel_id,)
        )
    ]


def reel_resources(conn, reel_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT name, kind, url, source, description, verified, search_url FROM resources"
        " WHERE reel_id = ? ORDER BY id", (reel_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in r.keys() if r[k] is not None}
        if "verified" in d:
            d["verified"] = bool(d["verified"])
        out.append(d)
    return out


def reel_to_dict(conn, row: sqlite3.Row, full: bool = False) -> dict:
    d: dict[str, Any] = {
        "id": row["id"],
        "url": row["url"],
        "status": row["status"],
        "title": row["title"],
        "summary": row["summary"],
        "category": row["category"],
        "content_type": row["content_type"],
        "tags": _loads(row["tags"]),
        "creator": row["uploader"] or row["username"],
        "collections": reel_collections(conn, row["id"]),
        "saved_at": _iso(row["saved_at"]),
    }
    if full:
        d.update(
            key_points=_loads(row["key_points"]),
            topics=_loads(row["topics"]),
            why_saved=row["why_saved"],
            caption=row["caption"],
            transcript=row["transcript"],
            on_screen_text=row["on_screen_text"],
            language=row["language"],
            duration_seconds=row["duration"],
            thumbnail_url=row["thumbnail_url"],
            links=reel_resources(conn, row["id"]),
            analyzed_at=_iso(row["analyzed_at"]),
            error=row["error"],
        )
    return {k: v for k, v in d.items() if v not in (None, "", [])}


def _iso(ts: int | None) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def fts_query(text: str) -> str:
    """Turn free text into a forgiving FTS5 query (prefix match, OR-ed terms)."""
    terms = re.findall(r"[\w']+", text.lower())
    return " OR ".join(f'"{t}"*' for t in terms) if terms else '""'
