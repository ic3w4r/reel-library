"""Getting saved reels into the library.

Three sources:
  1. The official Instagram data export ("Download your information", JSON format).
     Contains every saved post plus your saved *collections*. This is the recommended path.
  2. Single URLs added by hand (add_reel).
  3. Optional live sync through an instaloader session (pip extra `live`).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Iterator

from . import db

ALL_POSTS = "All saved"


def _iter_json_files(path: Path) -> Iterator[tuple[str, Any]]:
    """Yield (name, parsed json) for saved-related files in a folder or a .zip export."""
    if path.is_file() and path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if _is_saved_file(name):
                    yield name, json.loads(z.read(name).decode("utf-8"))
    elif path.is_file():
        yield path.name, json.loads(path.read_text("utf-8"))
    else:
        for p in sorted(path.rglob("*.json")):
            if _is_saved_file(str(p)):
                yield str(p), json.loads(p.read_text("utf-8"))


def _is_saved_file(name: str) -> bool:
    n = name.lower().replace("\\", "/")
    return n.endswith(".json") and ("/saved/" in n or n.startswith("saved/") or "saved_" in n.rsplit("/", 1)[-1])


def _fix(s: str | None) -> str | None:
    """Instagram exports encode UTF-8 bytes as latin-1 escapes; undo that."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _fields(entry: dict) -> dict[str, dict]:
    """Normalise an export entry's key/value data across export format versions."""
    out: dict[str, dict] = {}
    smd = entry.get("string_map_data")
    if isinstance(smd, dict):
        out.update({k: v for k, v in smd.items() if isinstance(v, dict)})
    for lv in entry.get("label_values") or []:  # newer export format
        if isinstance(lv, dict) and "label" in lv:
            out[lv["label"]] = {k: lv[k] for k in ("value", "href", "timestamp") if k in lv}
    return out


def _find_href(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "href" and isinstance(v, str) and db.parse_instagram_url(v):
                return v
            found = _find_href(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_href(v)
            if found:
                return found
    return None


def _find_ts(fields: dict[str, dict], entry: dict) -> int | None:
    for v in fields.values():
        if isinstance(v.get("timestamp"), int) and v["timestamp"] > 0:
            return v["timestamp"]
    ts = entry.get("timestamp")
    return ts if isinstance(ts, int) and ts > 0 else None


def import_export(conn, path: str | Path) -> dict[str, Any]:
    """Import saved posts and collections from an Instagram data export (folder, zip or json)."""
    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"No such file or folder: {path}")

    stats = {"files": [], "reels_seen": 0, "new_reels": 0, "collections": set()}
    before = conn.execute("SELECT COUNT(*) FROM reels").fetchone()[0]

    for name, data in _iter_json_files(path):
        stats["files"].append(name)
        if not isinstance(data, dict):
            continue
        for key, entries in data.items():
            if not isinstance(entries, list):
                continue
            if "collection" in key.lower():
                _import_collections(conn, entries, stats)
            else:
                _import_saved(conn, entries, stats)

    conn.commit()
    stats["new_reels"] = conn.execute("SELECT COUNT(*) FROM reels").fetchone()[0] - before
    stats["collections"] = sorted(stats["collections"])
    if not stats["files"]:
        raise ValueError(
            "No saved_posts.json / saved_collections.json found. Request your export in JSON format "
            "(Accounts Center → Your information and permissions → Download your information) and "
            "point this at the unzipped folder or the .zip."
        )
    return stats


def _import_saved(conn, entries: list, stats: dict) -> None:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        href = _find_href(entry)
        if not href:
            continue
        fields = _fields(entry)
        code = db.upsert_reel(conn, href, username=_fix(entry.get("title")), saved_at=_find_ts(fields, entry))
        if code:
            stats["reels_seen"] += 1


def _import_collections(conn, entries: list, stats: dict) -> None:
    """saved_collections.json is a flat list: a collection header, then its items, then the next header."""
    current: str | None = None
    current_created: int | None = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        fields = _fields(entry)
        href = _find_href(entry)
        name_field = fields.get("Name") or fields.get("Collection name") or {}
        if not href and name_field.get("value"):
            current = _fix(name_field["value"])
            current_created = _find_ts(fields, entry)
            stats["collections"].add(current)
            continue
        # Some export versions nest a collection's media under the header entry.
        nested = entry.get("media") or entry.get("media_list_data")
        if isinstance(nested, list) and entry.get("title") and not href:
            current = _fix(entry["title"])
            stats["collections"].add(current)
            for item in nested:
                h = _find_href(item)
                if h:
                    code = db.upsert_reel(conn, h)
                    if code:
                        db.add_to_collection(conn, code, current)
            continue
        if href and current:
            username = _fix(name_field.get("value") or entry.get("title"))
            added = _find_ts(fields, entry)
            code = db.upsert_reel(conn, href, username=username, saved_at=added)
            if code:
                stats["reels_seen"] += 1
                db.add_to_collection(conn, code, current, added_at=added, created_at=current_created)


def add_url(conn, url: str, collection: str | None = None) -> str:
    code = db.upsert_reel(conn, url)
    if not code:
        raise ValueError(f"Not an Instagram post/reel URL: {url}")
    if collection:
        db.add_to_collection(conn, code, collection)
    conn.commit()
    return code


def live_sync(conn, username: str, session_file: str | None = None, limit: int | None = None) -> dict:
    """Pull saved posts directly using an instaloader session (created with `instaloader -l USERNAME`).

    Note: Instagram does not expose collection membership here; use the data export for collections.
    """
    try:
        import instaloader
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Live sync needs the 'live' extra: uv sync --extra live") from e

    L = instaloader.Instaloader(download_pictures=False, download_videos=False, save_metadata=False)
    L.load_session_from_file(username, session_file)
    profile = instaloader.Profile.own_profile(L.context)
    added = 0
    for i, post in enumerate(profile.get_saved_posts()):
        if limit and i >= limit:
            break
        kind = "reel" if post.is_video else "p"
        code = db.upsert_reel(
            conn, f"https://www.instagram.com/{kind}/{post.shortcode}/",
            username=post.owner_username, saved_at=None,
        )
        if code:
            conn.execute(
                "UPDATE reels SET caption = COALESCE(caption, ?) WHERE id = ?", (post.caption, code)
            )
            added += 1
    conn.commit()
    return {"synced": added}
