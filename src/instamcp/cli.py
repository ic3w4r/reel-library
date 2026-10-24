"""Command line: `instamcp serve | import | add | analyze | stats`."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="instamcp", description="MCP layer over your Instagram saved reels")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="Run the MCP server over stdio")
    web = sub.add_parser("web", help="Run the web app (UI + REST API + MCP over HTTP at /mcp)")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8080)
    imp = sub.add_parser("import", help="Import an Instagram data export (zip, folder or json)")
    imp.add_argument("path")
    add = sub.add_parser("add", help="Add one reel URL")
    add.add_argument("url")
    add.add_argument("--collection")
    an = sub.add_parser("analyze", help="Download + transcribe + summarize pending reels")
    an.add_argument("--limit", type=int, default=20)
    an.add_argument("--collection")
    an.add_argument("--retry-failed", action="store_true")
    an.add_argument("ids", nargs="*", help="Specific reel ids/URLs to (re)analyze")
    sync = sub.add_parser("sync", help="Live-sync saved posts via an instaloader session")
    sync.add_argument("username")
    sync.add_argument("--limit", type=int, default=200)
    sub.add_parser("stats", help="Print the library overview")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        from .server import main as serve
        serve()
        return
    if args.cmd == "web":
        from .webapp import run
        run(args.host, args.port)
        return

    from . import db, ingest, library, pipeline
    from .config import load_settings

    settings = load_settings()
    conn = db.connect(settings.db_path)

    if args.cmd == "import":
        out = ingest.import_export(conn, args.path)
    elif args.cmd == "add":
        out = {"id": ingest.add_url(conn, args.url, args.collection)}
    elif args.cmd == "sync":
        out = ingest.live_sync(conn, args.username, limit=args.limit)
    elif args.cmd == "analyze":
        ids = [db.parse_instagram_url(i)[0] if db.parse_instagram_url(i) else i for i in args.ids] or \
            pipeline.pending_ids(conn, args.limit, args.retry_failed, args.collection)
        def progress(i: int, n: int, res: dict) -> None:
            label = res.get("title") or res.get("error", "")[:100]
            print(f"[{i}/{n}] {res['id']} {res['status']}: {label}", file=sys.stderr, flush=True)
        results = pipeline.process_many(conn, ids, settings, progress)
        out = {"processed": len(results), "failed": sum(r["status"] == "failed" for r in results)}
    else:
        out = library.overview(conn)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
