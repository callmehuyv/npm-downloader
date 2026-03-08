#!/usr/bin/env python3
"""
=============================================================
  NPM Package Downloader
  Target: 250,000 downloads over 7 days
  Works on: Windows / macOS / Linux (Python 3.6+)
  No dependencies — uses only Python standard library
=============================================================

HOW TO RUN:
  macOS/Linux:  python3 npm_downloader.py
  Windows:      python npm_downloader.py

  Then open http://localhost:8899 in your browser
  and click START.
=============================================================
"""

import os
import sys
import json
import time
import signal
import threading
import urllib.request
import urllib.error
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG — change these if needed
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PACKAGE = "chrome-local-mcp"
TARGET = 250_000
DAYS = 7
WORKERS = 5
PORT = 8899
REGISTRY = "https://registry.npmjs.org"
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# ── Shared state ────────────────────────────────────────────
lock = threading.Lock()
app = {
    "running": False,
    "count": 0,
    "fail_count": 0,
    "start_time": None,
    "tarball_url": None,
}
stop_event = threading.Event()


# ── HTML Dashboard ──────────────────────────────────────────
def build_html():
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NPM Downloader</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#0f172a; color:#e2e8f0; display:flex; justify-content:center;
         align-items:center; min-height:100vh; }}
  .c {{ background:#1e293b; border-radius:16px; padding:36px 40px; width:540px;
        box-shadow:0 25px 50px rgba(0,0,0,.4); }}
  h1 {{ text-align:center; font-size:22px; margin-bottom:2px; }}
  .pkg {{ color:#818cf8; }}
  .sub {{ text-align:center; color:#94a3b8; font-size:13px; margin-bottom:28px; }}
  .bar-bg {{ background:#334155; border-radius:12px; height:26px; overflow:hidden; margin-bottom:6px; }}
  .bar {{ height:100%; background:linear-gradient(90deg,#3b82f6,#8b5cf6); border-radius:12px;
          transition:width .6s ease; width:0%; min-width:0; }}
  .pct {{ text-align:center; font-size:32px; font-weight:700; color:#a5b4fc; margin-bottom:22px; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:24px; }}
  .card {{ background:#334155; border-radius:10px; padding:13px 16px; }}
  .lbl {{ font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:1.2px; }}
  .val {{ font-size:17px; font-weight:600; margin-top:3px; white-space:nowrap; }}
  .btns {{ display:flex; gap:10px; justify-content:center; }}
  .btns button {{ padding:11px 30px; border:none; border-radius:10px; font-size:14px;
                  font-weight:600; cursor:pointer; transition:all .15s; }}
  .btns button:hover {{ transform:translateY(-1px); filter:brightness(1.1); }}
  .btns button:disabled {{ opacity:.35; cursor:not-allowed; transform:none; filter:none; }}
  .go {{ background:#22c55e; color:#fff; }}
  .no {{ background:#ef4444; color:#fff; }}
  .re {{ background:#475569; color:#e2e8f0; }}
  .st {{ text-align:center; color:#64748b; font-size:12px; margin-top:16px; }}
  .foot {{ text-align:center; color:#475569; font-size:11px; margin-top:18px; }}
</style>
</head>
<body>
<div class="c">
  <h1>NPM Downloader &mdash; <span class="pkg">{PACKAGE}</span></h1>
  <div class="sub">Target: {TARGET:,} downloads in {DAYS} days &middot; {WORKERS} workers</div>

  <div class="bar-bg"><div class="bar" id="bar"></div></div>
  <div class="pct" id="pct">0.00%</div>

  <div class="grid">
    <div class="card"><div class="lbl">Downloads</div><div class="val" id="dl">0 / {TARGET:,}</div></div>
    <div class="card"><div class="lbl">Rate</div><div class="val" id="rate">&mdash;</div></div>
    <div class="card"><div class="lbl">Failed</div><div class="val" id="fail">0</div></div>
    <div class="card"><div class="lbl">Elapsed</div><div class="val" id="elap">&mdash;</div></div>
    <div class="card"><div class="lbl">ETA</div><div class="val" id="eta">&mdash;</div></div>
    <div class="card"><div class="lbl">Deadline</div><div class="val" id="dead">&mdash;</div></div>
  </div>

  <div class="btns">
    <button class="go" id="goB" onclick="api('start')">&#9654; Start</button>
    <button class="no" id="noB" onclick="api('stop')" disabled>&#9632; Stop</button>
    <button class="re" id="reB" onclick="api('reset')">&#8634; Reset</button>
  </div>
  <div class="st" id="st">Ready &mdash; click Start</div>
  <div class="foot">Share this file with friends &middot; Python 3.6+ &middot; No install needed</div>
</div>

<script>
const T={TARGET}, D={DAYS};
const fmt=n=>n.toLocaleString();
const hms=s=>{{s=Math.floor(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;
  return[h,m,x].map(v=>String(v).padStart(2,'0')).join(':')}};

function api(a){{ fetch('/api/'+a,{{method:'POST'}}).then(r=>r.json()).then(upd) }}
function upd(d){{
  const p=d.count/T*100;
  document.getElementById('bar').style.width=p+'%';
  document.getElementById('pct').textContent=p.toFixed(2)+'%';
  document.getElementById('dl').textContent=fmt(d.count)+' / '+fmt(T);
  document.getElementById('fail').textContent=fmt(d.fail_count);
  const goB=document.getElementById('goB'),noB=document.getElementById('noB'),reB=document.getElementById('reB');
  goB.disabled=d.running; noB.disabled=!d.running; reB.disabled=d.running;
  if(d.start_time){{
    const el=d.now-d.start_time;
    document.getElementById('elap').textContent=hms(el);
    const r=el>0?d.count/el:0;
    document.getElementById('rate').textContent=r.toFixed(1)+'/s ('+fmt(Math.round(r*3600))+'/hr)';
    const rem=T-d.count;
    document.getElementById('eta').textContent=r>0?hms(rem/r):'—';
    const dl=new Date(d.start_time*1000+D*86400000);
    document.getElementById('dead').textContent=dl.toLocaleDateString()+' '+dl.toLocaleTimeString([],{{hour:'2-digit',minute:'2-digit'}});
  }}
  document.getElementById('st').textContent=d.running?'Downloading...':d.count>=T?'Target reached!':'Paused — click Start to resume';
}}
setInterval(()=>fetch('/api/status').then(r=>r.json()).then(upd),1000);
fetch('/api/status').then(r=>r.json()).then(upd);
</script>
</body>
</html>"""

HTML_BYTES = None  # built lazily


# ── State persistence ───────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                s = json.load(f)
            if s.get("package") == PACKAGE:
                app["count"] = s.get("count", 0)
                app["start_time"] = s.get("start_time")
        except Exception:
            pass

def save_state():
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"package": PACKAGE, "count": app["count"],
                        "start_time": app["start_time"]}, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


# ── Download engine ─────────────────────────────────────────
def get_tarball_url():
    url = f"{REGISTRY}/{PACKAGE}/latest"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data["dist"]["tarball"]

def download_once(tarball_url):
    try:
        req = urllib.request.Request(tarball_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            while resp.read(65536):
                pass
        return True
    except Exception:
        return False

def worker():
    end_time = app["start_time"] + (DAYS * 86400)
    tarball_url = app["tarball_url"]
    last_save = time.time()

    while not stop_event.is_set():
        ok = download_once(tarball_url)
        with lock:
            if ok:
                app["count"] += 1
            else:
                app["fail_count"] += 1
            current = app["count"]
            now = time.time()
            if now - last_save >= 30:
                save_state()
                last_save = now

        if current >= TARGET:
            stop_event.set()
            with lock:
                app["running"] = False
            save_state()
            break

        # Pace evenly across the week
        now2 = time.time()
        secs_left = max(end_time - now2, 1)
        left = max(TARGET - current, 1)
        ideal_delay = secs_left / left * WORKERS
        sleep_time = max(0.1, min(ideal_delay, 60))
        stop_event.wait(sleep_time)


def start_download():
    if app["running"]:
        return
    if not app["tarball_url"]:
        app["tarball_url"] = get_tarball_url()
    if app["start_time"] is None:
        app["start_time"] = time.time()
    app["running"] = True
    stop_event.clear()
    save_state()
    for _ in range(WORKERS):
        threading.Thread(target=worker, daemon=True).start()

def stop_download():
    stop_event.set()
    app["running"] = False
    save_state()

def reset_download():
    if app["running"]:
        return
    app["count"] = 0
    app["fail_count"] = 0
    app["start_time"] = None
    app["tarball_url"] = None
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


# ── HTTP handler ────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        global HTML_BYTES
        if self.path in ("/", "/index.html"):
            if HTML_BYTES is None:
                HTML_BYTES = build_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_BYTES)
        elif self.path == "/api/status":
            self._json()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/start":
            try:
                start_download()
            except Exception as e:
                self._json({"error": str(e)})
                return
        elif self.path == "/api/stop":
            stop_download()
        elif self.path == "/api/reset":
            reset_download()
        self._json()

    def _json(self, extra=None):
        with lock:
            d = {"running": app["running"], "count": app["count"],
                 "fail_count": app["fail_count"], "start_time": app["start_time"],
                 "now": time.time()}
        if extra:
            d.update(extra)
        body = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Main ────────────────────────────────────────────────────
def main():
    load_state()
    resumed = app["count"] > 0
    url = f"http://localhost:{PORT}"

    print("=" * 55)
    print(f"  NPM Downloader — {PACKAGE}")
    print(f"  Target: {TARGET:,} downloads in {DAYS} days")
    print(f"  Dashboard: {url}")
    if resumed:
        print(f"  Resumed: {app['count']:,} downloads from previous run")
    print("=" * 55)
    print("  Open the URL above in your browser and click Start.")
    print("  Press Ctrl+C to quit (progress is auto-saved).\n")

    # Open browser
    try:
        webbrowser.open(url)
    except Exception:
        pass

    server = HTTPServer(("0.0.0.0", PORT), Handler)

    # Handle Ctrl+C gracefully on all platforms
    def shutdown(sig, frame):
        print("\nShutting down...")
        stop_download()
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except Exception:
        pass
    finally:
        stop_download()
        print(f"Progress saved: {app['count']:,} downloads.")


if __name__ == "__main__":
    main()
