"""Ask the configured AI engine(s) to understand a reel (frames + transcript + caption) and pull out links/resources."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

from . import engines, providers
from .config import Settings
from .media import MediaBundle
from .providers import AccountError

log = logging.getLogger("instamcp.analyze")

__all__ = ["AccountError", "analyze", "enrich_links"]

CATEGORIES = [
    "Food & Recipes", "Fitness & Health", "Tech & AI", "Programming & Dev", "Business & Money",
    "Productivity & Learning", "Design & Creativity", "Travel & Places", "Fashion & Beauty",
    "Home & DIY", "Music & Entertainment", "Humor & Memes", "Motivation & Mindset",
    "Science & Education", "Shopping & Products", "Parenting & Relationships", "Sports", "Other",
]

CONTENT_TYPES = [
    "tutorial", "recipe", "tips", "review", "recommendation_list", "explainer", "news",
    "workout", "inspiration", "entertainment", "story", "product_showcase", "place_guide", "other",
]

RESOURCE_KINDS = [
    "website", "tool", "app", "product", "book", "course", "place", "recipe", "person",
    "video", "music", "article", "repo", "other",
]

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title", "summary", "key_points", "category", "content_type", "topics", "tags",
        "why_saved", "on_screen_text", "language", "resources",
    ],
    "properties": {
        "title": {"type": "string", "description": "Short descriptive title (max ~10 words)."},
        "summary": {"type": "string", "description": "2-4 sentence summary of what the reel actually shows/says."},
        "key_points": {"type": "array", "items": {"type": "string"},
                       "description": "The concrete takeaways: steps, ingredients, tips, claims, names."},
        "category": {"type": "string", "enum": CATEGORIES},
        "content_type": {"type": "string", "enum": CONTENT_TYPES},
        "topics": {"type": "array", "items": {"type": "string"}, "description": "2-5 specific topics."},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "5-12 lowercase search tags."},
        "why_saved": {"type": "string",
                      "description": "One line: the most likely reason someone saved this / what to use it for later."},
        "on_screen_text": {"type": "string", "description": "Important text visible in the frames (empty if none)."},
        "language": {"type": "string", "description": "ISO 639-1 code of the main language."},
        "resources": {
            "type": "array",
            "description": "Every concrete thing the viewer might want to look up or open.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "kind", "url", "source", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": RESOURCE_KINDS},
                    "url": {"type": "string",
                            "description": "Exact URL if shown/said; else the official homepage only if you are confident; else empty."},
                    "source": {"type": "string", "enum": ["caption", "spoken", "on_screen", "inferred"]},
                    "description": {"type": "string", "description": "What it is and why it's in the reel."},
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You catalogue Instagram reels that a person saved, so they can find and use them later.
You receive sampled keyframes, the speech transcript, the caption, the creator and the saved-collection names.
Describe what the reel really contains — not what the caption hypes. Be specific: name the dishes, tools, apps,
exercises, places, books, products, people and numbers that appear. Collection names are the user's own
filing system and are a strong hint about why they saved it.

For resources: include URLs that appear in the caption, on screen or are spoken. For named tools, products,
sites, books or places with no URL given, add the official URL only when you are confident it is correct;
otherwise leave url empty (a search link is generated automatically). Never invent shortened or tracking links.
If an input is missing (no transcript, no frames), work from what you have and say less rather than guess."""


def _normalize(raw: dict) -> dict:
    """Make any engine's output fit the schema: fill gaps, map labels onto the allowed values."""
    def pick(value: Any, allowed: list[str], default: str) -> str:
        v = str(value or "").strip()
        for a in allowed:
            if v.lower() == a.lower() or v.lower().replace(" ", "_") == a.lower():
                return a
        return default

    def strings(v: Any) -> list[str]:
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",")]
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    out = {
        "title": str(raw.get("title") or "").strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "key_points": strings(raw.get("key_points")),
        "category": pick(raw.get("category"), CATEGORIES, "Other"),
        "content_type": pick(raw.get("content_type"), CONTENT_TYPES, "other"),
        "topics": strings(raw.get("topics")),
        "tags": [t.lower() for t in strings(raw.get("tags"))],
        "why_saved": str(raw.get("why_saved") or "").strip(),
        "on_screen_text": str(raw.get("on_screen_text") or "").strip(),
        "language": str(raw.get("language") or "").strip()[:8],
        "resources": [],
    }
    for r in raw.get("resources") or []:
        if not isinstance(r, dict) or not str(r.get("name") or "").strip():
            continue
        out["resources"].append({
            "name": str(r["name"]).strip(),
            "kind": pick(r.get("kind"), RESOURCE_KINDS, "other"),
            "url": str(r.get("url") or "").strip(),
            "source": pick(r.get("source"), ["caption", "spoken", "on_screen", "inferred"], "inferred"),
            "description": str(r.get("description") or "").strip(),
        })
    if not out["title"] and not out["summary"]:
        raise RuntimeError("The model returned an empty analysis")
    return out


def analyze(bundle: MediaBundle, url: str, username: str | None, collections: list[str],
            settings: Settings) -> dict[str, Any]:
    facts = {
        "url": url,
        "creator": bundle.uploader or username,
        "duration_seconds": bundle.duration,
        "saved_in_collections": collections or None,
        "caption": bundle.caption,
        "transcript": bundle.transcript or "(no speech detected)",
    }
    text = "Reel details:\n" + json.dumps(facts, ensure_ascii=False, indent=2)

    chain = engines.chain()
    if not chain:
        raise AccountError("No AI engine is configured. Add one in Settings → AI engines.")
    errors: list[Exception] = []
    for i, engine in enumerate(chain):
        try:
            raw, model = providers.generate_json(engine, SYSTEM_PROMPT, bundle.frames, text, ANALYSIS_SCHEMA)
            result = _normalize(raw)
            if raw.get("_signals"):
                result["_signals"] = raw["_signals"]
            break
        except Exception as e:
            errors.append(e)
            if i + 1 < len(chain):
                log.warning("%s failed (%s); trying fallback %s", engine.get("name"), e, chain[i + 1].get("name"))
                continue
            if all(isinstance(x, AccountError) for x in errors):
                # Every engine is unusable: stop the queue rather than failing reel after reel.
                raise AccountError(" ".join(str(x) for x in errors)) from None
            raise
    result["resources"] = enrich_links(result["resources"], bundle.caption, settings.verify_links)
    result["_model"] = f"{engine.get('name')} · {model}"
    return result


URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def enrich_links(resources: list[dict], caption: str | None, verify: bool) -> list[dict]:
    """Add caption URLs the model missed, a search link for every resource, and reachability checks."""
    known = {r.get("url", "").rstrip("/") for r in resources if r.get("url")}
    for u in URL_RE.findall(caption or ""):
        u = u.rstrip(".,!")
        if u.rstrip("/") not in known:
            resources.append({"name": u, "kind": "website", "url": u, "source": "caption",
                              "description": "Link from the caption"})
            known.add(u.rstrip("/"))

    with httpx.Client(follow_redirects=True, timeout=8.0,
                      headers={"User-Agent": "Mozilla/5.0 (instamcp link check)"}) as http:
        for r in resources:
            r["search_url"] = "https://www.google.com/search?q=" + quote_plus(
                r["name"] if r.get("kind") in ("website", "repo") else f'{r["name"]} {r.get("kind", "")}'.strip()
            )
            if r.get("url") and verify:
                r["verified"] = _reachable(http, r["url"])
                if r["verified"] == 0 and r.get("source") == "inferred":
                    r["url"] = ""  # a guessed URL that doesn't resolve is worse than none
            if not r.get("url"):
                r.pop("verified", None)
    return resources


def _reachable(http: httpx.Client, url: str) -> int:
    try:
        resp = http.head(url)
        if resp.status_code in (403, 405) or resp.status_code >= 500:
            resp = http.get(url)
        # Many sites block bots with 403/429; treat those as "exists".
        return 1 if resp.status_code < 400 or resp.status_code in (403, 429) else 0
    except httpx.HTTPError:
        return 0
