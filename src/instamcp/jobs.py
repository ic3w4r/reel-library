"""Background analysis queue for the web app: one worker thread, processes reels one at a time.

The queue is mirrored to <data_dir>/queue.json so a batch picks up where it left off after the
server restarts (e.g. the container was killed for running out of memory mid-reel).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque

from . import db, pipeline
from .analyze import AccountError
from .config import data_dir, load_settings

log = logging.getLogger("instamcp.jobs")


def _queue_file():
    return data_dir() / "queue.json"


class JobManager:
    def __init__(self) -> None:
        self._queue: deque[str] = deque()
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self.current: dict | None = None
        self.done = 0
        self.failed = 0
        self.batch_total = 0
        self.recent: deque[dict] = deque(maxlen=30)
        self.halted: str | None = None  # set when an account problem stopped the queue
        self._crashes = 0  # times the server already died on the reel at the head of a resumed queue

    def start(self) -> None:
        if not self._thread:
            self._resume()
            self._thread = threading.Thread(target=self._run, name="analysis-worker", daemon=True)
            self._thread.start()

    def _resume(self) -> None:
        """Re-queue the batch saved by _save(). The reel that was in progress goes first, unless the
        server already died on it before: then it's marked failed so one bad reel can't loop forever."""
        try:
            saved = json.loads(_queue_file().read_text())
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        current, queue = saved.get("current"), [i for i in saved.get("queue", []) if isinstance(i, str)]
        if isinstance(current, str):
            if saved.get("current_crashes", 0) >= 1:
                log.warning("server died twice while analyzing %s; marking it failed", current)
                try:
                    conn = db.connect(load_settings().db_path)
                    db.mark_failed(conn, current, "The server ran out of memory twice on this reel "
                                   "(long video?). Give Docker more memory, then use Retry failed.")
                    conn.close()
                except Exception:
                    log.warning("couldn't mark %s failed", current, exc_info=True)
                self._crashes = 0
            else:
                queue.insert(0, current)
                self._crashes = saved.get("current_crashes", 0) + 1
        self._queue.extend(dict.fromkeys(queue))
        self.batch_total = len(self._queue)
        if self._queue:
            log.info("resuming %d queued reels from the last run", len(self._queue))

    def _save(self) -> None:
        """Persist the in-progress reel plus the queue. Call with self._cond held."""
        state = {"current": self.current["id"] if self.current else None,
                 "current_crashes": self._crashes if self.current else 0,
                 "queue": list(self._queue)}
        try:
            _queue_file().write_text(json.dumps(state))
        except OSError:
            log.warning("couldn't save the analysis queue", exc_info=True)

    def enqueue(self, ids: list[str]) -> int:
        with self._cond:
            if not self._queue and not self.current:
                self.done = self.failed = self.batch_total = 0  # new batch
            self.halted = None
            known = set(self._queue) | ({self.current["id"]} if self.current else set())
            new = [i for i in dict.fromkeys(ids) if i not in known]
            self._queue.extend(new)
            self.batch_total += len(new)
            self._save()
            self._cond.notify()
        return len(new)

    def cancel(self) -> int:
        with self._cond:
            n = len(self._queue)
            self._queue.clear()
            self.batch_total -= n
            self._save()
        return n

    def status(self) -> dict:
        with self._cond:
            queued = list(self._queue)
            current = dict(self.current) if self.current else None
        if current:
            current["elapsed_seconds"] = round(time.time() - current.pop("started"), 1)
        return {
            "running": bool(current or queued),
            "current": current,
            "queued": len(queued),
            "queued_ids": queued[:500],
            "batch_total": self.batch_total,
            "done": self.done,
            "failed": self.failed,
            "recent": list(self.recent),
            "halted": self.halted,
        }

    def _run(self) -> None:
        conn = None
        while True:
            with self._cond:
                while not self._queue:
                    self._cond.wait()
                rid = self._queue.popleft()
                self.current = {"id": rid, "started": time.time()}
                self._save()
            try:
                settings = load_settings()
                conn = conn or db.connect(settings.db_path)
                row = conn.execute("SELECT username FROM reels WHERE id = ?", (rid,)).fetchone()
                if self.current is not None and row:
                    self.current["creator"] = row["username"]
                result = pipeline.process_reel(conn, rid, settings)
            except AccountError as e:
                with self._cond:
                    self.batch_total -= len(self._queue) + 1
                    self._queue.clear()
                    self.halted = str(e)
                    self.current = None
                    self._crashes = 0
                    self._save()
                log.warning("queue stopped: %s", e)
                continue
            except Exception as e:  # never let the worker die
                log.exception("worker error on %s", rid)
                result = {"id": rid, "status": "failed", "error": str(e)[:500]}
            with self._cond:
                if result["status"] == "analyzed":
                    self.done += 1
                else:
                    self.failed += 1
                self.recent.appendleft({**result, "finished_at": int(time.time())})
                self.current = None
                self._crashes = 0
                self._save()


jobs = JobManager()
