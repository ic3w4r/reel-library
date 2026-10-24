"""The MCP layer: tools, resources and prompts over your saved-reels library."""

from __future__ import annotations

import json
import logging

import anyio
from mcp.server.mcpserver import Context, MCPServer

from . import db, decisions, ingest, library, pipeline
from .config import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

conn = db.connect(load_settings().db_path)

mcp = MCPServer(
    name="instamcp",
    title="Instagram Saved Reels",
    instructions=(
        "A library of the user's Instagram saved reels/posts. Each analyzed reel has a title, summary, key "
        "points, category, content type, tags, the user's own collection names, the transcript, and "
        "extracted links/resources (tools, products, places, books, sites).\n"
        "Start with library_overview to see collections and categories. Use search_reels for questions "
        "('that pasta recipe', 'AI tools for video'), list_reels to browse a collection/category, get_reel "
        "for full detail, and find_links to collect URLs. If many reels are 'pending', run analyze_reels. "
        "Always give the user the reel URL alongside anything you cite from a reel."
    ),
)


# ------------------------------------------------------------------ ingest

@mcp.tool()
def import_instagram_export(path: str) -> dict:
    """Import saved posts and saved collections from an Instagram data export.

    `path` can be the downloaded .zip, the unzipped folder, or a single saved_posts.json /
    saved_collections.json. Request the export in JSON format from Instagram: Accounts Center →
    Your information and permissions → Download your information → Saved.
    Safe to re-run: existing reels are kept, new ones are added as 'pending'.
    """
    stats = ingest.import_export(conn, path)
    stats["pending_analysis"] = library.counts_by_status(conn).get("pending", 0)
    return stats


@mcp.tool()
def add_reel(url: str, collection: str | None = None) -> dict:
    """Add a single Instagram reel/post URL to the library (optionally into a named collection).
    Run analyze_reels afterwards (or pass its id) to summarize it."""
    code = ingest.add_url(conn, url, collection)
    return {"id": code, "url": db.canonical_url(code, "reel"), "status": "pending"}


@mcp.tool()
async def sync_saved_from_instagram(username: str, limit: int = 200, session_file: str | None = None) -> dict:
    """Pull saved posts directly from Instagram using an existing instaloader login session
    (create one in a terminal with `instaloader -l USERNAME`). Collections are not available this
    way; use import_instagram_export for those."""
    return await anyio.to_thread.run_sync(lambda: ingest.live_sync(conn, username, session_file, limit))


# ------------------------------------------------------------------ analysis

@mcp.tool()
async def analyze_reels(
    ctx: Context,
    limit: int = 5,
    reel_ids: list[str] | None = None,
    collection: str | None = None,
    retry_failed: bool = False,
) -> dict:
    """Download, transcribe and summarize reels with the configured AI engine (vision + transcript), extracting links.

    With no reel_ids, processes up to `limit` pending reels (newest saves first), optionally only from
    one collection. Each reel takes roughly 20-60 s. For hundreds of reels prefer the web app's
    Analyze page or the CLI (`instamcp analyze --limit 500`). `reel_ids` accepts ids or URLs.
    """
    ids = [library.resolve_id(r) for r in reel_ids] if reel_ids else pipeline.pending_ids(
        conn, max(1, min(limit, 25)), include_failed=retry_failed, collection=collection
    )
    if not ids:
        return {"processed": 0, "message": "Nothing pending."}

    settings = load_settings()
    results: list[dict] = []
    for i, rid in enumerate(ids, 1):
        await ctx.report_progress(i - 1, len(ids), f"Analyzing {rid}")
        results.append(await anyio.to_thread.run_sync(pipeline.process_reel, conn, rid, settings))
    await ctx.report_progress(len(ids), len(ids), "Done")
    return {"processed": len(results), "results": results,
            "still_pending": library.counts_by_status(conn).get("pending", 0)}


# ------------------------------------------------------------------ browse & search

@mcp.tool()
def library_overview() -> dict:
    """Map of the whole saved library: totals by status, every collection (with its reel count and
    dominant categories), category and content-type counts, top tags and top creators."""
    return library.overview(conn)


@mcp.tool()
def list_reels(
    collection: str | None = None,
    category: str | None = None,
    content_type: str | None = None,
    creator: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict:
    """Browse reels with filters (all optional, case-insensitive). Newest saves first.
    status: pending | analyzed | failed."""
    return library.query_reels(conn, None, collection, category, content_type, creator, tag, status, limit, offset)


@mcp.tool()
def search_reels(query: str, collection: str | None = None, category: str | None = None, limit: int = 15) -> dict:
    """Full-text search across titles, summaries, captions, transcripts, on-screen text, tags,
    extracted resources and collection names. Results are ranked by relevance."""
    res = library.query_reels(conn, query, collection, category, limit=min(limit, 50))
    return {"query": query, "total": res["total"], "results": res["reels"]}


@mcp.tool()
def get_reel(reel: str, include_transcript: bool = True) -> dict:
    """Everything known about one reel (id or Instagram URL): summary, key points, why it was
    saved, transcript, on-screen text, collections and all extracted links."""
    try:
        return library.get_reel(conn, reel, include_transcript)
    except KeyError as e:
        raise ValueError(f"{e.args[0]}. Use add_reel first.") from None


@mcp.tool()
def find_links(
    query: str | None = None,
    kind: str | None = None,
    category: str | None = None,
    collection: str | None = None,
    verified_only: bool = False,
    limit: int = 50,
) -> dict:
    """Collect the links/resources extracted from reels — tools, apps, products, books, places,
    recipes, repos, websites — each with its URL (if known), a search link, and the reel it came from.
    Filter by free-text `query`, resource `kind`, reel `category` or `collection`."""
    return library.find_links(conn, query, kind, category, collection, verified_only, min(limit, 300))


@mcp.tool()
def move_to_collection(reel: str, collection: str) -> dict:
    """File a reel into a collection in this library (does not change Instagram itself)."""
    try:
        cols = library.add_to_collection(conn, reel, collection)
    except KeyError as e:
        raise ValueError(e.args[0]) from None
    return {"id": library.resolve_id(reel), "collections": cols}


# ------------------------------------------------------------------ analytics (Laya decision model)

@mcp.tool()
def library_analytics() -> dict:
    """Analytics across the library: saves per month by category, category / content-type / purpose
    mix, how many reels are actionable and worth revisiting (Laya signals), per-collection stats."""
    out = decisions.analytics(conn)
    out.pop("signals_job", None)
    return out


@mcp.tool()
async def ask_reels(
    question: str,
    answer_type: str = "yes_no",
    options: list[str] | None = None,
    collection: str | None = None,
    category: str | None = None,
    limit: int = 200,
) -> dict:
    """Ask one question about every reel in scope with the fast local Laya decision model, and get
    the reels ranked by the answer. Great for filtering by meaning, e.g. "Is this an activity to do
    with a toddler?" or "Does this need special equipment?".

    answer_type: "yes_no" (ranked by probability of yes), "choice" (options = labels to pick from) or
    "scale" (options = levels, lowest first). Only reels with text (analyzed, or with a caption) are
    asked. Answers are fast estimates; confirm important ones with get_reel."""
    if not decisions.available():
        raise ValueError("Laya isn't installed on this server.")
    res = await anyio.to_thread.run_sync(lambda: decisions.ask(
        conn, question, answer_type, options, collection, category, min(limit, 500)))
    for item in res["results"]:
        r = item["reel"]
        item["reel"] = {k: r.get(k) for k in ("id", "url", "title", "category", "creator", "collections")}
    return res


# ------------------------------------------------------------------ resources

@mcp.resource("instagram://overview", mime_type="application/json",
              description="Collections, categories and counts for the saved library")
def overview_resource() -> str:
    return json.dumps(library.overview(conn), ensure_ascii=False, indent=2)


@mcp.resource("instagram://reel/{reel_id}", mime_type="application/json",
              description="Full analysis of one saved reel")
def reel_resource(reel_id: str) -> str:
    return json.dumps(get_reel(reel_id), ensure_ascii=False, indent=2)


@mcp.resource("instagram://collection/{name}", mime_type="application/json",
              description="All reels in one saved collection")
def collection_resource(name: str) -> str:
    return json.dumps(library.query_reels(conn, collection=name, limit=200), ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ prompts

@mcp.prompt(description="Turn everything saved in a collection into a usable digest")
def digest_collection(collection: str) -> str:
    return (
        f"Use list_reels(collection={collection!r}, limit=200) and get_reel on the most useful ones. "
        "Write a digest grouped by theme: for each reel a one-line takeaway and its URL, then a "
        "'Links & resources' section from find_links(collection=...). Point out duplicates and anything "
        "still pending analysis."
    )


@mcp.prompt(description="Build a plan for a goal from what you've already saved")
def plan_from_saved(goal: str) -> str:
    return (
        f"My goal: {goal}\n"
        "Search my saved reels (search_reels with several phrasings, plus library_overview to spot relevant "
        "collections/categories). Build a concrete step-by-step plan using only what my saved reels teach, "
        "citing each reel's URL, and list the tools/products/links I'd need via find_links."
    )


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
