"""Runtime configuration: environment variables, overridden by settings saved from the web UI.

AI engine configuration (providers, keys, models) lives in engines.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Callable


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def data_dir() -> Path:
    d = Path(_env("INSTAMCP_DATA_DIR") or Path.home() / ".instamcp").expanduser()
    for sub in ("", "media", "thumbs"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    whisper_model: str
    num_frames: int
    cookies_from_browser: str
    cookies_file: str
    keep_media: bool
    verify_links: bool
    auto_signals: bool

    @property
    def db_path(self) -> Path:
        return self.data_dir / "instamcp.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"


# Keys the web UI may change; stored in <data_dir>/settings.json.
EDITABLE = ("whisper_model", "num_frames", "verify_links", "auto_signals")


def settings_file() -> Path:
    return data_dir() / "settings.json"


def saved_overrides() -> dict:
    try:
        return json.loads(settings_file().read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_overrides(mutate: Callable[[dict], None]) -> None:
    current = saved_overrides()
    mutate(current)
    path = settings_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2), "utf-8")
    tmp.chmod(0o600)  # holds API keys
    tmp.replace(path)


def save_overrides(updates: dict) -> None:
    def mutate(current: dict) -> None:
        for k, v in updates.items():
            if k not in EDITABLE:
                continue
            if v in (None, ""):
                current.pop(k, None)
            else:
                current[k] = v
    write_overrides(mutate)


def cookies_path() -> Path:
    """Cookies uploaded through the UI (Netscape cookies.txt format)."""
    return data_dir() / "cookies.txt"


def write_session_cookie(sessionid: str) -> None:
    """Build a cookies.txt from a pasted Instagram `sessionid` cookie value."""
    sessionid = sessionid.strip().strip('"')
    lines = ["# Netscape HTTP Cookie File",
             f".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\t{sessionid}"]
    path = cookies_path()
    path.write_text("\n".join(lines) + "\n", "utf-8")
    path.chmod(0o600)


def load_settings() -> Settings:
    d = data_dir()
    over = saved_overrides()
    uploaded_cookies = cookies_path()
    return Settings(
        data_dir=d,
        whisper_model=over.get("whisper_model") or _env("INSTAMCP_WHISPER_MODEL", "small"),
        num_frames=int(over.get("num_frames") or _env("INSTAMCP_FRAMES", "8")),
        cookies_from_browser=_env("INSTAMCP_COOKIES_FROM_BROWSER"),
        cookies_file=_env("INSTAMCP_COOKIES_FILE") or (str(uploaded_cookies) if uploaded_cookies.exists() else ""),
        keep_media=_env("INSTAMCP_KEEP_MEDIA", "0") == "1",
        verify_links=bool(over.get("verify_links", _env("INSTAMCP_VERIFY_LINKS", "1") == "1")),
        auto_signals=bool(over.get("auto_signals", _env("INSTAMCP_AUTO_SIGNALS", "1") == "1")),
    )


def public_settings(s: Settings) -> dict:
    """Settings safe to show in the UI."""
    out = {f.name: getattr(s, f.name) for f in fields(s) if f.name != "data_dir"}
    out["data_dir"] = str(s.data_dir)
    out["instagram_login"] = bool(s.cookies_file or s.cookies_from_browser)
    return out
