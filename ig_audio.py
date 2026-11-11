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
  "background_color": "#0a0a0a",
  "theme_color": "#0a0a0a",
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
<meta name="theme-color" content="#0a0a0a">
<style>
  :root { color-scheme: dark; --amber:#ffb000; --glow:rgba(255,176,0,.6); --red:#ff5a36; }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  html, body { margin:0; background:#0a0a0a; color:var(--amber); }
  body {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    min-height:100vh;
    padding: calc(env(safe-area-inset-top, 0px) + 28px) 14px calc(env(safe-area-inset-bottom, 0px) + 24px);
    background: radial-gradient(120% 60% at 50% 0%, #1c1c1f 0%, #0a0a0a 70%);
  }
  .unit {
    max-width:480px; margin:0 auto; padding:14px; border-radius:18px;
    background:linear-gradient(#2b2b2f, #17171a); border:1px solid #3a3a40;
    box-shadow:0 1px 0 #55555c inset, 0 20px 40px rgba(0,0,0,.6);
  }
  .top { display:flex; justify-content:space-between; font-size:11px; letter-spacing:.3em; color:#b8b8c0; margin:2px 4px 12px; }
  .brand { font-weight:700; }
  .face { display:flex; align-items:center; gap:10px; }
  .knob {
    flex:0 0 40px; height:40px; border-radius:50%; position:relative; border:2px solid #111;
    background:conic-gradient(#6d6d75, #2a2a2e, #8a8a92, #2a2a2e, #6d6d75);
    box-shadow:0 2px 4px rgba(0,0,0,.7), inset 0 1px 1px rgba(255,255,255,.3);
  }
  .knob::after { content:""; position:absolute; left:50%; top:4px; width:2px; height:10px; margin-left:-1px; background:var(--amber); border-radius:1px; }
  .display {
    flex:1; min-width:0; padding:10px 12px; background:#050403; border:2px solid #000; border-radius:8px;
    box-shadow:inset 0 0 14px rgba(255,176,0,.12), 0 0 0 1px #3a3a40;
  }
  .small { display:flex; justify-content:space-between; font-size:10px; letter-spacing:.2em; opacity:.7; }
  .big { font-size:22px; letter-spacing:.14em; margin:6px 0 8px; min-height:28px; text-transform:uppercase; text-shadow:0 0 8px var(--glow); }
  .big.err { color:var(--red); text-shadow:0 0 8px rgba(255,90,54,.7); }
  .blink::after { content:"_"; animation:b 1s steps(1) infinite; }
  @keyframes b { 50% { opacity:0; } }
  .field {
    display:block; width:100%; margin:0; padding:10px 0 4px; border:0; border-top:1px dashed rgba(255,176,0,.35); border-radius:0;
    background:transparent; color:var(--amber); font:inherit; font-size:16px; outline:0; caret-color:var(--amber);
    text-shadow:0 0 6px var(--glow);
  }
  .field::placeholder { color:rgba(255,176,0,.4); text-transform:uppercase; letter-spacing:.1em; }
  .msg { font-size:11px; color:var(--red); margin:6px 0 0; word-break:break-word; letter-spacing:.05em; }
  .buttons { display:grid; grid-template-columns:2fr 1fr; gap:10px; margin-top:14px; }
  .btn {
    width:100%; padding:16px 8px; font:inherit; font-size:13px; font-weight:700; letter-spacing:.2em; color:var(--amber);
    text-shadow:0 0 6px var(--glow); background:linear-gradient(#3a3a40, #222226); border:1px solid #000; border-radius:10px;
    box-shadow:0 1px 0 rgba(255,255,255,.2) inset, 0 3px 0 #0a0a0a, 0 4px 6px rgba(0,0,0,.6);
  }
  .btn:active { transform:translateY(2px); box-shadow:0 1px 0 rgba(255,255,255,.15) inset, 0 1px 0 #0a0a0a; }
  .btn:disabled { opacity:.45; }
  #out { margin-top:16px; padding:12px; background:#101012; border:1px solid #2c2c31; border-radius:10px; }
  audio { width:100%; color-scheme:dark; }
  #save { margin-top:10px; }
  .hint { color:#9a9aa2; font-size:11px; margin:10px 0 0; }
</style>
</head>
<body>
<main class="unit">
  <div class="top"><span class="brand">LINK·MP3</span><span>DIGITAL STEREO</span></div>
  <div class="face">
    <div class="knob"></div>
    <div class="display">
      <div class="small"><span>SRC WEB</span><span>MP3 192K</span></div>
      <div id="status" class="big">Ready</div>
      <form id="f">
        <input id="url" class="field" type="url" inputmode="url" autocapitalize="off" autocorrect="off"
               placeholder="Paste IG / TikTok / YT link" required>
        __CODE__
      </form>
      <p class="msg" id="msg"></p>
    </div>
    <div class="knob"></div>
  </div>
  <div class="buttons">
    <button id="go" class="btn" type="submit" form="f">EXTRACT</button>
    <button id="clear" class="btn" type="button">CLEAR</button>
  </div>
  <div id="out" hidden>
    <audio id="player" controls></audio>
    <button id="save" class="btn" type="button">SAVE / SHARE MP3</button>
    <p class="hint" id="hint"></p>
    <a id="dl" hidden></a>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const f = $('f'), url = $('url'), go = $('go'), clr = $('clear'), status = $('status'), msg = $('msg');
const out = $('out'), player = $('player'), save = $('save'), dl = $('dl'), hint = $('hint'), codeEl = $('code');
let blobUrl = null;

if (codeEl) { try { codeEl.value = localStorage.getItem('code') || ''; } catch (_) {} }

function setStatus(text, cls) {
  status.textContent = text;
  status.className = 'big' + (cls ? ' ' + cls : '');
}

function dropAudio() {
  player.pause();
  player.removeAttribute('src');
  player.load();
  if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
  out.hidden = true;
}

clr.addEventListener('click', () => {
  dropAudio();
  url.value = '';
  msg.textContent = '';
  setStatus('Ready');
  url.focus();
});

f.addEventListener('submit', async (e) => {
  e.preventDefault();
  msg.textContent = '';
  dropAudio();
  go.disabled = true;
  setStatus('Working', 'blink');
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
    blobUrl = URL.createObjectURL(blob);
    player.src = blobUrl;
    dl.href = blobUrl;
    dl.download = name;
    const canShare = !!(navigator.canShare && navigator.canShare({ files: [file] }));
    hint.textContent = canShare ? '' : 'If saving does nothing, press and hold the player or open this page in Safari.';
    save.onclick = async () => {
      if (canShare) {
        try { await navigator.share({ files: [file] }); } catch (_) {}
      } else {
        dl.click();
      }
    };
    out.hidden = false;
    setStatus('Done');
  } catch (err) {
    setStatus('Error', 'err');
    msg.textContent = err.message;
  } finally {
    go.disabled = false;
  }
});
</script>
</body>
</html>
"""


def make_icon(size=512):
    """Dependency-free PNG: dark square with white sound-wave bars."""
    bg, fg = (10, 10, 10), (255, 176, 0)
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
    field = ('<input id="code" class="field" type="password" placeholder="Access code" '
             'required>') if ACCESS_CODE else ""
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
