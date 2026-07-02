# YouTube support (yt-dlp path)

When you pass a YouTube URL to `markitdown`, it does **not** fetch the watch page over
HTTP. YouTube's watch page is bot-gated and often rate-limited (the request gets
redirected to Google's `/sorry` captcha → HTTP 429), so a plain fetch fails before any
transcript can be read.

Instead, markitdown drives the [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) binary to
pull the video's **metadata + auto-generated captions** directly, and renders them to
Markdown (title, channel, upload date, duration, views, description, transcript).

```bash
markitdown "https://youtu.be/VIDEOID"          # -> markdown on stdout
markitdown "https://youtu.be/VIDEOID" -o out.md
```

## Prerequisites

- **`yt-dlp` on PATH.** Install with `pipx install yt-dlp` or `brew install yt-dlp`.
- **Browser login.** YouTube requires a signed-in session to pass its bot check.
  By default markitdown reads cookies from Chrome (`--cookies-from-browser chrome`),
  which may trigger a one-time OS keychain prompt. To use an exported cookie file
  instead, set `MARKITDOWN_YT_COOKIES` (see below).

## Configuration (environment variables)

All optional.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MARKITDOWN_YT_PORTS` | `7892 7890` | Space-separated SOCKS proxy ports to try, in order. Ports that aren't listening are skipped. Set to empty for a direct connection. |
| `MARKITDOWN_YT_COOKIES` | *(unset)* | Path to a `cookies.txt` file. Unset → pull cookies from Chrome. |
| `MARKITDOWN_YT_RETRIES` | `3` | Passes over the port list before giving up. |
| `MARKITDOWN_YT_COOLDOWN` | `20` | Seconds to wait between passes (rides out transient 429s). |

Rotating proxy ports lets markitdown fall back to a second VPN exit when the first is
being rate-limited. On a normal (unblocked) network, set `MARKITDOWN_YT_PORTS=` to skip
the proxy entirely.

## Notes

- Only subtitles and metadata are retrieved (no video/audio download), which is all the
  Markdown output needs.
- Raw YouTube **HTML** piped in as a file (not a URL) still goes through the legacy
  HTML-scraping converter; only URL conversion uses the yt-dlp path.
