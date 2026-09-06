"""logsum-stats: a dependency-free web dashboard for the logsum (Drain3) token savings.

    logsum-stats --port 8765            # then open http://localhost:8765
Reads ~/.local/share/logsum/stats.jsonl (or LOGSUM_STATS). Pure standard library.
"""
import argparse
import json
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATS_PATH = Path(os.environ.get("LOGSUM_STATS") or Path.home() / ".local/share/logsum/stats.jsonl")
# Optional hook/plugin audit logs (tab-separated: ts, agent, decision, detail, command), colon-separated paths.
INSPECT_LOGS = [Path(p) for p in os.environ.get("LOGSUM_INSPECT_LOGS", "").split(":") if p]
_cache = {"mtime": None, "rows": []}
_icache: dict[str, dict] = {}


def load_inspections() -> list[dict]:
    """Every shell command the hooks looked at, whether or not it was summarized."""
    rows: list[dict] = []
    for p in INSPECT_LOGS:
        try:
            mtime = p.stat().st_mtime
        except FileNotFoundError:
            continue
        c = _icache.get(str(p))
        if not c or c["mtime"] != mtime:
            parsed = []
            with p.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 3:
                        parsed.append({"ts": parts[0], "agent": parts[1], "decision": parts[2],
                                       "detail": parts[3] if len(parts) > 3 else "", "cmd": parts[4] if len(parts) > 4 else ""})
            c = {"mtime": mtime, "rows": parsed}
            _icache[str(p)] = c
        rows += c["rows"]
    return rows


def load_rows() -> list[dict]:
    try:
        mtime = STATS_PATH.stat().st_mtime
    except FileNotFoundError:
        return []
    if _cache["mtime"] != mtime:
        rows = []
        with STATS_PATH.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        _cache.update(mtime=mtime, rows=rows)
    return _cache["rows"]


def aggregate(days: int) -> dict:
    rows = load_rows()
    since = datetime.now() - timedelta(days=days)
    keep = [r for r in rows if datetime.strptime(r["ts"][:19], "%Y-%m-%dT%H:%M:%S") >= since]
    summarized = [r for r in keep if not r.get("passthrough")]
    tot = lambda rs, k: sum(r.get(k, 0) for r in rs)  # noqa: E731
    by_day: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tok_in": 0, "tok_out": 0})
    by_agent: dict[str, dict] = defaultdict(lambda: {"calls": 0, "passthrough": 0, "tok_in": 0, "tok_out": 0, "lines_in": 0, "lines_out": 0})
    for r in keep:
        d = r["ts"][:10]
        a = by_agent[r.get("agent") or "unknown"]
        a["calls"] += 1
        if r.get("passthrough"):
            a["passthrough"] += 1
            continue
        by_day[d]["calls"] += 1
        by_day[d]["tok_in"] += r.get("tok_in", 0)
        by_day[d]["tok_out"] += r.get("tok_out", 0)
        for k in ("tok_in", "tok_out", "lines_in", "lines_out"):
            a[k] += r.get(k, 0)
    day_list = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        day_list.append({"day": d, **by_day.get(d, {"calls": 0, "tok_in": 0, "tok_out": 0})})
    recent = sorted(keep, key=lambda r: r["ts"], reverse=True)[:60]
    latest = next((r for r in recent if not r.get("passthrough")), None)

    # hook activity: inspected vs rewritten, per agent (timestamps in the audit logs are UTC ISO)
    since_utc = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    insp = [r for r in load_inspections()
            if r["ts"][:19].replace("T", " ") >= since_utc.strftime("%Y-%m-%d %H:%M:%S")]
    insp_by_agent: dict[str, dict] = defaultdict(lambda: {"inspected": 0, "rewritten": 0, "skipped": 0})
    for r in insp:
        a = insp_by_agent[r["agent"]]
        a["inspected"] += 1
        if r["decision"] == "rewrite":
            a["rewritten"] += 1
        elif r["decision"].startswith("skip"):
            a["skipped"] += 1
    agents_out = []
    names = set(by_agent) | set(insp_by_agent)
    for name in names:
        s = by_agent.get(name, {"calls": 0, "passthrough": 0, "tok_in": 0, "tok_out": 0, "lines_in": 0, "lines_out": 0})
        agents_out.append({"agent": name, **s, **insp_by_agent.get(name, {"inspected": 0, "rewritten": 0, "skipped": 0})})
    agents_out.sort(key=lambda x: (-x["tok_in"], -x["inspected"]))
    recent_insp = sorted(insp, key=lambda r: r["ts"], reverse=True)[:40]
    return {
        "inspect": {"total": len(insp), "rewritten": sum(1 for r in insp if r["decision"] == "rewrite"),
                    "skipped": sum(1 for r in insp if r["decision"].startswith("skip")),
                    "sources": [str(p) for p in INSPECT_LOGS], "recent": recent_insp},
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "stats_file": str(STATS_PATH),
        "days": days,
        "totals": {
            "calls": len(keep), "summarized": len(summarized), "passthrough": len(keep) - len(summarized),
            "tok_in": tot(summarized, "tok_in"), "tok_out": tot(summarized, "tok_out"),
            "lines_in": tot(summarized, "lines_in"), "lines_out": tot(summarized, "lines_out"),
            "ms_avg": round(tot(summarized, "ms") / len(summarized)) if summarized else 0,
            "exact_tokens": all(r.get("tok_method") == "tiktoken" for r in summarized) if summarized else True,
        },
        "by_day": day_list,
        "by_agent": agents_out,
        "recent": recent,
        "latest": latest,
    }


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>logsum stats</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--good:#006300;--wild:#8a4b00}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--good:#0ca30c;--wild:#e0a24a}}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 20px 60px;display:grid;gap:22px}
h1{font-size:1.35rem;margin:0;font-weight:600}h2{font-size:1rem;margin:0;font-weight:600;color:var(--ink)}
.sub{color:var(--ink2);font-size:.9rem}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.tile{background:var(--surface);border:1px solid var(--ring);border-radius:6px;padding:12px 14px;display:grid;gap:2px}
.tile .v{font-size:1.6rem;font-weight:600;letter-spacing:-.01em}.tile .l{font-size:.78rem;color:var(--muted);letter-spacing:.03em;text-transform:uppercase}
.tile .d{font-size:.8rem;color:var(--ink2)}.hero .v{color:var(--good)}
.panel{background:var(--surface);border:1px solid var(--ring);border-radius:6px;padding:14px 16px;display:grid;gap:10px}
.legend{display:flex;gap:16px;font-size:.85rem;color:var(--ink2)}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
svg{width:100%;height:auto;display:block}
.tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--ring);border-radius:6px;padding:8px 10px;font-size:.82rem;box-shadow:0 4px 16px rgba(0,0,0,.15);display:none;color:var(--ink)}
table{border-collapse:collapse;width:100%;font-size:.86rem;font-variant-numeric:tabular-nums}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--muted);font-weight:500;font-size:.75rem;letter-spacing:.04em;text-transform:uppercase}td.n,th.n{text-align:right}tr:last-child td{border-bottom:0}
.wrap{overflow-x:auto}code{font:.82rem/1.4 ui-monospace,"Cascadia Mono",Consolas,monospace}
.tpl{display:grid;gap:4px}.tpl div{display:grid;grid-template-columns:64px 1fr;gap:8px;font:.82rem ui-monospace,Consolas,monospace}.tpl b{text-align:right;font-weight:500;color:var(--ink2)}.w{color:var(--wild)}
select,input,button{font:inherit;color:var(--ink);background:var(--surface);border:1px solid var(--axis);border-radius:4px;padding:3px 8px}input{width:80px}
button{cursor:pointer}button:hover{border-color:var(--s1)}
.muted{color:var(--muted)}.empty{padding:24px;text-align:center;color:var(--muted)}
details summary{cursor:pointer;color:var(--ink2)}
@media (prefers-reduced-motion:no-preference){.bar{transition:opacity .15s}}
</style></head><body><main>
<div class="row" style="justify-content:space-between">
  <div><h1>logsum · Drain3 token savings</h1><div class="sub" id="meta">loading…</div></div>
  <div class="row"><label>Range <select id="days"><option value="7">7 days</option><option value="14" selected>14 days</option><option value="30">30 days</option><option value="90">90 days</option></select></label>
  <label>Price $/Mtok <input id="price" type="number" step="0.25" min="0" value="3"></label><button id="refresh" type="button">Refresh</button></div>
</div>
<div class="tiles" id="tiles"></div>
<section class="panel"><div class="row" style="justify-content:space-between"><h2>Tokens per day</h2><div class="row"><div class="legend"><span><i style="background:var(--s1)"></i>read by the model</span><span><i style="background:var(--s2)"></i>saved by logsum</span></div><button id="tableToggle" type="button">Show as table</button></div></div>
  <div id="chart"></div><div class="wrap" id="daytable" hidden></div></section>
<section class="panel"><h2>Latest summary, how Drain3 saw it</h2><div id="latest" class="tpl"></div></section>
<section class="panel"><h2>By agent</h2><div class="wrap" id="agents"></div></section>
<section class="panel"><h2>Recent summaries</h2><div class="wrap" id="recent"></div></section>
<section class="panel"><h2>Recent shell commands the hooks looked at</h2><div class="sub">Every Bash/PowerShell call passes through the hook. <code>rewrite</code> = piped through Drain3, <code>inspect</code> = not a log read, <code>skip:*</code> = a log read left alone by rule (follow mode, already filtered, redirect, opt-out).</div><div class="wrap" id="inspections"></div></section>
<div class="tip" id="tip"></div>
</main>
<script>
const $=s=>document.querySelector(s);const fmt=n=>n.toLocaleString();const k=n=>n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(n>=1e4?0:1)+'k':String(n);
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const wild=s=>esc(s).replace(/&lt;([^&]*?)&gt;/g,'<span class="w">&lt;$1&gt;</span>');
try{const p=localStorage.getItem('logsum.price');if(p)$('#price').value=p;const d=localStorage.getItem('logsum.days');if(d)$('#days').value=d;}catch{}
let data=null;
async function load(){const days=$('#days').value;const r=await fetch('/api/stats?days='+days);data=await r.json();render();}
function render(){const t=data.totals,price=parseFloat($('#price').value)||0;const saved=t.tok_in-t.tok_out;const pct=t.tok_in?saved/t.tok_in:0;
$('#meta').textContent=`${data.stats_file} · updated ${data.generated} · ${t.exact_tokens?'exact cl100k counts':'estimated counts (install tiktoken for exact)'} · avg ${t.ms_avg} ms per summary`;
const ins=data.inspect||{total:0,rewritten:0,skipped:0};
$('#tiles').innerHTML=[
 ['Shell commands seen','',fmt(ins.total),`${fmt(ins.rewritten)} were log reads · ${fmt(ins.skipped)} skipped by rule`],
 ['Summaries','',fmt(t.summarized),`${fmt(t.passthrough)} short reads passed through`],
 ['Tokens before','',k(t.tok_in),`${fmt(t.lines_in)} log lines`],
 ['Tokens after','',k(t.tok_out),`${fmt(t.lines_out)} lines shown to the model`],
 ['Saved','hero',`${(pct*100).toFixed(0)}%`,`${fmt(saved)} tokens not sent`],
 ['Est. cost saved','hero','$'+(saved/1e6*price).toFixed(2),`at $${price}/Mtok input`]
].map(([l,c,v,d])=>`<div class="tile ${c}"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
chart();latest();agents();recent();}
function chart(){const rows=data.by_day,W=900,H=260,L=48,R=12,T=18,B=34,iw=W-L-R,ih=H-T-B;const max=Math.max(1,...rows.map(r=>r.tok_in));
const nice=[1,2,5,10,20,50,100,200,500,1e3,2e3,5e3,1e4,2e4,5e4,1e5,2e5,5e5,1e6].find(s=>max/s<=5)||1e6;const top=Math.ceil(max/nice)*nice;const y=v=>T+ih-(v/top)*ih;
let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="tokens per day">`;
for(let v=0;v<=top;v+=nice){s+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="${v?'var(--grid)':'var(--axis)'}" stroke-width="1"/><text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${k(v)}</text>`;}
const n=rows.length,slot=iw/n,bw=Math.max(6,Math.min(36,slot*0.6));const maxI=rows.reduce((m,r,i)=>r.tok_in>rows[m].tok_in?i:m,0);
rows.forEach((r,i)=>{const x=L+slot*i+(slot-bw)/2;const yo=y(r.tok_out),yi=y(r.tok_in);const svd=r.tok_in-r.tok_out;
 if(r.tok_out>0)s+=`<rect class="bar" x="${x}" y="${yo}" width="${bw}" height="${T+ih-yo}" fill="var(--s1)"/>`;
 if(svd>0){const h=Math.max(0,(yo-2)-yi);s+=`<rect class="bar" x="${x}" y="${yi}" width="${bw}" height="${h}" rx="3" fill="var(--s2)"/>`;}
 s+=`<rect x="${L+slot*i}" y="${T}" width="${slot}" height="${ih}" fill="transparent" data-i="${i}"/>`;
 if(r.tok_in&&(i===maxI||i===n-1))s+=`<text x="${x+bw/2}" y="${yi-5}" text-anchor="middle" font-size="11" fill="var(--ink2)">${k(r.tok_in)}</text>`;
 const lab=n<=14||i%Math.ceil(n/12)===0?r.day.slice(5):'';if(lab)s+=`<text x="${x+bw/2}" y="${H-12}" text-anchor="middle" font-size="11" fill="var(--muted)">${lab}</text>`;});
s+='</svg>';$('#chart').innerHTML=s;const tip=$('#tip');
$('#chart').querySelectorAll('rect[data-i]').forEach(el=>{el.addEventListener('mousemove',e=>{const r=rows[+el.dataset.i];const sv=r.tok_in-r.tok_out;tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';
 tip.innerHTML=`<b>${r.day}</b><br>${fmt(r.calls)} summaries<br>before ${fmt(r.tok_in)} · after ${fmt(r.tok_out)}<br>saved ${fmt(sv)} (${r.tok_in?Math.round(sv/r.tok_in*100):0}%)`;});el.addEventListener('mouseleave',()=>tip.style.display='none');});
$('#daytable').innerHTML=`<table><tr><th>day</th><th class="n">summaries</th><th class="n">before</th><th class="n">after</th><th class="n">saved</th></tr>${rows.filter(r=>r.calls).map(r=>`<tr><td>${r.day}</td><td class="n">${r.calls}</td><td class="n">${fmt(r.tok_in)}</td><td class="n">${fmt(r.tok_out)}</td><td class="n">${fmt(r.tok_in-r.tok_out)}</td></tr>`).join('')||'<tr><td colspan="5" class="muted">no summaries in range</td></tr>'}</table>`;}
function latest(){const r=data.latest;if(!r){$('#latest').innerHTML='<div class="empty">No summaries yet. Read a log of more than 40 lines through an agent and it will appear here.</div>';return;}
$('#latest').innerHTML=`<div class="sub">${esc(r.ts)} · ${esc(r.agent)} · <code>${esc(r.cmd||'(command not recorded)')}</code><br>${fmt(r.lines_in)} lines → ${r.templates} templates, ${fmt(r.rare_lines)} rare lines kept · ${fmt(r.tok_in)} → ${fmt(r.tok_out)} tokens in ${r.ms} ms</div>`+(r.top||[]).map(([c,t])=>`<div><b>${fmt(c)}×</b><span>${wild(t)}</span></div>`).join('');}
function agents(){const a=data.by_agent;if(!a.length){$('#agents').innerHTML='<div class="empty">no calls in range</div>';return;}
$('#agents').innerHTML=`<table><tr><th>agent</th><th class="n">commands seen</th><th class="n">log reads</th><th class="n">summaries</th><th class="n">passed through</th><th class="n">lines in → out</th><th class="n">tokens before</th><th class="n">after</th><th class="n">saved</th></tr>${a.map(x=>`<tr><td>${esc(x.agent)}</td><td class="n">${fmt(x.inspected||0)}</td><td class="n">${fmt(x.rewritten||0)}</td><td class="n">${x.calls-x.passthrough}</td><td class="n">${x.passthrough}</td><td class="n">${fmt(x.lines_in)} → ${fmt(x.lines_out)}</td><td class="n">${fmt(x.tok_in)}</td><td class="n">${fmt(x.tok_out)}</td><td class="n">${x.tok_in?Math.round((1-x.tok_out/x.tok_in)*100):0}%</td></tr>`).join('')}</table>`;
const ri=(data.inspect&&data.inspect.recent)||[];$('#inspections').innerHTML=ri.length?`<table><tr><th>time (UTC)</th><th>agent</th><th>decision</th><th>command</th></tr>${ri.map(r=>`<tr><td>${esc(r.ts.slice(0,19).replace('T',' '))}</td><td>${esc(r.agent)}</td><td>${esc(r.decision)}</td><td><code>${esc(r.cmd.slice(0,110))}</code></td></tr>`).join('')}</table>`:'<div class="empty">no hook activity recorded (set LOGSUM_INSPECT_LOGS for the service)</div>';}
function recent(){const rs=data.recent;if(!rs.length){$('#recent').innerHTML='<div class="empty">nothing recorded yet</div>';return;}
$('#recent').innerHTML=`<table><tr><th>time</th><th>agent</th><th>command</th><th class="n">lines</th><th class="n">tokens</th><th class="n">saved</th><th class="n">ms</th></tr>${rs.map(r=>{const p=r.passthrough;return `<tr><td>${esc(r.ts.slice(0,19).replace('T',' '))}</td><td>${esc(r.agent)}</td><td><code>${esc((r.cmd||'').slice(0,80))}</code>${p?' <span class="muted">(passthrough)</span>':(r.top&&r.top.length?`<details><summary>${r.templates} templates</summary><div class="tpl">${r.top.map(([c,t])=>`<div><b>${fmt(c)}×</b><span>${wild(t)}</span></div>`).join('')}</div></details>`:'')}</td><td class="n">${fmt(r.lines_in)} → ${fmt(r.lines_out)}</td><td class="n">${fmt(r.tok_in)} → ${fmt(r.tok_out)}</td><td class="n">${p?'—':Math.round((1-r.tok_out/Math.max(1,r.tok_in))*100)+'%'}</td><td class="n">${r.ms??''}</td></tr>`}).join('')}</table>`;}
$('#days').addEventListener('change',()=>{try{localStorage.setItem('logsum.days',$('#days').value)}catch{}load();});
$('#price').addEventListener('input',()=>{try{localStorage.setItem('logsum.price',$('#price').value)}catch{}if(data)render();});
$('#refresh').addEventListener('click',load);
$('#tableToggle').addEventListener('click',()=>{const t=$('#daytable');t.hidden=!t.hidden;$('#chart').hidden=!t.hidden;$('#tableToggle').textContent=t.hidden?'Show as table':'Show as chart';});
load();setInterval(load,15000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/stats":
            days = max(1, min(365, int(parse_qs(u.query).get("days", ["14"])[0])))
            body = json.dumps(aggregate(days)).encode()
            self._send(200, "application/json; charset=utf-8", body)
        elif u.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", PAGE.encode())
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quiet
        pass


def main():
    ap = argparse.ArgumentParser(description="logsum statistics dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"logsum-stats: http://{a.host}:{a.port}  (reading {STATS_PATH})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
