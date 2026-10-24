"""Download a reel and turn it into things a model can read: metadata, transcript, keyframes."""

from __future__ import annotations

import base64
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .config import Settings


@dataclass
class MediaBundle:
    caption: str | None = None
    uploader: str | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    video_path: Path | None = None
    transcript: str | None = None
    language: str | None = None
    frames: list[bytes] = field(default_factory=list)  # JPEG bytes


def fetch(url: str, workdir: Path, settings: Settings) -> MediaBundle:
    """Download the reel with yt-dlp and collect its metadata."""
    import yt_dlp

    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(workdir / "video.%(ext)s"),
        "format": "best[ext=mp4]/bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if settings.cookies_file:
        opts["cookiefile"] = settings.cookies_file
    elif settings.cookies_from_browser:
        opts["cookiesfrombrowser"] = (settings.cookies_from_browser,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info.get("_type") == "playlist" and info.get("entries"):  # carousel posts
        info = next((e for e in info["entries"] if e), info)

    video = next((p for p in workdir.glob("video.*") if p.suffix in (".mp4", ".mkv", ".webm", ".mov")), None)
    return MediaBundle(
        caption=info.get("description") or info.get("title"),
        uploader=info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        duration=info.get("duration"),
        thumbnail_url=info.get("thumbnail"),
        video_path=video,
    )


def extract_frames(video: Path, count: int, duration: float | None) -> list[bytes]:
    """Grab `count` evenly spaced keyframes as JPEGs (max 768px wide)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed (brew install ffmpeg)")
    duration = duration or _probe_duration(video) or 30.0
    frames: list[bytes] = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", "scale='min(768,iw)':-2", "-q:v", "4", "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
            capture_output=True, timeout=60,
        )
        if out.returncode == 0 and out.stdout:
            frames.append(out.stdout)
    return frames


def _probe_duration(video: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


@lru_cache(maxsize=1)
def _whisper(model_name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="auto", compute_type="int8")


def transcribe(video: Path, model_name: str) -> tuple[str | None, str | None]:
    """Speech-to-text with faster-whisper. Returns (transcript, language)."""
    try:
        segments, info = _whisper(model_name).transcribe(str(video), vad_filter=True, beam_size=5)
        text = " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:  # silent reels, no audio stream, etc.
        if "audio" in str(e).lower() or "stream" in str(e).lower():
            return None, None
        raise
    return (text or None), getattr(info, "language", None)


def prepare(url: str, workdir: Path, settings: Settings) -> MediaBundle:
    bundle = fetch(url, workdir, settings)
    if bundle.video_path:
        bundle.frames = extract_frames(bundle.video_path, settings.num_frames, bundle.duration)
        bundle.transcript, bundle.language = transcribe(bundle.video_path, settings.whisper_model)
    return bundle


def b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("ascii")
