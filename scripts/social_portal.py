#!/usr/bin/env python3
"""PYRESEC Social Deck — local desktop portal for social-card approvals.

Custom popup window (pywebview, falls back to browser) styled like the
PYRESEC website: dark glass, brand red, same fonts. localhost-only API.
"""
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
os.chdir(ROOT)

# pythonw (GUI mode) has sys.stdout/stderr = None — uvicorn's startup logging
# writes to stderr and hard-kills the process without a traceback. Redirect
# both to the portal log so a detached GUI launch survives.
if sys.stdout is None:
    _gui_log = open(ROOT / "scripts" / ".social_portal.log", "a",
                    encoding="utf-8", buffering=1)
    sys.stdout = _gui_log
    sys.stderr = _gui_log

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import social_pipeline
import social_scanner

app = FastAPI(title="PYRESEC Social Deck")
_lock = threading.Lock()
HEARTBEAT = Path("scripts/.social_scanner.heartbeat")

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>PYRESEC — Social Deck</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');
:root {
  --base-950:#050505; --base-900:#0a0a0a; --base-800:#121212;
  --brand-red:#dc2626; --brand-red-glow:rgba(220,38,38,.15); --brand-crimson:#991b1b;
  --glass-high:rgba(255,255,255,.02); --glass-border:1px solid rgba(255,255,255,.06);
  --font-main:"Instrument Sans",system-ui,sans-serif;
  --font-mono:"JetBrains Mono",monospace;
  --text-primary:#fff; --text-secondary:rgba(255,255,255,.6); --text-muted:rgba(255,255,255,.3);
  --ok:#22c55e; --warn:#d97706;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--font-main);background:var(--base-950);color:var(--text-primary);
  min-height:100vh;overflow-x:hidden;
  background-image:radial-gradient(at 0% 0%,rgba(220,38,38,.08) 0,transparent 50%),
  radial-gradient(at 100% 100%,rgba(153,27,27,.06) 0,transparent 50%);}
.noise{position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.03;mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");}
.orb{position:fixed;border-radius:50%;pointer-events:none;z-index:0}
.orb-red{width:60vw;height:60vw;top:-20%;left:-15%;background:radial-gradient(circle,rgba(220,38,38,.12) 0%,rgba(220,38,38,.03) 40%,transparent 70%)}
.wrap{position:relative;z-index:2;max-width:1280px;margin:0 auto;padding:1.5rem 2rem 3rem}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;flex-wrap:wrap;gap:.75rem}
.brand{display:flex;align-items:center;gap:.9rem}
.logo{height:52px;width:auto;border-radius:10px;
  filter:drop-shadow(0 0 7px rgba(220,38,38,.85)) drop-shadow(0 0 18px rgba(220,38,38,.4));
  animation:logoGlow 3.2s ease-in-out infinite}
@keyframes logoGlow{
  0%,100%{filter:drop-shadow(0 0 7px rgba(220,38,38,.85)) drop-shadow(0 0 18px rgba(220,38,38,.4))}
  50%{filter:drop-shadow(0 0 12px rgba(220,38,38,1)) drop-shadow(0 0 28px rgba(220,38,38,.65))}
}
h1{font-size:1.25rem;font-weight:700;letter-spacing:-.02em}
h1 span{color:var(--brand-red)}
.sub{font-family:var(--font-mono);font-size:.68rem;color:var(--text-muted);letter-spacing:.18em;text-transform:uppercase}
.pills{display:flex;gap:.5rem;flex-wrap:wrap}
.pill{font-family:var(--font-mono);font-size:.68rem;padding:.4rem .7rem;border-radius:99px;
  border:var(--glass-border);background:var(--glass-high);color:var(--text-secondary);display:flex;align-items:center;gap:.4rem}
.dot{width:7px;height:7px;border-radius:50%;background:var(--text-muted)}
.dot.ok{background:var(--ok);box-shadow:0 0 8px rgba(34,197,94,.6)}
.dot.bad{background:var(--brand-red);box-shadow:0 0 8px rgba(220,38,38,.6)}
.grid{display:grid;grid-template-columns:340px 1fr;gap:1.25rem;align-items:start}
@media(max-width:960px){.grid{grid-template-columns:1fr}}
.card{background:rgba(18,18,18,.72);backdrop-filter:blur(24px) saturate(180%);border:var(--glass-border);
  border-radius:16px;padding:1.25rem}
.card h2{font-size:.78rem;font-family:var(--font-mono);color:var(--text-muted);letter-spacing:.16em;
  text-transform:uppercase;margin-bottom:1rem}
.q-item{border:var(--glass-border);background:var(--glass-high);border-radius:12px;padding:.85rem 1rem;
  margin-bottom:.6rem;cursor:pointer;transition:.15s}
.q-item:hover{border-color:rgba(220,38,38,.4);background:rgba(220,38,38,.05)}
.q-item.active{border-color:var(--brand-red);background:rgba(220,38,38,.08)}
.q-item .row{display:flex;justify-content:space-between;align-items:center;gap:.5rem}
.q-item .slug{font-family:var(--font-mono);font-size:.78rem;font-weight:500}
.q-item .meta{font-size:.7rem;color:var(--text-muted);margin-top:.3rem}
.badge{font-family:var(--font-mono);font-size:.62rem;padding:.2rem .5rem;border-radius:6px;letter-spacing:.06em}
.badge.HIGH{background:rgba(220,38,38,.15);color:#f87171;border:1px solid rgba(220,38,38,.35)}
.badge.MEDIUM{background:rgba(217,119,6,.12);color:#fbbf24;border:1px solid rgba(217,119,6,.3)}
.badge.LOW{background:rgba(34,197,94,.1);color:#4ade80;border:1px solid rgba(34,197,94,.3)}
.badge.pending{background:rgba(255,255,255,.06);color:var(--text-secondary)}
.badge.posted{background:rgba(34,197,94,.12);color:#4ade80}
.badge.error{background:rgba(220,38,38,.15);color:#f87171}
.badge.rejected{background:rgba(255,255,255,.04);color:var(--text-muted)}
.empty{text-align:center;padding:3rem 1rem;color:var(--text-muted)}
.empty .big{font-family:var(--font-mono);font-size:1rem;color:var(--text-secondary);margin-bottom:.6rem;letter-spacing:.2em}
.empty code{font-family:var(--font-mono);font-size:.7rem;background:rgba(255,255,255,.04);
  padding:.35rem .6rem;border-radius:6px;color:#f87171;display:inline-block;margin-top:.8rem}
table{width:100%;border-collapse:collapse;font-size:.8rem}
th{font-family:var(--font-mono);font-size:.62rem;color:var(--text-muted);text-transform:uppercase;
  letter-spacing:.12em;text-align:left;padding:.4rem .6rem;border-bottom:var(--glass-border)}
td{padding:.55rem .6rem;border-bottom:1px solid rgba(255,255,255,.04)}
td .mono{font-family:var(--font-mono);font-size:.75rem}
.mode-auto{color:var(--ok);font-family:var(--font-mono);font-size:.68rem}
.mode-copy{color:var(--warn);font-family:var(--font-mono);font-size:.68rem}
.section-label{font-family:var(--font-mono);font-size:.65rem;color:var(--text-muted);letter-spacing:.16em;
  text-transform:uppercase;margin:1.25rem 0 .5rem;display:flex;justify-content:space-between}
.section-label.x{color:#3b82f6}
.section-label.fc{color:#a855f7}
.section-label.li{color:#eab308}
.tweet{border:var(--glass-border);background:var(--glass-high);border-radius:12px;padding:.9rem 1rem;margin-bottom:.55rem}
.tweet .head{display:flex;justify-content:space-between;align-items:center;margin-bottom:.5rem}
.tweet .num{font-family:var(--font-mono);font-size:.68rem;color:var(--brand-red)}
.count{font-family:var(--font-mono);font-size:.65rem;color:var(--text-muted)}
.count.over{color:#f87171}
.tweet pre,.cast pre,.li pre{white-space:pre-wrap;word-break:break-word;font-family:var(--font-main);
  font-size:.85rem;line-height:1.55;color:rgba(255,255,255,.85)}
.btns{display:flex;gap:.5rem;margin-top:.6rem;justify-content:flex-end}
button{font-family:var(--font-mono);font-size:.68rem;letter-spacing:.06em;padding:.42rem .85rem;
  border-radius:8px;border:var(--glass-border);background:var(--glass-high);color:var(--text-secondary);
  cursor:pointer;transition:.15s}
button:hover{border-color:rgba(255,255,255,.2);color:#fff}
.btn-approve{background:var(--brand-red);border-color:var(--brand-red);color:#fff;font-weight:700;
  font-size:.8rem;padding:.7rem 1.6rem}
.btn-approve:hover{background:#b91c1c;border-color:#b91c1c}
.btn-approve:disabled{opacity:.4;cursor:not-allowed}
.btn-reject{font-size:.8rem;padding:.7rem 1.2rem}
.actions{display:flex;justify-content:flex-end;gap:.75rem;margin-top:1.5rem;padding-top:1.25rem;border-top:var(--glass-border)}
.result{border-radius:12px;padding:1rem 1.1rem;margin-top:1rem;border:1px solid rgba(34,197,94,.35);
  background:rgba(34,197,94,.07);font-size:.85rem}
.result.err{border-color:rgba(220,38,38,.4);background:rgba(220,38,38,.08)}
.result a{color:#4ade80;font-family:var(--font-mono);font-size:.78rem;word-break:break-all}
.result.err a,.result.err{color:#f87171}
#toast{position:fixed;bottom:1.4rem;right:1.4rem;background:var(--base-800);border:var(--glass-border);
  border-left:3px solid var(--brand-red);border-radius:10px;padding:.7rem 1.1rem;font-family:var(--font-mono);
  font-size:.72rem;opacity:0;transform:translateY(8px);transition:.25s;z-index:99}
#toast.show{opacity:1;transform:translateY(0)}
.hintbar{font-family:var(--font-mono);font-size:.62rem;color:var(--text-muted);margin-top:.4rem}
</style>
</head>
<body>
<div class="noise"></div><div class="orb orb-red"></div>
<div class="wrap">
  <header>
    <div class="brand">
      <img class="logo" src="/assets/pyresec-icon.png" alt="PYRESEC">
      <div><h1>PYRESEC <span>Social Deck</span></h1>
      <div class="sub">Zero-Day Breakdown · approval console</div></div>
    </div>
    <div class="pills">
      <div class="pill"><span class="dot" id="dot-daemon"></span>DAEMON</div>
      <div class="pill"><span class="dot" id="dot-fc"></span>FARCASTER @RENAAT</div>
      <div class="pill" id="pill-count">0 PENDING</div>
    </div>
  </header>
  <div class="grid">
    <div class="card"><h2>Queue</h2><div id="queue"></div></div>
    <div class="card" id="detail"><div class="empty"><div class="big">NO CARD SELECTED</div>
      Select a social bundle on the left to run pre-flight checks.</div></div>
  </div>
</div>
<div id="toast"></div>
<script>
let current = null, busy = false;
const $ = s => document.querySelector(s);
const esc = t => String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function toast(msg){ const t=$('#toast'); t.textContent=msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),2200); }
async function copyText(text, btn){
  try{ await navigator.clipboard.writeText(text); toast('COPIED TO CLIPBOARD');
    if(btn){ const o=btn.textContent; btn.textContent='COPIED'; setTimeout(()=>btn.textContent=o,1200);} }
  catch(e){ toast('COPY FAILED — SELECT TEXT MANUALLY'); }
}
async function refresh(){
  try{
    const s = await (await fetch('/api/state')).json();
    $('#dot-daemon').className = 'dot ' + (s.daemon_alive?'ok':'bad');
    $('#dot-fc').className = 'dot ' + (s.farcaster.configured?'ok':'bad');
    const pend = s.queue.filter(q=>q.status==='pending').length;
    $('#pill-count').textContent = pend + ' PENDING';
    const q = $('#queue');
    if(!s.queue.length){ q.innerHTML = '<div class="empty"><div class="big">QUEUE CLEAR</div>'+
      'Next bundle arrives via the weekly Shadow Audit<br>or run on demand: '+
      '<code>python scripts\\shadow_audit.py --limit 1 && python scripts\\social_pipeline.py</code></div>'; }
    else{
      q.innerHTML = s.queue.map(item =>
        `<div class="q-item ${current===item.qid?'active':''}" onclick="openCard('${item.qid}')">
          <div class="row"><span class="slug">${esc(item.slug||item.qid)}</span>
          <span class="badge ${item.rating||''}">${item.rating||'?'}</span></div>
          <div class="row" style="margin-top:.35rem">
            <span class="meta">${(item.created_at||'').slice(0,16).replace('T',' ')}</span>
            <span class="badge ${item.status}">${item.status.toUpperCase()}</span></div>
        </div>`).join('');
    }
  }catch(e){ /* daemon down or server restarting */ }
}
async function openCard(qid){
  current = qid; busy = false; refresh();
  const d = await (await fetch('/api/card/'+qid)).json();
  const draft = d.draft || {};
  const tweets = draft.x_thread || [];
  const tchars = tweets.reduce((a,t)=>a+t.length,0);
  const fbytes = new TextEncoder().encode(draft.farcaster||'').length;
  const locked = d.status !== 'pending';
  $('#detail').innerHTML = `
    <h2>Pre-Flight — ${esc(draft.slug||'')}</h2>
    <table>
      <tr><th>Channel</th><th>Account</th><th>Mode</th><th>Check</th></tr>
      <tr><td class="mono">Farcaster</td><td class="mono">@renaat → /security</td>
        <td class="mode-auto">AUTO</td><td class="mono">${d.farcaster_ok?'signer approved':'signer MISSING'}</td></tr>
      <tr><td class="mono">X / Twitter</td><td class="mono">@Nanoclone_S</td>
        <td class="mode-copy">COPY-PASTE</td><td class="mono">${tweets.length} tweet(s)</td></tr>
      <tr><td class="mono">LinkedIn</td><td class="mono">Renaat Sibanda · NanoClone</td>
        <td class="mode-copy">COPY-PASTE</td><td class="mono">founder post</td></tr>
    </table>
    <div class="section-label x"><span>✕ X / Twitter Thread</span><span>${tchars} chars total</span></div>
    ${tweets.map((t,i)=>`<div class="tweet"><div class="head">
        <span class="num">TWEET ${i+1}/${tweets.length}</span>
        <span class="count ${t.length>280?'over':''}">${t.length}/280</span></div>
      <pre>${esc(t)}</pre>
      <div class="btns"><button onclick="copyText(this.previousElementSibling.textContent,this)">COPY</button></div>
    </div>`).join('')}
    <div class="section-label fc"><span>◈ Farcaster cast</span><span>${fbytes}/1024 bytes</span></div>
    <div class="tweet cast"><pre>${esc(draft.farcaster||'')}</pre>
      <div class="btns"><button onclick="copyText(this.previousElementSibling.textContent,this)">COPY</button></div></div>
    <div class="section-label li"><span>in LinkedIn post</span><span>${(draft.linkedin||'').length} chars</span></div>
    <div class="tweet li"><pre>${esc(draft.linkedin||'')}</pre>
      <div class="btns"><button onclick="copyText(this.previousElementSibling.textContent,this)">COPY</button></div></div>
    ${d.result ? `<div class="result ${d.result.status==='posted'?'':'err'}">
      ${d.result.status==='posted'
        ? `PUBLISHED — <a href="${esc(d.result.cast_url)}" target="_blank">${esc(d.result.cast_url)}</a>
           <div class="hintbar">X + LinkedIn texts above are live — paste into @Nanoclone_S and your LinkedIn.</div>`
        : 'ERROR — ' + esc((d.result.errors||[]).join('; '))}
      </div>` : ''}
    ${locked ? '' : `<div class="actions">
      <button class="btn-reject" onclick="act('reject')">❌ REJECT</button>
      <button class="btn-approve" onclick="act('approve')">✅ APPROVE &amp; PUBLISH</button>
    </div>`}`;
}
async function act(kind){
  if(busy||!current) return; busy = true;
  try{
    if(kind==='reject'){
      const r = await fetch('/api/reject/'+current,{method:'POST'});
      if(!r.ok) throw new Error((await r.json()).detail||'');
      toast('REJECTED'); refresh(); openCard(current); return;
    }
    toast('PUBLISHING FARCASTER CAST…');
    const r = await fetch('/api/approve/'+current,{method:'POST'});
    const body = await r.json();
    if(!r.ok) throw new Error(body.detail||'');
    if(body.result.status==='posted') toast('PUBLISHED — CAST LIVE');
    else toast('PUBLISH ERROR — SEE DETAIL');
    refresh(); openCard(current);
  }catch(e){ toast('FAILED — '+e.message); }
  finally{ busy=false; }
}
refresh(); setInterval(refresh, 10000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.get("/assets/pyresec-icon.png")
def asset_icon() -> FileResponse:
    return FileResponse(ROOT / "assets" / "pyresec-icon.png")


@app.get("/api/state")
def api_state() -> dict:
    daemon_alive = False
    try:
        if HEARTBEAT.exists():
            hb = datetime.fromisoformat(HEARTBEAT.read_text().strip())
            daemon_alive = (datetime.now(timezone.utc) - hb).total_seconds() < 120
    except Exception:
        pass
    try:
        import farcaster_api
        fc_state = farcaster_api.load_state()
        farcaster = {
            "configured": fc_state.get("status") == "approved",
            "fid": fc_state.get("fid"),
        }
    except Exception:
        farcaster = {"configured": False, "fid": None}
    queue = social_scanner.load_queue()
    social = [q for q in queue if q.get("kind") == "social_post"]
    summary = []
    for q in reversed(social[-30:]):
        draft = q.get("draft") or {}
        summary.append({
            "qid": q["qid"],
            "slug": draft.get("slug", q["qid"]),
            "rating": draft.get("rating", ""),
            "status": q.get("status", "pending"),
            "created_at": q.get("created_at", ""),
        })
    return {"daemon_alive": daemon_alive, "farcaster": farcaster, "queue": summary}


@app.get("/api/card/{qid}")
def api_card(qid: str) -> dict:
    queue = social_scanner.load_queue()
    entry = next((q for q in queue if q["qid"] == qid and q.get("kind") == "social_post"), None)
    if not entry:
        raise HTTPException(404, "queue entry not found")
    try:
        import farcaster_api
        fc_ok = farcaster_api.load_state().get("status") == "approved"
    except Exception:
        fc_ok = False
    out = {
        "qid": entry["qid"],
        "status": entry.get("status", "pending"),
        "created_at": entry.get("created_at", ""),
        "draft": entry.get("draft") or {},
        "farcaster_ok": fc_ok,
        "cast_url": entry.get("cast_url", ""),
    }
    if entry.get("status") in ("posted", "error"):
        out["result"] = {
            "status": entry.get("status"),
            "cast_url": entry.get("cast_url", ""),
            "errors": [e for e in (entry.get("error") or "").split("; ") if e],
        }
    return out


@app.post("/api/approve/{qid}")
def api_approve(qid: str) -> dict:
    with _lock:
        queue = social_scanner.load_queue()
        entry = next((q for q in queue if q["qid"] == qid and q.get("kind") == "social_post"), None)
        if not entry:
            raise HTTPException(404, "queue entry not found")
        if entry.get("status") != "pending":
            raise HTTPException(409, f"already {entry.get('status')}")
        result = social_pipeline.publish_approved(entry)
        social_scanner.save_queue(queue)
        draft = entry.get("draft") or {}
        tg_msg = entry.get("tg_message_id")
    try:
        import telegram_app
        if result["status"] == "posted":
            telegram_app.notify(
                f"📤 Social Deck: published {draft.get('slug', '')}\n"
                f"Farcaster: {result['cast_url']}")
            if tg_msg:
                telegram_app.edit_message(
                    tg_msg,
                    f"✅ Published via Social Deck — {draft.get('slug', '')}\n"
                    f"Farcaster: {result['cast_url']}")
        else:
            telegram_app.notify(
                f"⚠️ Social Deck: publish issue — {'; '.join(result['errors'])}")
    except Exception:
        pass
    return {"result": result}


@app.post("/api/reject/{qid}")
def api_reject(qid: str) -> dict:
    with _lock:
        queue = social_scanner.load_queue()
        entry = next((q for q in queue if q["qid"] == qid and q.get("kind") == "social_post"), None)
        if not entry:
            raise HTTPException(404, "queue entry not found")
        if entry.get("status") != "pending":
            raise HTTPException(409, f"already {entry.get('status')}")
        entry["status"] = "rejected"
        social_scanner.save_queue(queue)
        tg_msg = entry.get("tg_message_id")
        slug = (entry.get("draft") or {}).get("slug", "")
    try:
        import telegram_app
        if tg_msg:
            telegram_app.edit_message(tg_msg, f"❌ Rejected via Social Deck — {slug}")
    except Exception:
        pass
    return {"status": "rejected"}


def main() -> None:
    import uvicorn

    log_path = ROOT / "scripts" / ".social_portal.log"

    def _log(msg: str) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
        except OSError:
            pass

    port = 8790
    for candidate in (8790, 8791, 8792):
        try:
            probe = __import__("socket").create_connection(("127.0.0.1", candidate), 0.3)
            probe.close()
            continue
        except OSError:
            port = candidate
            break
    _log(f"starting server on 127.0.0.1:{port}")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        time.sleep(0.25)
        if server.started:
            break
    _log(f"server started={server.started} url={url}")
    try:
        import webview
        _log("opening pywebview window")
        webview.create_window(
            "PYRESEC — Social Deck", url,
            width=1320, height=880, min_size=(980, 680),
            background_color="#050505", text_select=True)
        webview.start()
        _log("webview window closed — exiting")
    except Exception as e:
        _log(f"webview failed ({e}) — browser fallback")
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
