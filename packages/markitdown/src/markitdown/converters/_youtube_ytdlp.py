"""Reliable YouTube -> Markdown via yt-dlp.

markitdown's normal path fetches the watch page over `requests` before any
converter runs. On networks whose exit IP is rate-limited by YouTube, that fetch
is redirected to Google's `/sorry` captcha and returns HTTP 429, so the transcript
is never reached. YouTube also gates the video API behind a bot check that requires
the viewer's logged-in cookies.

This module bypasses the page fetch entirely: it drives the `yt-dlp` binary to pull
the video's metadata and auto-captions directly, authenticating with the local
browser's cookies and, when configured, rotating between SOCKS proxy ports to ride
out transient 429s. It returns a `DocumentConverterResult` so `convert_uri` can hand
YouTube URLs straight here.

Configuration (all optional, via environment variables):

- ``MARKITDOWN_YT_PORTS``    space-separated SOCKS proxy ports to try, in order.
                             Empty/unset means "no proxy" (direct connection).
- ``MARKITDOWN_YT_COOKIES``  path to a cookies.txt file. Unset means pull cookies
                             from Chrome (``--cookies-from-browser chrome``).
- ``MARKITDOWN_YT_RETRIES``  passes over the port list before giving up (default 3).
- ``MARKITDOWN_YT_COOLDOWN`` seconds to wait between passes (default 20).

Requires the ``yt-dlp`` binary on PATH.
"""

import glob
import html
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from typing import List, Optional
from urllib.parse import urlparse

from .._base_converter import DocumentConverterResult

YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
)

# Substrings in yt-dlp stderr that indicate a transient / IP- or bot-related block
# worth retrying on a different proxy port or after a cooldown.
_RETRYABLE_MARKERS = (
    "429",
    "too many requests",
    "sign in to confirm",
    "not a bot",
    "/sorry/",
    "confirm you",
)


class YouTubeFetchError(RuntimeError):
    """Raised when a YouTube URL cannot be converted via yt-dlp."""


def is_youtube_url(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "").lower() in YOUTUBE_HOSTS
    except ValueError:
        return False


def _ports() -> List[Optional[str]]:
    raw = os.environ.get("MARKITDOWN_YT_PORTS", "7892 7890").split()
    return [p for p in raw] or [None]  # [None] => single attempt, no proxy


def _port_listening(port: str) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=2):
            return True
    except (OSError, ValueError):
        return False


def _run_ytdlp(url: str, workdir: str, proxy_port: Optional[str]) -> subprocess.CompletedProcess:
    cookies = os.environ.get("MARKITDOWN_YT_COOKIES")
    cmd = ["yt-dlp"]
    if proxy_port:
        cmd += ["--proxy", f"socks5h://127.0.0.1:{proxy_port}"]
    if cookies:
        cmd += ["--cookies", cookies]
    else:
        cmd += ["--cookies-from-browser", "chrome"]
    cmd += [
        # metadata + captions only; tolerate the image-only-formats condition that
        # otherwise aborts format selection when YouTube's JS challenge fails.
        "--ignore-no-formats-error",
        "--no-abort-on-error",
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
        "--sub-langs",
        "en.*,en",
        "--sub-format",
        "json3",
        "--write-info-json",
        "-o",
        os.path.join(workdir, "v.%(ext)s"),
        url,
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


def _is_retryable(stderr: str) -> bool:
    low = stderr.lower()
    return any(m in low for m in _RETRYABLE_MARKERS)


def _first(pattern: str, workdir: str) -> Optional[str]:
    matches = sorted(glob.glob(os.path.join(workdir, pattern)))
    return matches[0] if matches else None


def _transcript_from_json3(path: str) -> str:
    """Flatten yt-dlp json3 captions into de-duplicated plain text.

    Auto-generated captions emit overlapping rolling windows, so consecutive
    identical lines are collapsed.
    """
    data = json.load(open(path, encoding="utf-8"))
    lines: List[str] = []
    prev: Optional[str] = None
    for event in data.get("events", []):
        segs = event.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs)
        text = html.unescape(text).replace("\n", " ").strip()
        if text and text != prev:
            lines.append(text)
            prev = text
    return " ".join(lines)


def _build_markdown(info_path: str, sub_path: Optional[str]) -> DocumentConverterResult:
    info = json.load(open(info_path, encoding="utf-8"))
    title = info.get("title") or "(untitled)"
    out: List[str] = [f"# {title}\n"]

    def row(label: str, value) -> None:
        if value:
            out.append(f"- **{label}:** {value}")

    row("Channel", info.get("uploader") or info.get("channel"))
    row("Uploaded", info.get("upload_date"))
    row("Duration", info.get("duration_string") or info.get("duration"))
    row("Views", info.get("view_count"))
    row("URL", info.get("webpage_url"))

    description = (info.get("description") or "").strip()
    if description:
        out.append("\n## Description\n")
        out.append(description)

    if sub_path:
        try:
            transcript = _transcript_from_json3(sub_path)
        except Exception as exc:  # pragma: no cover - defensive
            transcript = ""
            out.append(f"\n_(transcript parse failed: {exc})_")
        if transcript:
            out.append("\n## Transcript\n")
            out.append(transcript)

    return DocumentConverterResult("\n".join(out), title=title)


def fetch_youtube_markdown(url: str) -> DocumentConverterResult:
    """Convert a YouTube URL to Markdown using yt-dlp, rotating proxy ports.

    Raises YouTubeFetchError with an actionable message on failure.
    """
    if shutil.which("yt-dlp") is None:
        raise YouTubeFetchError(
            "yt-dlp is required to convert YouTube URLs but was not found on PATH. "
            "Install it (e.g. `pipx install yt-dlp` or `brew install yt-dlp`)."
        )

    retries = int(os.environ.get("MARKITDOWN_YT_RETRIES", "3"))
    cooldown = float(os.environ.get("MARKITDOWN_YT_COOLDOWN", "20"))
    ports = _ports()
    last_stderr = ""

    for attempt in range(1, retries + 1):
        blocked_all = True
        for port in ports:
            if port is not None and not _port_listening(port):
                continue  # proxy not up; skip
            workdir = tempfile.mkdtemp(prefix="markitdown-yt-")
            try:
                proc = _run_ytdlp(url, workdir, port)
                info_path = _first("*.info.json", workdir)
                if info_path:
                    sub_path = _first("*.json3", workdir)
                    return _build_markdown(info_path, sub_path)
                last_stderr = proc.stderr or proc.stdout or ""
                if not _is_retryable(last_stderr):
                    # A real, non-transient failure (bad URL, private video, etc.).
                    raise YouTubeFetchError(
                        "yt-dlp could not retrieve this YouTube URL:\n"
                        + last_stderr.strip()
                    )
                blocked_all = blocked_all and True  # this port was blocked; try next
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
        if blocked_all and attempt < retries:
            time.sleep(cooldown)

    raise YouTubeFetchError(
        "YouTube blocked every configured proxy port after "
        f"{retries} attempts (transient rate-limit / bot check). "
        "Try again later, switch VPN exit, or set MARKITDOWN_YT_PORTS. "
        "Last yt-dlp error:\n" + last_stderr.strip()
    )
