"""Laya decision layer: fast, local, typed decisions over reels (github.com/NandhaKishorM/laya).

Laya is a non-generative decision model: given a reel's text it answers typed questions in one
forward pass — `choice` (pick a label), `score` (ordinal level) or `noul` (probability of yes).
Here it powers three things:
  * signals: category, content type, purpose, "actionable" and "revisit value" for every reel,
  * ask():  any custom question asked across the library ("Is this a toddler activity?"),
  * a free local analysis engine (providers.py, type "laya") that files reels without an LLM.

It needs text, so a reel gets signals once it has a caption, transcript or AI summary.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable

from . import db
from .config import data_dir

log = logging.getLogger("instamcp.decisions")

CATEGORY_HINTS = {
    "Food & Recipes": "cooking, recipes, restaurants, food",
    "Fitness & Health": "workouts, exercise, nutrition, health, wellbeing",
    "Tech & AI": "AI tools, gadgets, apps, software, technology news",
    "Programming & Dev": "coding, developers, GitHub, software engineering",
    "Business & Money": "business, marketing, investing, finance, careers",
    "Productivity & Learning": "study tips, productivity, learning skills, education",
    "Design & Creativity": "design, art, photography, crafts, creative work",
    "Travel & Places": "travel, destinations, places to visit, hotels",
    "Fashion & Beauty": "outfits, style, skincare, makeup, hair",
    "Home & DIY": "home decor, cleaning, organizing, DIY projects, gardening",
    "Music & Entertainment": "music, movies, shows, celebrities, dance",
    "Humor & Memes": "jokes, memes, funny skits",
    "Motivation & Mindset": "motivation, self-improvement, quotes, mindset",
    "Science & Education": "science, history, explainers, facts",
    "Shopping & Products": "product finds, deals, reviews, gift ideas",
    "Parenting & Relationships": "kids, parenting, baby names, family, relationships",
    "Sports": "sports, athletes, matches",
    "Other": "anything else",
}

CONTENT_TYPE_HINTS = {
    "tutorial": "step-by-step how-to",
    "recipe": "how to cook a dish",
    "tips": "a list of tips or hacks",
    "review": "opinion on a product, place or service",
    "recommendation_list": "a list of things to try, buy, watch or use",
    "explainer": "explains a concept or topic",
    "news": "news or announcement",
    "workout": "an exercise routine",
    "inspiration": "aesthetic or motivational content",
    "entertainment": "comedy, music, a story, just for fun",
    "story": "a personal story or vlog",
    "product_showcase": "shows off or advertises a product",
    "place_guide": "where to go, eat or stay",
    "other": "anything else",
}

PURPOSES = {
    "learn": "teaches a skill, facts or how-to",
    "entertain": "funny, music, story, just for fun",
    "inspire": "motivation, aesthetics, ideas, dream destinations",
    "shop": "products, deals or things to buy",
}

# Measured on sample reels:
#  - choice questions (category, type): plain labels on the multilingual checkpoint classified best
#    (8/8); the English checkpoint and descriptive hints both misfiled kids/parenting reels.
#  - yes/no and scale questions: on English text the English checkpoint separated yes from no far
#    more cleanly (e.g. 0.91 vs 0.15 against 0.97 vs 0.88), so those use Laya's Router ("auto"),
#    which sends English to the English checkpoint and everything else to the multilingual one.
DEFAULT_MODEL = "multilingual"
CHOICE_MODEL = "multilingual"
JUDGEMENT_MODEL = "auto"

SIGNAL_QUESTIONS: dict[str, dict[str, Any]] = {
    "category": {"type": "choice", "instructions": "What is this saved Instagram reel mainly about?",
                 "criteria": {c: c for c in CATEGORY_HINTS}},
    "content_type": {"type": "choice", "instructions": "What kind of reel is this?",
                     "criteria": {t: t.replace("_", " ") for t in CONTENT_TYPE_HINTS}},
    "purpose": {"type": "choice", "instructions": "Why would someone watch this reel?", "criteria": PURPOSES},
    "actionable": {"type": "noul", "instructions": "Does the reel teach something the viewer can do or use "
                   "(steps, a recipe, a tool, an exercise, a product, a place)?"},
    "revisit": {"type": "score", "instructions": "How useful is this reel to come back to later?",
                "criteria": ["not useful", "somewhat useful", "very useful"]},
}
SIGNAL_IDS = tuple(SIGNAL_QUESTIONS)


def model_for(question: dict) -> str:
    return CHOICE_MODEL if question["type"] == "choice" else JUDGEMENT_MODEL


def predict_questions(states: list[str], questions: dict[str, dict]) -> list[dict]:
    """Answer a mixed question set, each question on the checkpoint that suits its type.
    Returns one {"answers": {...}, "models": {...}} per state."""
    groups: dict[str, dict] = {}
    for qid, q in questions.items():
        groups.setdefault(model_for(q), {})[qid] = q
    merged = [{"answers": {}, "models": {}} for _ in states]
    for model, qs in groups.items():
        for out, res in zip(merged, predict_batch(states, qs, model)):
            out["answers"].update(res["answers"])
            routed = (res.get("routing") or {}).get("model", model)
            out["models"].update({qid: routed for qid in qs})
            out.setdefault("routing", res.get("routing"))
    return merged
MAX_STATE_CHARS = 2400

_router = None
_router_lock = threading.Lock()
_predict_lock = threading.Lock()  # one forward pass at a time; the model isn't re-entrant-safe on MPS


def available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("laya") is not None
    except Exception:
        return False


def router(model_default: str = DEFAULT_MODEL):
    """Lazily load Laya's Router (downloads the checkpoint into <data_dir>/models on first use)."""
    global _router
    with _router_lock:
        if _router is None:
            os.environ.setdefault("HF_HOME", str(data_dir() / "models"))
            from laya import Router

            _router = Router(default=model_default)
        return _router


def is_loaded() -> bool:
    return _router is not None


def predict_batch(states: list[str], questions: dict, model: str | None = DEFAULT_MODEL) -> list[dict]:
    """model: a checkpoint name, or "auto"/None to let Laya's Router pick by language."""
    reqs = [{"state": s, "questions": questions, **({"model": model} if model and model != "auto" else {})}
            for s in states]
    with _predict_lock:
        return router().predict_batch(reqs, batch_size=8, sort_by_length=True)


# ------------------------------------------------------------------ reel text

def reel_state(row, collections: list[str] | None = None) -> str:
    """The text Laya reads for a reel: AI summary first (best signal), then caption, then speech."""
    parts = []
    if row["title"]:
        parts.append(f"Title: {row['title']}")
    if row["summary"]:
        parts.append(f"Summary: {row['summary']}")
    if row["caption"]:
        parts.append(f"Caption: {row['caption']}")
    if row["on_screen_text"]:
        parts.append(f"On screen: {row['on_screen_text']}")
    if row["transcript"]:
        parts.append(f"Speech: {row['transcript']}")
    if collections:
        parts.append(f"Saved in: {', '.join(collections)}")
    return "\n".join(parts)[:MAX_STATE_CHARS]


def has_text(row) -> bool:
    return bool(row["summary"] or row["caption"] or row["transcript"])


TEXT_SQL = "(r.summary IS NOT NULL OR r.caption IS NOT NULL OR r.transcript IS NOT NULL)"


# ------------------------------------------------------------------ signals

def signals_from_answers(answers: dict) -> dict[str, dict]:
    out = {}
    for qid in SIGNAL_IDS:
        a = answers.get(qid)
        if not a:
            continue
        if a["type"] == "choice":
            out[qid] = {"answer": a["choice"], "value": None, "confidence": a.get("confidence")}
        elif a["type"] == "noul":
            out[qid] = {"answer": "yes" if a["noul"] >= 0.5 else "no", "value": a["noul"],
                        "confidence": a.get("confidence")}
        else:  # score: 0 .. n-1 expected level
            level = ["low", "medium", "high"][min(2, max(0, round(a["score"])))]
            out[qid] = {"answer": level, "value": a["score"], "confidence": a.get("confidence")}
    return out


def store_signals(conn, reel_id: str, signals: dict[str, dict], model: str) -> None:
    now = int(time.time())
    conn.executemany(
        """INSERT INTO decisions (reel_id, qid, answer, value, confidence, model, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(reel_id, qid) DO UPDATE SET answer = excluded.answer, value = excluded.value,
             confidence = excluded.confidence, model = excluded.model, created_at = excluded.created_at""",
        [(reel_id, q, s["answer"], s["value"], s["confidence"], model, now) for q, s in signals.items()],
    )
    conn.commit()


def reel_signals(conn, reel_id: str) -> dict:
    return {r["qid"]: {"answer": r["answer"], "value": r["value"], "confidence": r["confidence"]}
            for r in conn.execute("SELECT * FROM decisions WHERE reel_id = ?", (reel_id,))}


def compute_signals(conn, ids: list[str], on_progress: Callable[[int, int], None] | None = None,
                    chunk: int = 16) -> int:
    done = 0
    for start in range(0, len(ids), chunk):
        batch = ids[start:start + chunk]
        rows = {r["id"]: r for r in conn.execute(
            f"SELECT * FROM reels WHERE id IN ({','.join('?' * len(batch))})", batch)}
        todo = [i for i in batch if i in rows and has_text(rows[i])]
        if todo:
            states = [reel_state(rows[i], db.reel_collections(conn, i)) for i in todo]
            results = predict_questions(states, SIGNAL_QUESTIONS)
            for rid, res in zip(todo, results):
                store_signals(conn, rid, signals_from_answers(res["answers"]), "laya")
        done += len(batch)
        if on_progress:
            on_progress(done, len(ids))
    return done


def ids_missing_signals(conn, limit: int = 100000, collection: str | None = None) -> list[str]:
    sql = f"""SELECT r.id FROM reels r WHERE {TEXT_SQL}
              AND r.id NOT IN (SELECT reel_id FROM decisions WHERE qid = 'revisit')"""
    args: list[Any] = []
    if collection:
        sql += """ AND r.id IN (SELECT rc.reel_id FROM reel_collections rc JOIN collections c
                   ON c.id = rc.collection_id WHERE c.name = ? COLLATE NOCASE)"""
        args.append(collection)
    return [r["id"] for r in conn.execute(sql + " ORDER BY r.saved_at DESC NULLS LAST LIMIT ?", [*args, limit])]


class SignalsJob:
    """Background computation of signals for many reels, with progress for the UI."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {"running": False, "done": 0, "total": 0, "error": None, "finished_at": None}

    def start(self, db_path, ids: list[str]) -> bool:
        with self.lock:
            if self.state["running"]:
                return False
            self.state = {"running": True, "done": 0, "total": len(ids), "error": None, "finished_at": None}
        threading.Thread(target=self._run, args=(db_path, ids), daemon=True, name="laya-signals").start()
        return True

    def _run(self, db_path, ids: list[str]) -> None:
        conn = db.connect(db_path)
        try:
            def progress(done: int, total: int) -> None:
                self.state["done"] = done
            compute_signals(conn, ids, progress)
        except Exception as e:
            log.exception("signals job failed")
            self.state["error"] = str(e)[:500]
        finally:
            self.state["running"] = False
            self.state["finished_at"] = int(time.time())
            conn.close()

    def status(self) -> dict:
        return dict(self.state)


signals_job = SignalsJob()


# ------------------------------------------------------------------ ask your library

def build_question(question: str, answer_type: str, options: list[str] | None) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("Type a question")
    if answer_type == "yes_no":
        return {"type": "noul", "instructions": question}
    opts = [o.strip() for o in (options or []) if o and o.strip()]
    if answer_type == "choice":
        if len(opts) < 2:
            raise ValueError("Give at least two options")
        if any(o.lower() in ("yes", "no", "true", "false") for o in opts):
            raise ValueError("For yes/no questions pick the Yes/No type; choice options need descriptive labels")
        return {"type": "choice", "instructions": question, "criteria": {o: o for o in opts[:30]}}
    if answer_type == "scale":
        opts = opts or ["low", "medium", "high"]
        if len(opts) < 2:
            raise ValueError("A scale needs at least two levels, lowest first")
        return {"type": "score", "instructions": question, "criteria": opts[:10]}
    raise ValueError("answer_type must be yes_no, choice or scale")


def ask(conn, question: str, answer_type: str = "yes_no", options: list[str] | None = None,
        collection: str | None = None, category: str | None = None, limit: int = 200,
        thumbs_dir=None) -> dict:
    """Ask one typed question about every reel in scope; results ranked by the answer."""
    q = build_question(question, answer_type, options)
    scope, args = "", []
    if collection:
        scope += """ AND r.id IN (SELECT rc.reel_id FROM reel_collections rc JOIN collections c
                     ON c.id = rc.collection_id WHERE c.name = ? COLLATE NOCASE)"""
        args.append(collection)
    if category:
        scope += " AND COALESCE(r.category, (SELECT answer FROM decisions d WHERE d.reel_id = r.id" \
                 " AND d.qid = 'category')) = ? COLLATE NOCASE"
        args.append(category)
    rows = conn.execute(f"SELECT r.* FROM reels r WHERE {TEXT_SQL}{scope} ORDER BY r.saved_at DESC NULLS LAST LIMIT ?",
                        [*args, max(1, min(limit, 2000))]).fetchall()
    in_scope_no_text = conn.execute(f"SELECT COUNT(*) FROM reels r WHERE NOT {TEXT_SQL}{scope}", args).fetchone()[0]
    if not rows:
        return {"question": question, "answer_type": answer_type, "asked": 0, "results": [],
                "skipped_without_text": in_scope_no_text}

    t = time.time()
    results = predict_batch([reel_state(r, db.reel_collections(conn, r["id"])) for r in rows], {"q": q}, model_for(q))
    out = []
    for row, res in zip(rows, results):
        a = res["answers"]["q"]
        reel = db.reel_to_dict(conn, row)
        if thumbs_dir and (thumbs_dir / f"{row['id']}.jpg").exists():
            reel["thumbnail"] = f"/api/reels/{row['id']}/thumb"
        item = {"reel": reel, "confidence": a.get("confidence")}
        if a["type"] == "noul":
            item.update(answer="yes" if a["noul"] >= 0.5 else "no", probability=a["noul"])
        elif a["type"] == "choice":
            item.update(answer=a["choice"], probability=a["probabilities"].get(a["choice"]))
        else:
            levels = q["criteria"]
            item.update(answer=levels[min(len(levels) - 1, max(0, round(a["score"])))], score=a["score"])
        out.append(item)

    if answer_type == "yes_no":
        out.sort(key=lambda x: -x["probability"])
    elif answer_type == "scale":
        out.sort(key=lambda x: -x["score"])
    else:
        out.sort(key=lambda x: (x["answer"], -(x["probability"] or 0)))
    summary: dict[str, int] = {}
    for x in out:
        summary[x["answer"]] = summary.get(x["answer"], 0) + 1
    return {"question": question, "answer_type": answer_type, "asked": len(out), "seconds": round(time.time() - t, 1),
            "summary": summary, "results": out, "skipped_without_text": in_scope_no_text}


# ------------------------------------------------------------------ analytics

def analytics(conn) -> dict:
    def counts(sql: str, args: tuple = ()) -> dict:
        return {r[0]: r[1] for r in conn.execute(sql, args)}

    months: dict[str, dict] = {}
    for r in conn.execute(
        """SELECT strftime('%Y-%m', r.saved_at, 'unixepoch') m,
                  COALESCE(r.category, d.answer, '(not analyzed)') c, COUNT(*) n
           FROM reels r LEFT JOIN decisions d ON d.reel_id = r.id AND d.qid = 'category'
           WHERE r.saved_at IS NOT NULL GROUP BY m, c ORDER BY m"""
    ):
        bucket = months.setdefault(r["m"], {"month": r["m"], "total": 0, "by_category": {}})
        bucket["total"] += r["n"]
        bucket["by_category"][r["c"]] = r["n"]

    signal = lambda qid: counts("SELECT answer, COUNT(*) FROM decisions WHERE qid = ? GROUP BY answer ORDER BY 2 DESC", (qid,))

    collections = []
    for c in conn.execute(
        """SELECT c.name, COUNT(*) n,
                  SUM(r.status = 'analyzed') analyzed,
                  SUM(CASE WHEN d.answer = 'yes' THEN 1 ELSE 0 END) actionable,
                  SUM(CASE WHEN d.answer IS NOT NULL THEN 1 ELSE 0 END) with_signals
           FROM collections c JOIN reel_collections rc ON rc.collection_id = c.id
           JOIN reels r ON r.id = rc.reel_id
           LEFT JOIN decisions d ON d.reel_id = r.id AND d.qid = 'actionable'
           GROUP BY c.id ORDER BY n DESC"""
    ):
        top = conn.execute(
            """SELECT COALESCE(r.category, d.answer) cat, COUNT(*) n FROM reels r
               JOIN reel_collections rc ON rc.reel_id = r.id JOIN collections c ON c.id = rc.collection_id
               LEFT JOIN decisions d ON d.reel_id = r.id AND d.qid = 'category'
               WHERE c.name = ? AND COALESCE(r.category, d.answer) IS NOT NULL
               GROUP BY cat ORDER BY n DESC LIMIT 1""", (c["name"],)).fetchone()
        collections.append({
            "name": c["name"], "reels": c["n"], "analyzed": c["analyzed"] or 0,
            "with_signals": c["with_signals"] or 0, "actionable": c["actionable"] or 0,
            "top_category": top["cat"] if top else None,
        })

    total = conn.execute("SELECT COUNT(*) FROM reels").fetchone()[0]
    with_text = conn.execute(f"SELECT COUNT(*) FROM reels r WHERE {TEXT_SQL}").fetchone()[0]
    with_signals = conn.execute("SELECT COUNT(DISTINCT reel_id) FROM decisions WHERE qid = 'revisit'").fetchone()[0]
    return {
        "total_reels": total,
        "with_text": with_text,
        "with_signals": with_signals,
        "missing_signals": len(ids_missing_signals(conn)),
        "laya_available": available(),
        "laya_loaded": is_loaded(),
        "saves_by_month": list(months.values()),
        "categories": counts("SELECT category, COUNT(*) FROM reels WHERE category IS NOT NULL GROUP BY category ORDER BY 2 DESC"),
        "signal_categories": signal("category"),
        "content_types": signal("content_type"),
        "purposes": signal("purpose"),
        "actionable": signal("actionable"),
        "revisit": signal("revisit"),
        "collections": collections,
        "signals_job": signals_job.status(),
    }


def dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, indent=2)
