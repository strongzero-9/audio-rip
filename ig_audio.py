"""Link to MP3: paste an Instagram, TikTok or YouTube link, get the audio as MP3.

Setup:  pip install flask yt-dlp   (and install ffmpeg)
Run:    python ig_audio.py

On your iPhone (same Wi-Fi as the computer running this):
  1. Open  http://<computer-IP>:5000  in Safari
  2. Tap Share -> Add to Home Screen

Note: the share sheet ("Save to Files") needs HTTPS. Over plain http the
app falls back to a download link. Host it somewhere with HTTPS for the
full experience.

Use only on content you own or have permission to use.
Optional: set the ACCESS_CODE environment variable to require a code.
Login-required or age-gated posts: export cookies to cookies.txt next to this file.
"""
import hmac
import io
import os
import pathlib
import shutil
import struct
import tempfile
import zlib
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request, send_file
from yt_dlp import YoutubeDL

app = Flask(__name__)

ACCESS_CODE = os.environ.get("ACCESS_CODE", "")

ALLOWED = ("instagram.com", "tiktok.com", "youtube.com", "youtu.be")

MANIFEST = """{
  "name": "Link to MP3",
  "short_name": "Link to MP3",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#111111",
  "theme_color": "#111111",
  "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}]
}"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Link to MP3</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Link to MP3">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#111111">
<style>
  :root { --bg:#ffffff; --fg:#111111; --muted:#6b6b6b; --field:#f2f2f4; --btn:#111111; --btnfg:#ffffff; --err:#b00020; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111111; --fg:#f5f5f5; --muted:#9a9a9a; --field:#1f1f22; --btn:#f5f5f5; --btnfg:#111111; --err:#ff6b81; }
  }
  * { box-sizing: border-box; }
  html, body { margin:0; background:var(--bg); color:var(--fg); }
  body { font-family:-apple-system, system-ui, sans-serif; min-height:100vh;
    padding: calc(env(safe-area-inset-top, 0px) + 56px) 20px calc(env(safe-area-inset-bottom, 0px) + 24px); }
  main { max-width:480px; margin:0 auto; }
  h1 { font-size:28px; margin:0 0 4px; }
  p.sub { color:var(--muted); margin:0 0 24px; }
  input, button { width:100%; font-size:17px; padding:15px; border-radius:12px; border:0; }
  input { background:var(--field); color:var(--fg); }
  button { background:var(--btn); color:var(--btnfg); font-weight:600; margin-top:12px; }
  button:disabled { opacity:.5; }
  .err { color:var(--err); margin-top:14px; }
  #out { margin-top:24px; }
  audio { width:100%; }
  .hint { color:var(--muted); font-size:13px; margin-top:10px; }
</style>
</head>
<body>
<main>
  <h1>Link to MP3</h1>
  <p class="sub">Instagram, TikTok or YouTube</p>
  <form id="f">
    <input id="url" type="url" inputmode="url" autocapitalize="off" autocorrect="off"
           placeholder="Paste a link" required>
    __CODE__
    <button id="go" type="submit">Extract audio</button>
  </form>
  <p class="err" id="msg"></p>
  <div id="out" hidden>
    <audio id="player" controls></audio>
    <button id="save" type="button">Save / Share MP3</button>
    <p class="hint" id="hint"></p>
    <a id="dl" hidden></a>
  </div>
</main>
<script>
const f = document.getElementById('f'), url = document.getElementById('url');
const go = document.getElementById('go'), msg = document.getElementById('msg');
const out = document.getElementById('out'), player = document.getElementById('player');
const save = document.getElementById('save'), dl = document.getElementById('dl');
const hint = document.getElementById('hint');
const codeEl = document.getElementById('code');
if (codeEl) { try { codeEl.value = localStorage.getItem('code') || ''; } catch (_) {} }

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  msg.textContent = '';
  out.hidden = true;
  go.disabled = true;
  go.textContent = 'Working…';
  try {
    if (codeEl) { try { localStorage.setItem('code', codeEl.value); } catch (_) {} }
    const r = await fetch('/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'url=' + encodeURIComponent(url.value.trim()) + '&code=' + encodeURIComponent(codeEl ? codeEl.value : '')
    });
    if (!r.ok) {
      let m = 'Something went wrong.';
      try { m = (await r.json()).error || m; } catch (_) {}
      throw new Error(m);
    }
    const name = r.headers.get('X-Filename') || 'audio.mp3';
    const blob = await r.blob();
    const file = new File([blob], name, { type: 'audio/mpeg' });
    const href = URL.createObjectURL(blob);
    player.src = href;
    dl.href = href;
    dl.download = name;
    const canShare = !!(navigator.canShare && navigator.canShare({ files: [file] }));
    hint.textContent = canShare ? '' : 'Tip: if saving does nothing, press and hold the player or open this page in Safari.';
    save.onclick = async () => {
      if (canShare) {
        try { await navigator.share({ files: [file] }); } catch (_) {}
      } else {
        dl.click();
      }
    };
    out.hidden = false;
  } catch (err) {
    msg.textContent = err.message;
  } finally {
    go.disabled = false;
    go.textContent = 'Extract audio';
  }
});
</script>
</body>
</html>
"""


def make_icon(size=512):
    """Dependency-free PNG: dark square with white sound-wave bars."""
    bg, fg = (17, 17, 17), (255, 255, 255)
    bars = [0.25, 0.5, 0.8, 0.5, 0.35, 0.65, 0.3]
    n = len(bars)
    margin = size * 0.2
    span = size - 2 * margin
    barw = span / (n * 2 - 1)
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            c = bg
            rel = (x - margin) / barw
            if 0 <= rel < 2 * n - 1 and int(rel) % 2 == 0:
                h = bars[int(rel) // 2] * span
                if abs(y - size / 2) <= h / 2:
                    c = fg
            raw.extend(c)

    def chunk(t, d):
        body = t + d
        return struct.pack(">I", len(d)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))


ICON = make_icon()


def valid(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and any(
        host == d or host.endswith("." + d) for d in ALLOWED)


@app.route("/")
def index():
    field = ('<input id="code" type="password" placeholder="Access code" required '
             'style="margin-top:12px">') if ACCESS_CODE else ""
    return PAGE.replace("__CODE__", field)


@app.route("/manifest.webmanifest")
def manifest():
    return Response(MANIFEST, mimetype="application/manifest+json")


@app.route("/icon.png")
def icon():
    return Response(ICON, mimetype="image/png")


@app.route("/extract", methods=["POST"])
def extract():
    if ACCESS_CODE and not hmac.compare_digest(
            request.form.get("code", ""), ACCESS_CODE):
        return jsonify(error="Wrong access code."), 403
    url = request.form.get("url", "").strip()
    if not valid(url):
        return jsonify(error="Use an Instagram, TikTok or YouTube link."), 400

    tmp = tempfile.mkdtemp()
    try:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{tmp}/%(id)s.%(ext)s",
            "quiet": True,
            "noplaylist": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
        if pathlib.Path("cookies.txt").exists():
            opts["cookiefile"] = "cookies.txt"
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
        f = next(pathlib.Path(tmp).glob("*.mp3"))
        resp = send_file(io.BytesIO(f.read_bytes()), as_attachment=True,
                         download_name=f.name, mimetype="audio/mpeg")
        resp.headers["X-Filename"] = f.name
        return resp
    except Exception as e:
        return jsonify(error=f"Failed: {str(e)[:200]}"), 500
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
