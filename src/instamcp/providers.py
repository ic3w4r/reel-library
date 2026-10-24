"""Provider adapters: send frames + text to an engine and get back JSON matching a schema.

Every adapter exposes the same three calls:
    generate_json(engine, system, frames, text, schema) -> (dict, model_id)
    check(engine) -> model_id          # tiny real request: key, model access, billing
    list_models(engine) -> [model ids]
and turns "nothing will work until the user fixes something" failures into AccountError.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic
import openai

from . import engines
from .media import b64

log = logging.getLogger("instamcp.providers")


class AccountError(RuntimeError):
    """Engine-level problem (bad key, no credits, unknown model, server down): no reel can succeed
    with this engine until the user fixes it."""


# ------------------------------------------------------------------ Anthropic (native)

def _anthropic_client(engine: dict) -> anthropic.Anthropic:
    key = engines.api_key(engine)
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def _anthropic_error(engine: dict, e: Exception) -> Exception:
    name = engine.get("name", "Claude")
    msg = str(e).lower()
    if isinstance(e, anthropic.AuthenticationError):
        return AccountError(f"{name}: the API key was rejected. Check it in Settings → AI engines.")
    if isinstance(e, anthropic.PermissionDeniedError):
        return AccountError(f"{name}: this key can't use model {engine.get('model')}. Pick another model.")
    if isinstance(e, anthropic.NotFoundError):
        return AccountError(f"{name}: model {engine.get('model')} was not found. Use “Fetch models”.")
    if isinstance(e, anthropic.APIStatusError) and ("credit balance" in msg or "billing" in msg):
        return AccountError(f"{name}: the Anthropic account has no credits left. Add credits at "
                            "console.anthropic.com → Settings → Billing, or switch engines.")
    return e


def _supports_effort(model: str) -> bool:
    return not re.search(r"claude-(3|haiku-4-5|sonnet-4-5|opus-4-1|opus-4-0|sonnet-4-0)", model)


def _supports_fallbacks(model: str) -> bool:
    return bool(re.match(r"claude-(opus-5|fable-5|sonnet-5-5)", model))


def _anthropic_generate(engine: dict, system: str, frames: list[bytes], text: str,
                        schema: dict) -> tuple[dict, str]:
    content: list[dict[str, Any]] = []
    for i, frame in enumerate(frames):
        content.append({"type": "text", "text": f"Frame {i + 1}/{len(frames)}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(frame)}})
    content.append({"type": "text", "text": text})

    model = engine["model"]
    output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
    if _supports_effort(model):
        output_config["effort"] = engine.get("effort") or "medium"
    kwargs: dict[str, Any] = {}
    if _supports_fallbacks(model):
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    try:
        response = _anthropic_client(engine).beta.messages.create(
            model=model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": content}],
            output_config=output_config, **kwargs,
        )
    except anthropic.APIError as e:
        raise _anthropic_error(engine, e) from None
    if response.stop_reason == "refusal":
        raise RuntimeError("The model declined to analyze this reel")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("The analysis was cut off (max_tokens)")
    text_out = next(b.text for b in response.content if b.type == "text")
    return json.loads(text_out), response.model


def _anthropic_check(engine: dict) -> str:
    model = engine["model"]
    extra = {"output_config": {"effort": "low"}} if _supports_effort(model) else {}
    try:
        r = _anthropic_client(engine).messages.create(
            model=model, max_tokens=64, messages=[{"role": "user", "content": "Reply with OK."}], **extra)
    except anthropic.APIError as e:
        raise _anthropic_error(engine, e) from None
    return r.model


def _anthropic_models(engine: dict) -> list[str]:
    try:
        return [m.id for m in _anthropic_client(engine).models.list(limit=100)]
    except anthropic.APIError as e:
        raise _anthropic_error(engine, e) from None


# ------------------------------------------------------------------ OpenAI-compatible

# Remember what each engine's endpoint accepts, so we only probe once per process.
_learned: dict[str, dict[str, Any]] = {}


def _openai_client(engine: dict) -> openai.OpenAI:
    return openai.OpenAI(
        api_key=engines.api_key(engine) or "not-needed",  # local servers ignore it
        base_url=engine.get("base_url") or None,
        timeout=600, max_retries=2,
    )


def _openai_error(engine: dict, e: Exception) -> Exception:
    name = engine.get("name", "Engine")
    msg = str(e).lower()
    if isinstance(e, openai.AuthenticationError):
        return AccountError(f"{name}: the API key was rejected. Check it in Settings → AI engines.")
    if isinstance(e, openai.PermissionDeniedError):
        return AccountError(f"{name}: access denied for model {engine.get('model')}.")
    if isinstance(e, openai.NotFoundError):
        return AccountError(f"{name}: model “{engine.get('model')}” was not found at {engine.get('base_url')}. "
                            "Use “Fetch models” to pick one.")
    if isinstance(e, openai.APIConnectionError):
        return AccountError(f"{name}: can't reach {engine.get('base_url')}. Is the server running?")
    if isinstance(e, openai.APIStatusError) and (
        e.status_code == 402 or "insufficient_quota" in msg or "quota" in msg or "credit" in msg
    ):
        return AccountError(f"{name}: out of credits or quota. Top up the account, or switch engines.")
    return e


def _schema_instructions(schema: dict) -> str:
    return ("\n\nRespond with ONLY a JSON object (no markdown, no commentary) that matches this JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False))


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise RuntimeError(f"The model didn't return JSON: {text[:200]!r}") from None


def _openai_generate(engine: dict, system: str, frames: list[bytes], text: str,
                     schema: dict) -> tuple[dict, str]:
    learned = _learned.setdefault(engine["id"], {})
    mode = learned.get("json_mode") or (engine.get("json_mode") if engine.get("json_mode") != "auto" else "schema")
    use_images = engine.get("vision", True) and not learned.get("no_vision") and bool(frames)
    client = _openai_client(engine)

    while True:
        content: list[dict[str, Any]] = []
        if use_images:
            for i, frame in enumerate(frames):
                content.append({"type": "text", "text": f"Frame {i + 1}/{len(frames)}"})
                content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64(frame)}"}})
        note = "\n\n(Video frames are not available to you; rely on the transcript and caption.)" \
            if frames and not use_images else ""
        content.append({"type": "text", "text": text + note})

        sys_prompt = system if mode == "schema" else system + _schema_instructions(schema)
        kwargs: dict[str, Any] = {}
        if mode == "schema":
            kwargs["response_format"] = {"type": "json_schema",
                                         "json_schema": {"name": "reel_analysis", "schema": schema, "strict": True}}
        elif mode == "object":
            kwargs["response_format"] = {"type": "json_object"}

        try:
            r = client.chat.completions.create(
                model=engine["model"],
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": content}],
                **kwargs,
            )
        except openai.BadRequestError as e:
            msg = str(e).lower()
            # Endpoint doesn't do strict schemas / JSON mode → step down and remember.
            if mode != "none" and any(w in msg for w in ("response_format", "json_schema", "json_object",
                                                         "strict", "schema", "not supported")):
                mode = {"schema": "object", "object": "none"}[mode]
                learned["json_mode"] = mode
                log.info("%s: falling back to json mode %r", engine.get("name"), mode)
                continue
            # Text-only model → drop the frames and remember.
            if use_images and any(w in msg for w in ("image", "vision", "multimodal", "content type")):
                use_images = False
                learned["no_vision"] = True
                log.info("%s: model has no vision, sending text only", engine.get("name"))
                continue
            raise _openai_error(engine, e) from None
        except openai.APIError as e:
            raise _openai_error(engine, e) from None

        choice = r.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError("The analysis was cut off (output token limit)")
        refusal = getattr(choice.message, "refusal", None)
        if refusal:
            raise RuntimeError(f"The model declined: {refusal}")
        return _parse_json(choice.message.content or ""), r.model or engine["model"]


def _openai_check(engine: dict) -> str:
    try:
        r = _openai_client(engine).chat.completions.create(
            model=engine["model"], messages=[{"role": "user", "content": "Reply with OK."}])
    except openai.APIError as e:
        raise _openai_error(engine, e) from None
    return r.model or engine["model"]


def _openai_models(engine: dict) -> list[str]:
    try:
        return sorted(m.id for m in _openai_client(engine).models.list())
    except openai.APIError as e:
        raise _openai_error(engine, e) from None


# ------------------------------------------------------------------ Laya (local decision model)

_HASHTAG = re.compile(r"#(\w+)")


def _laya_generate(engine: dict, system: str, frames: list[bytes], text: str,
                   schema: dict) -> tuple[dict, str]:
    """No text generation: Laya files the reel (category, type, signals) and the rest is taken
    from the reel's own caption and speech."""
    from . import decisions

    facts = json.loads(text.split("\n", 1)[1]) if text.startswith("Reel details:") else {}
    caption = (facts.get("caption") or "").strip()
    speech = facts.get("transcript") or ""
    speech = "" if speech.startswith("(no speech") else speech.strip()
    if not caption and not speech:
        raise RuntimeError("Laya needs text, and this reel has no caption or speech. Analyze it with an LLM engine.")
    collections = facts.get("saved_in_collections") or []
    state = "\n".join(filter(None, [
        f"Caption: {caption}" if caption else "", f"Speech: {speech}" if speech else "",
        f"Saved in: {', '.join(collections)}" if collections else "",
    ]))[:decisions.MAX_STATE_CHARS]
    try:
        res = decisions.predict_questions([state], decisions.SIGNAL_QUESTIONS)[0]
    except Exception as e:
        raise AccountError(f"{engine.get('name', 'Laya')}: the local model failed to load or run ({e}).") from e
    signals = decisions.signals_from_answers(res["answers"])

    first_line = next((ln for ln in caption.splitlines() if _HASHTAG.sub("", ln).strip()), "")
    title = _HASHTAG.sub("", first_line).strip(" -–:|") or (speech[:60] + "…" if speech else "")
    if len(title) > 80:
        title = title[:77].rsplit(" ", 1)[0] + "…"
    body = _HASHTAG.sub("", caption).strip() or speech
    summary = body if len(body) <= 400 else body[:397].rsplit(" ", 1)[0] + "…"
    purpose = signals.get("purpose", {}).get("answer")
    why = {"learn": "To learn from it later", "entertain": "Because it was fun",
           "inspire": "For inspiration", "shop": "Something to buy or check out"}.get(purpose or "", "")
    detection = (res.get("routing") or {}).get("detection") or {}
    out = {
        "title": title or "Untitled reel",
        "summary": summary,
        "key_points": [],
        "category": signals.get("category", {}).get("answer", "Other"),
        "content_type": signals.get("content_type", {}).get("answer", "other"),
        "topics": [],
        "tags": [t.lower() for t in _HASHTAG.findall(caption)][:12],
        "why_saved": why,
        "on_screen_text": "",
        "language": detection.get("language") or "",
        "resources": [],
        "_signals": signals,
    }
    return out, "laya"


def _laya_check(engine: dict) -> str:
    from . import decisions

    if not decisions.available():
        raise AccountError("Laya isn't installed. Install the 'decisions' extra (uv sync --extra decisions).")
    try:
        res = decisions.predict_batch(["Quick test: a pasta recipe."],
                                      {"t": {"type": "noul", "instructions": "Is this about food?"}},
                                      engine.get("model"))[0]
    except Exception as e:
        raise AccountError(f"Laya failed to load: {e}") from e
    return f"laya/{(res.get('routing') or {}).get('model', 'auto')} (local)"


def _laya_models(engine: dict) -> list[str]:
    return ["auto"]  # Laya picks the checkpoint per question type (see decisions.py)


# ------------------------------------------------------------------ dispatch

_ADAPTERS = {
    "anthropic": (_anthropic_generate, _anthropic_check, _anthropic_models),
    "openai": (_openai_generate, _openai_check, _openai_models),
    "laya": (_laya_generate, _laya_check, _laya_models),
}


def _adapter(engine: dict):
    if not engines.is_ready(engine):
        raise AccountError(f"{engine.get('name', 'Engine')} isn't set up yet (needs an API key, model"
                           " and URL). Finish it in Settings → AI engines.")
    return _ADAPTERS[engine["type"]]


def generate_json(engine: dict, system: str, frames: list[bytes], text: str, schema: dict) -> tuple[dict, str]:
    return _adapter(engine)[0](engine, system, frames, text, schema)


def check(engine: dict) -> str:
    return _adapter(engine)[1](engine)


def list_models(engine: dict) -> list[str]:
    return _ADAPTERS[engine["type"]][2](engine)
