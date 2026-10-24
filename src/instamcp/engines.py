"""AI engines: which model providers can analyze reels, and which one is primary / fallback.

Three adapter types cover nearly every provider:
  - "anthropic": Claude through the native Anthropic API.
  - "openai":    anything that speaks the OpenAI Chat Completions API — OpenAI itself, Google Gemini,
                 OpenRouter, Groq, local Ollama / LM Studio, vLLM, or any custom endpoint.
  - "laya":      the local Laya decision model: files reels (category, type, signals) for free, but
                 writes no summaries — a good fallback when paid engines are unavailable.

Engines live in <data_dir>/settings.json under "engines", "active_engine" and "fallback_engine".
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from .config import saved_overrides, write_overrides

_IN_DOCKER = Path("/.dockerenv").exists()
_LOCALHOST = "http://host.docker.internal" if _IN_DOCKER else "http://localhost"

# Default models are suggestions; use "Fetch models" in the UI to pick from what your key can access.
PRESETS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "label": "Claude (Anthropic)", "type": "anthropic", "base_url": "",
        "model": "claude-opus-5-5", "key_env": "ANTHROPIC_API_KEY", "needs_key": True,
        "key_url": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "label": "OpenAI", "type": "openai", "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini", "key_env": "OPENAI_API_KEY", "needs_key": True,
        "key_url": "https://platform.openai.com/api-keys",
    },
    "gemini": {
        "label": "Google Gemini", "type": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash", "key_env": "GEMINI_API_KEY", "needs_key": True,
        "key_url": "https://aistudio.google.com/apikey",
    },
    "openrouter": {
        "label": "OpenRouter (hundreds of models)", "type": "openai", "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.5-flash", "key_env": "OPENROUTER_API_KEY", "needs_key": True,
        "key_url": "https://openrouter.ai/keys",
    },
    "groq": {
        "label": "Groq", "type": "openai", "base_url": "https://api.groq.com/openai/v1",
        "model": "meta-llama/llama-4-scout-17b-16e-instruct", "key_env": "GROQ_API_KEY", "needs_key": True,
        "key_url": "https://console.groq.com/keys",
    },
    "ollama": {
        "label": "Ollama (local, free)", "type": "openai", "base_url": f"{_LOCALHOST}:11434/v1",
        "model": "qwen2.5vl:7b", "key_env": "", "needs_key": False,
        "key_url": "https://ollama.com/search?c=vision",
    },
    "lmstudio": {
        "label": "LM Studio (local, free)", "type": "openai", "base_url": f"{_LOCALHOST}:1234/v1",
        "model": "", "key_env": "", "needs_key": False, "key_url": "https://lmstudio.ai",
    },
    "laya": {
        "label": "Laya (local decisions, free)", "type": "laya", "base_url": "",
        "model": "auto", "key_env": "", "needs_key": False,
        "key_url": "https://github.com/NandhaKishorM/laya",
    },
    "custom": {
        "label": "Custom OpenAI-compatible", "type": "openai", "base_url": "",
        "model": "", "key_env": "", "needs_key": False, "key_url": "",
    },
}

FIELDS = ("id", "preset", "name", "type", "base_url", "api_key", "model", "effort", "vision", "json_mode")


def _new_id() -> str:
    return "eng_" + secrets.token_hex(4)


def make_engine(preset: str, **overrides: Any) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"Unknown engine type: {preset}")
    p = PRESETS[preset]
    eng = {
        "id": _new_id(), "preset": preset, "name": p["label"].split(" (")[0], "type": p["type"],
        "base_url": p["base_url"], "api_key": "", "model": p["model"], "effort": "medium",
        "vision": True, "json_mode": "auto",
    }
    eng.update({k: v for k, v in overrides.items() if k in FIELDS and k != "id" and v is not None})
    return eng


def _seed() -> tuple[list[dict], str | None]:
    """First run: build engines from the legacy single-Claude settings and any API keys in the env."""
    legacy = saved_overrides()
    engines = [make_engine(
        "anthropic",
        api_key=legacy.get("anthropic_api_key", ""),
        model=legacy.get("model") or os.environ.get("INSTAMCP_MODEL") or PRESETS["anthropic"]["model"],
        effort=legacy.get("effort") or os.environ.get("INSTAMCP_EFFORT") or "medium",
    )]
    for preset in ("openai", "gemini", "openrouter", "groq"):
        if os.environ.get(PRESETS[preset]["key_env"]):
            engines.append(make_engine(preset))
    has_claude = bool(engines[0]["api_key"] or os.environ.get("ANTHROPIC_API_KEY"))
    active = engines[0]["id"] if has_claude or len(engines) == 1 else engines[1]["id"]
    return engines, active


def load() -> dict:
    data = saved_overrides()
    if "engines" not in data:
        engines, active = _seed()
        save(engines, active, None)
        data = saved_overrides()
    engines = data.get("engines", [])
    ids = {e["id"] for e in engines}
    active = data.get("active_engine") if data.get("active_engine") in ids else (engines[0]["id"] if engines else None)
    fallback = data.get("fallback_engine") if data.get("fallback_engine") in ids - {active} else None
    return {"engines": engines, "active": active, "fallback": fallback}


def save(engines: list[dict], active: str | None, fallback: str | None) -> None:
    def mutate(d: dict) -> None:
        d["engines"] = engines
        d["active_engine"] = active
        d["fallback_engine"] = fallback
        for legacy in ("anthropic_api_key", "model", "effort"):
            d.pop(legacy, None)
    write_overrides(mutate)


def get(engine_id: str) -> dict:
    for e in load()["engines"]:
        if e["id"] == engine_id:
            return e
    raise KeyError(f"No such engine: {engine_id}")


def api_key(engine: dict) -> str:
    env = PRESETS.get(engine.get("preset", ""), {}).get("key_env")
    return engine.get("api_key") or (os.environ.get(env, "") if env else "")


def is_ready(engine: dict) -> bool:
    if engine.get("type") == "laya":
        from .decisions import available
        return available()
    needs_key = PRESETS.get(engine.get("preset", ""), {}).get("needs_key", False)
    return bool(engine.get("model")) and (bool(api_key(engine)) or not needs_key) and \
        (engine["type"] == "anthropic" or bool(engine.get("base_url")))


def chain() -> list[dict]:
    """Engines to try, in order: primary, then fallback."""
    cfg = load()
    by_id = {e["id"]: e for e in cfg["engines"]}
    return [by_id[i] for i in (cfg["active"], cfg["fallback"]) if i in by_id]


def public(engine: dict) -> dict:
    key = api_key(engine)
    out = {k: engine.get(k) for k in FIELDS if k != "api_key"}
    out["key_set"] = bool(key)
    out["key_from_env"] = bool(key and not engine.get("api_key"))
    out["key_hint"] = f"{key[:7]}…{key[-4:]}" if len(key) > 14 else ("set" if key else "")
    out["ready"] = is_ready(engine)
    out["label"] = f"{engine.get('name')} · {engine.get('model') or 'no model'}"
    return out


def summary() -> dict:
    cfg = load()
    by_id = {e["id"]: e for e in cfg["engines"]}
    active = by_id.get(cfg["active"])
    fallback = by_id.get(cfg["fallback"])
    return {
        "ai_ready": bool(active and is_ready(active)),
        "active_engine": public(active) if active else None,
        "fallback_engine": public(fallback) if fallback else None,
    }
