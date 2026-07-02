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
  which triggers a macOS "Chrome Safe Storage" keychain prompt on each run.

### Avoiding the keychain prompt (recommended)

Export the cookies once to a file and point `MARKITDOWN_YT_COOKIES` at it; markitdown
then never touches the keychain:

```bash
mkdir -p ~/.config
yt-dlp --cookies-from-browser chrome --cookies ~/.config/yt-cookies.txt \
       --skip-download "https://youtu.be/dQw4w9WgXcQ" >/dev/null 2>&1
chmod 600 ~/.config/yt-cookies.txt          # holds your YouTube session
export MARKITDOWN_YT_COOKIES="$HOME/.config/yt-cookies.txt"   # add to ~/.zshrc
```

The exported cookies eventually expire (YouTube's last months). When conversion starts
failing the bot check again, re-run the export command above to refresh the file.
Alternatively, just click **Always Allow** on the keychain prompt instead of using a
file — simpler, but it can reappear after a Chrome update.

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
