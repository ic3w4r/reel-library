"""Read/organise operations over the library, shared by the MCP server and the web API."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from . import db

COLLECTION_FILTER = """r.id IN (SELECT rc.reel_id FROM reel_collections rc JOIN collections c
                       ON c.id = rc.collection_id WHERE c.name = ? COLLATE NOCASE)"""


def resolve_id(reel: str) -> str:
    parsed = db.parse_instagram_url(reel)
    return parsed[0] if parsed else reel.strip()


def _with_thumb(d: dict, thumbs_dir: Path | None) -> dict:
    if thumbs_dir and (thumbs_dir / f"{d['id']}.jpg").exists():
        d["thumbnail"] = f"/api/reels/{d['id']}/thumb"
    return d


def overview(conn) -> dict:
    status = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM reels GROUP BY status")}

    collections = []
    for c in conn.execute(
        """SELECT c.name, COUNT(rc.reel_id) n FROM collections c
           LEFT JOIN reel_collections rc ON rc.collection_id = c.id GROUP BY c.id ORDER BY n DESC, c.name"""
    ):
        cats = conn.execute(
            """SELECT r.category, COUNT(*) n FROM reels r JOIN reel_collections rc ON rc.reel_id = r.id
               JOIN collections c ON c.id = rc.collection_id
               WHERE c.name = ? AND r.category IS NOT NULL GROUP BY r.category ORDER BY n DESC LIMIT 3""",
            (c["name"],),
        ).fetchall()
        collections.append({"name": c["name"], "reels": c["n"], "top_categories": [x["category"] for x in cats]})
    uncollected = conn.execute(
        "SELECT COUNT(*) FROM reels WHERE id NOT IN (SELECT reel_id FROM reel_collections)"
    ).fetchone()[0]

    def counts(col: str) -> dict:
        return {r[0]: r[1] for r in conn.execute(
            f"SELECT {col}, COUNT(*) FROM reels WHERE {col} IS NOT NULL GROUP BY {col} ORDER BY 2 DESC")}

    tags: Counter = Counter()
    for r in conn.execute("SELECT tags FROM reels WHERE tags IS NOT NULL"):
        tags.update(db._loads(r["tags"]))
    creators = conn.execute(
        """SELECT COALESCE(uploader, username) c, COUNT(*) n FROM reels WHERE COALESCE(uploader, username)
           IS NOT NULL GROUP BY c ORDER BY n DESC LIMIT 15"""
    ).fetchall()
    links = conn.execute("SELECT COUNT(*) FROM resources").fetchone()[0]

    return {
        "total_reels": sum(status.values()),
        "by_status": status,
        "collections": collections,
        "not_in_any_collection": uncollected,
        "categories": counts("category"),
        "content_types": counts("content_type"),
        "top_tags": dict(tags.most_common(30)),
        "top_creators": {r["c"]: r["n"] for r in creators},
        "extracted_links": links,
    }


def query_reels(
    conn,
    q: str | None = None,
    collection: str | None = None,
    category: str | None = None,
    content_type: str | None = None,
    creator: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    limit: int = 30,
    offset: int = 0,
    thumbs_dir: Path | None = None,
) -> dict:
    """Filter and/or full-text search reels. With `q`, results are ranked by relevance."""
    where, args = [], []
    if collection == "__none__":
        where.append("r.id NOT IN (SELECT reel_id FROM reel_collections)")
    elif collection:
        where.append(COLLECTION_FILTER)
        args.append(collection)
    for col, val in (("category", category), ("content_type", content_type), ("status", status)):
        if val:
            where.append(f"r.{col} = ? COLLATE NOCASE")
            args.append(val)
    if creator:
        where.append("(r.uploader LIKE ? OR r.username LIKE ?)")
        args += [f"%{creator.lstrip('@')}%"] * 2
    if tag:
        where.append("r.tags LIKE ?")
        args.append(f'%"{tag.lower()}"%')

    if q and q.strip():
        base = """FROM reels_fts JOIN reels r ON r.id = reels_fts.reel_id WHERE reels_fts MATCH ?"""
        args = [db.fts_query(q), *args]
        cond = "".join(f" AND {w}" for w in where)
        select = "SELECT r.*, bm25(reels_fts, 0, 8.0, 4.0, 2.0, 1.0, 5.0, 3.0, 3.0) AS score "
        order = " ORDER BY score"
    else:
        base = "FROM reels r"
        cond = (" WHERE " + " AND ".join(where)) if where else ""
        select = "SELECT r.* "
        order = " ORDER BY r.saved_at DESC NULLS LAST, r.added_at DESC"

    total = conn.execute("SELECT COUNT(*) " + base + cond, args).fetchone()[0]
    rows = conn.execute(select + base + cond + order + " LIMIT ? OFFSET ?",
                        [*args, max(1, min(limit, 200)), max(0, offset)]).fetchall()
    return {"total": total, "offset": offset,
            "reels": [_with_thumb(db.reel_to_dict(conn, r), thumbs_dir) for r in rows]}


def get_reel(conn, reel: str, include_transcript: bool = True, thumbs_dir: Path | None = None) -> dict:
    row = conn.execute("SELECT * FROM reels WHERE id = ?", (resolve_id(reel),)).fetchone()
    if not row:
        raise KeyError(f"Reel not in library: {reel}")
    d = _with_thumb(db.reel_to_dict(conn, row, full=True), thumbs_dir)
    from .decisions import reel_signals
    signals = reel_signals(conn, row["id"])
    if signals:
        d["signals"] = signals
    if not include_transcript:
        d.pop("transcript", None)
    return d


def find_links(
    conn,
    query: str | None = None,
    kind: str | None = None,
    category: str | None = None,
    collection: str | None = None,
    verified_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    sql = """FROM resources res JOIN reels r ON r.id = res.reel_id WHERE 1=1"""
    args: list[Any] = []
    if query:
        sql += " AND (res.name LIKE ? OR res.description LIKE ? OR r.title LIKE ? OR r.tags LIKE ?)"
        args += [f"%{query}%"] * 4
    if kind:
        sql += " AND res.kind = ? COLLATE NOCASE"
        args.append(kind)
    if category:
        sql += " AND r.category = ? COLLATE NOCASE"
        args.append(category)
    if collection:
        sql += " AND " + COLLECTION_FILTER
        args.append(collection)
    if verified_only:
        sql += " AND res.verified = 1"
    total = conn.execute("SELECT COUNT(*) " + sql, args).fetchone()[0]
    rows = conn.execute(
        "SELECT res.*, r.title AS reel_title, r.url AS reel_url, r.category " + sql
        + " ORDER BY res.id DESC LIMIT ? OFFSET ?", [*args, max(1, min(limit, 500)), max(0, offset)]
    ).fetchall()
    links = []
    for r in rows:
        links.append({k: v for k, v in {
            "name": r["name"], "kind": r["kind"], "url": r["url"],
            "verified": None if r["verified"] is None else bool(r["verified"]),
            "search_url": r["search_url"], "description": r["description"], "found_via": r["source"],
            "category": r["category"],
            "from_reel": {"id": r["reel_id"], "title": r["reel_title"], "url": r["reel_url"]},
        }.items() if v is not None})
    return {"total": total, "count": len(links), "links": links}


def link_kinds(conn) -> dict:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT kind, COUNT(*) FROM resources WHERE kind IS NOT NULL GROUP BY kind ORDER BY 2 DESC")}


def add_to_collection(conn, reel: str, collection: str) -> list[str]:
    rid = resolve_id(reel)
    if not conn.execute("SELECT 1 FROM reels WHERE id = ?", (rid,)).fetchone():
        raise KeyError(f"Reel not in library: {reel}")
    db.add_to_collection(conn, rid, collection.strip())
    conn.commit()
    return db.reel_collections(conn, rid)


def remove_from_collection(conn, reel: str, collection: str) -> list[str]:
    rid = resolve_id(reel)
    conn.execute(
        """DELETE FROM reel_collections WHERE reel_id = ? AND collection_id =
           (SELECT id FROM collections WHERE name = ? COLLATE NOCASE)""", (rid, collection))
    db.reindex(conn, rid)
    conn.commit()
    return db.reel_collections(conn, rid)


def delete_reel(conn, reel: str, thumbs_dir: Path | None = None) -> None:
    rid = resolve_id(reel)
    conn.execute("DELETE FROM reels_fts WHERE reel_id = ?", (rid,))
    conn.execute("DELETE FROM reels WHERE id = ?", (rid,))
    conn.commit()
    if thumbs_dir:
        (thumbs_dir / f"{rid}.jpg").unlink(missing_ok=True)


def counts_by_status(conn) -> dict:
    return {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM reels GROUP BY status")}
