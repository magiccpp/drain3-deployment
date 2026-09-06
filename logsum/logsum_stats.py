"""logsum-stats: a dependency-free web dashboard for the logsum (Drain3) token savings.

    logsum-stats --port 8765            # then open http://localhost:8765
Reads ~/.local/share/logsum/stats.jsonl (or LOGSUM_STATS). Pure standard library.
"""
import argparse
import json
import os
import sqlite3
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
# OpenCode's local SQLite database (read-only). Assistant messages carry modelID/providerID, agent,
# tokens {input, output, reasoning, cache{read,write}} and cost; sessions with a parent_id are subagent runs.
OPENCODE_DB = Path(os.environ.get("LOGSUM_OPENCODE_DB") or Path.home() / ".local/share/opencode/opencode.db")


PRICES_PATH = Path(os.environ.get("LOGSUM_PRICES") or Path(__file__).resolve().parent / "prices.json")
_pcache: dict = {"mtime": None, "models": {}}
CANONICAL_ORDER = ("openai", "azure", "anthropic", "google", "xai", "deepseek", "mistral", "moonshotai", "zai")


def load_prices() -> dict:
    """List prices per 1M tokens, {provider/model: {input, output, cache_read, cache_write}} from prices.json."""
    try:
        mtime = PRICES_PATH.stat().st_mtime
    except FileNotFoundError:
        return {}
    if _pcache["mtime"] != mtime:
        try:
            _pcache.update(mtime=mtime, models=json.loads(PRICES_PATH.read_text(encoding="utf-8")).get("models", {}))
        except (OSError, json.JSONDecodeError):
            return {}
    return _pcache["models"]


def price_for(provider: str, model: str) -> tuple[dict | None, str]:
    """Find a list price for a provider/model. Rule: exact match; then any gpt-* model under a vendor
    other than openai is priced as Azure OpenAI; then the bare model id under a canonical provider."""
    table = load_prices()
    if not table:
        return None, ""
    key = f"{provider}/{model}"
    if key in table:
        return table[key], key
    base = model.split("/")[-1]
    for pre in ("openai.", "openai-", "global.openai.", "azure-"):
        if base.startswith(pre):
            base = base[len(pre):]
    if provider != "openai" and base.startswith("gpt-") and f"azure/{base}" in table:
        return table[f"azure/{base}"], f"azure/{base}"
    for prov in CANONICAL_ORDER:
        if f"{prov}/{base}" in table:
            return table[f"{prov}/{base}"], f"{prov}/{base}"
    return None, ""


def estimate_cost(vals: dict, price: dict) -> float:
    """USD for one message from token counts; reasoning tokens are billed as output."""
    return (vals["input"] * price.get("input", 0) + (vals["output"] + vals["reasoning"]) * price.get("output", 0)
            + vals["cache_read"] * price.get("cache_read", 0) + vals["cache_write"] * price.get("cache_write", 0)) / 1e6


_snap: dict = {"key": None, "path": None}


def _db_snapshot() -> str:
    """Copy opencode.db plus its -wal/-shm files to a private temp dir and open the copy.

    OpenCode keeps the database in WAL mode. Opening the original read-only with immutable=1 (needed
    on a read-only mount) ignores the WAL, so the newest sessions and messages are invisible until a
    checkpoint. A copy that includes the WAL is recovered normally on open and sees everything. The
    copy is refreshed only when any of the three files changes."""
    import shutil
    import tempfile
    parts = [OPENCODE_DB, Path(str(OPENCODE_DB) + "-wal"), Path(str(OPENCODE_DB) + "-shm")]
    key = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in parts)
    if key != _snap["key"] or not _snap["path"] or not Path(_snap["path"]).exists():
        d = Path(tempfile.gettempdir()) / "logsum-opencode-snapshot"
        d.mkdir(exist_ok=True)
        for p, name in zip(parts, ("snap.db", "snap.db-wal", "snap.db-shm")):
            dst = d / name
            if p.exists():
                shutil.copyfile(p, dst)
            elif dst.exists():
                dst.unlink()
        _snap.update(key=key, path=str(d / "snap.db"))
    return _snap["path"]


def load_opencode(days: int) -> dict:
    """Per model endpoint and per agent token usage from OpenCode, main vs subagent sessions kept apart.
    Also returns "_msgs": sorted [(time_ms, provider/model)] so logsum records can be matched to the
    model that read them (stripped before the JSON response)."""
    empty = {"available": False, "db": str(OPENCODE_DB), "totals": {}, "by_model": [], "by_agent": [], "by_day": [], "sessions": 0, "_msgs": [], "_sessions": {}}
    if not OPENCODE_DB.exists():
        return empty
    since_ms = int((time.time() - days * 86400) * 1000)
    rows = []
    for attempt in range(2):  # retry once on a torn read (the snapshot is taken while OpenCode may be writing)
        try:
            con = sqlite3.connect(_db_snapshot(), timeout=1)
            try:
                rows = con.execute(
                    "SELECT m.time_created, m.data, s.parent_id, s.id, s.title FROM message m JOIN session s ON s.id = m.session_id "
                    "WHERE m.time_created >= ?", (since_ms,)).fetchall()
                # every session's own model (subagent sessions carry the subagent's model): exact attribution for summaries
                session_models = {}
                for sid, mjson in con.execute("SELECT id, model FROM session WHERE model IS NOT NULL"):
                    try:
                        mm = json.loads(mjson)
                        if mm.get("id"):
                            session_models[sid] = f"{mm.get('providerID') or '?'}/{mm['id']}"
                    except (json.JSONDecodeError, TypeError):
                        pass
            finally:
                con.close()
            break
        except sqlite3.Error as e:
            if attempt == 1:
                return {**empty, "error": str(e)}
    def bucket():
        return {"messages": 0, "input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0,
                "cost": 0.0, "cost_recorded": 0.0, "cost_estimated": 0.0, "estimated_msgs": 0, "unpriced_msgs": 0, "price_basis": set()}
    by_model: dict[tuple, dict] = defaultdict(bucket)
    by_agent: dict[tuple, dict] = defaultdict(lambda: {**bucket(), "models": set()})
    by_day: dict[str, dict] = defaultdict(lambda: {"main": 0, "subagent": 0, "cost": 0.0})
    sessions = set()
    msgs: list[tuple[int, str]] = []
    for t_ms, data, parent_id, sid, title in rows:
        try:
            d = json.loads(data)
        except json.JSONDecodeError:
            continue
        if d.get("role") != "assistant":
            continue
        tok = d.get("tokens") or {}
        cache = tok.get("cache") or {}
        model = f"{d.get('providerID') or '?'}/{d.get('modelID') or '?'}"
        msgs.append((int(t_ms), model))
        role = "subagent" if parent_id else "main"
        agent = d.get("agent") or d.get("mode") or "?"
        vals = {"input": tok.get("input", 0) or 0, "output": tok.get("output", 0) or 0, "reasoning": tok.get("reasoning", 0) or 0,
                "cache_read": cache.get("read", 0) or 0, "cache_write": cache.get("write", 0) or 0}
        recorded = float(d.get("cost") or 0)
        estimated, basis, unpriced = 0.0, "", False
        if recorded <= 0 and sum(vals.values()) > 0:
            price, basis = price_for(d.get("providerID") or "", d.get("modelID") or "")
            if price:
                estimated = estimate_cost(vals, price)
            else:
                unpriced = True
        vals["cost"] = recorded + estimated
        for b in (by_model[(model, role)], by_agent[(agent, role)]):
            b["messages"] += 1
            for k, v in vals.items():
                b[k] += v
            b["cost_recorded"] += recorded
            b["cost_estimated"] += estimated
            b["estimated_msgs"] += 1 if estimated else 0
            b["unpriced_msgs"] += 1 if unpriced else 0
            if recorded > 0 or estimated > 0 or unpriced:
                b["price_basis"].add(basis if basis else ("recorded" if recorded > 0 else "none"))
        by_agent[(agent, role)]["models"].add(model)
        day = datetime.fromtimestamp(t_ms / 1000).strftime("%Y-%m-%d")
        by_day[day][role] += vals["input"] + vals["output"] + vals["cache_read"] + vals["cache_write"]
        by_day[day]["cost"] += vals["cost"]
        sessions.add(sid)
    totals = {"messages": 0, "input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0,
              "cost": 0.0, "cost_recorded": 0.0, "cost_estimated": 0.0, "estimated_msgs": 0, "unpriced_msgs": 0}
    for v in by_model.values():
        for k in totals:
            totals[k] += v[k]

    def finish(v: dict) -> dict:
        out = {k: (sorted(x) if isinstance(x, set) else x) for k, x in v.items()}
        return out
    day_list = []
    for i in range(days - 1, -1, -1):
        dd = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        day_list.append({"day": dd, **by_day.get(dd, {"main": 0, "subagent": 0, "cost": 0.0})})
    return {
        "available": True, "db": str(OPENCODE_DB), "sessions": len(sessions), "totals": totals,
        "prices": {"file": str(PRICES_PATH), "models": len(load_prices())},
        "by_model": sorted([{"model": m, "role": r, **finish(v)} for (m, r), v in by_model.items()], key=lambda x: (-x["cost"], x["model"], x["role"])),
        "by_agent": sorted([{"agent": a, "role": r, **finish(vv)} for (a, r), vv in by_agent.items()], key=lambda x: (x["role"], -x["cost"])),
        "by_day": day_list,
        "_msgs": sorted(msgs),
        "_sessions": session_models,
    }


def _ts_ms(ts: str) -> int:
    """logsum record timestamp ('2026-09-06T17:34:51+0800') to epoch ms."""
    try:
        return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").timestamp() * 1000)
    except ValueError:
        return int(datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timestamp() * 1000)


def resolve_model(rec: dict, agent_models: dict, msgs: list[tuple[int, str]], sessions: dict | None = None) -> tuple[str, str]:
    """Which model read this summary? (model, how): the caller said so; or the OpenCode session it
    named (exact, works for subagents); or OpenCode's next assistant message within 15 minutes; or a
    configured fallback per agent."""
    if rec.get("model"):
        return rec["model"], "recorded"
    if rec.get("session") and sessions and rec["session"] in sessions:
        return sessions[rec["session"]], "opencode-session"
    if rec.get("agent") == "opencode" and msgs:
        import bisect
        t = _ts_ms(rec["ts"])
        i = bisect.bisect_left(msgs, (t, ""))
        if i < len(msgs) and msgs[i][0] - t <= 15 * 60 * 1000:
            return msgs[i][1], "opencode-db"
    fb = agent_models.get(rec.get("agent") or "")
    return (fb, "fallback") if fb else ("", "unknown")


def input_price(model: str) -> tuple[float | None, str]:
    """USD per token of uncached input for a provider/model, via the same lookup rule as OpenCode costs."""
    if not model or "/" not in model:
        return None, ""
    prov, mid = model.split("/", 1)
    price, basis = price_for(prov, mid)
    return (price.get("input", 0) / 1e6, basis) if price else (None, "")


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


DEFAULT_AGENT_MODELS = {"claude-code": "anthropic/claude-sonnet-5"}   # used only when a record carries no model


def aggregate(days: int, agent_models: dict | None = None) -> dict:
    agent_models = {**DEFAULT_AGENT_MODELS, **(agent_models or {})}
    rows = load_rows()
    since = datetime.now() - timedelta(days=days)
    keep = [r for r in rows if datetime.strptime(r["ts"][:19], "%Y-%m-%dT%H:%M:%S") >= since]
    summarized = [r for r in keep if not r.get("passthrough")]
    opencode = load_opencode(days)
    oc_msgs = opencode.pop("_msgs", [])
    oc_sessions = opencode.pop("_sessions", {})

    # price each summary's saved tokens at the input rate of the model that read it
    saving = {"cost": 0.0, "by_how": defaultdict(int), "unpriced": 0}
    saving_by_agent: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "models": set(), "unpriced": 0})
    for r in summarized:
        model, how = resolve_model(r, agent_models, oc_msgs, oc_sessions)
        ppt, basis = input_price(model)
        saved = max(0, r.get("tok_in", 0) - r.get("tok_out", 0))
        r["_model"], r["_how"] = model, how
        if ppt is None:
            saving["unpriced"] += 1
            saving_by_agent[r.get("agent") or "unknown"]["unpriced"] += 1
            continue
        r["_saved_cost"] = saved * ppt
        saving["cost"] += saved * ppt
        saving["by_how"][how] += 1
        a = saving_by_agent[r.get("agent") or "unknown"]
        a["cost"] += saved * ppt
        a["models"].add(model if basis == model else f"{model} @ {basis}")
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
        sa = saving_by_agent.get(name, {"cost": 0.0, "models": set(), "unpriced": 0})
        agents_out.append({"agent": name, **s, **insp_by_agent.get(name, {"inspected": 0, "rewritten": 0, "skipped": 0}),
                           "saved_cost": sa["cost"], "priced_as": sorted(sa["models"]), "unpriced": sa["unpriced"]})
    agents_out.sort(key=lambda x: (-x["tok_in"], -x["inspected"]))
    recent_insp = sorted(insp, key=lambda r: r["ts"], reverse=True)[:40]
    prices = load_prices()
    return {
        "opencode": opencode,
        "saving": {"cost": saving["cost"], "by_how": dict(saving["by_how"]), "unpriced": saving["unpriced"],
                   "agent_models": agent_models, "model_choices": sorted(k for k in prices if k.startswith("anthropic/"))},
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
        "recent": [{k: v for k, v in r.items() if not k.startswith("_")} | {"model": r.get("_model", r.get("model")), "model_how": r.get("_how"), "saved_cost": r.get("_saved_cost")} for r in recent],
        "latest": latest,
    }


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>logsum stats</title>
<style>
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--good:#006300;--wild:#8a4b00}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;--ring:rgba(255,255,255,.10);--s1:#3987e5;--s2:#d95926;--s3:#199e70;--good:#0ca30c;--wild:#e0a24a}}
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
  <div><h1>logsum · OpenCode usage and Drain3 savings</h1><div class="sub" id="meta">loading…</div></div>
  <div class="row"><label>Range <select id="days"><option value="7">7 days</option><option value="14" selected>14 days</option><option value="30">30 days</option><option value="90">90 days</option></select></label>
  <label title="Used only for Claude Code summaries recorded before the hook started reporting the session model">Price Claude Code as <select id="ccmodel"></select></label><button id="refresh" type="button">Refresh</button></div>
</div>
<section class="panel"><div class="row" style="justify-content:space-between"><h2>OpenCode usage, per model endpoint</h2><div class="sub" id="ocmeta"></div></div>
  <div class="tiles" id="octiles"></div>
  <div class="row" style="justify-content:space-between;margin-top:6px"><div class="legend"><span><i style="background:var(--s1)"></i>main agent</span><span><i style="background:var(--s3)"></i>subagents</span><span class="muted">tokens per day (input + output + cache)</span></div></div>
  <div id="occhart"></div>
  <div class="wrap" id="ocmodels"></div>
  <h2 style="margin-top:6px">OpenCode usage, per agent</h2><div class="sub">Main and subagent sessions are kept apart, so a build agent on one model and an explore or logs subagent on another never get mixed.</div>
  <div class="wrap" id="ocagents"></div></section>
<h2 style="margin-top:4px">Drain3 log summaries (logsum)</h2>
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
let ccModel='';try{ccModel=localStorage.getItem('logsum.ccmodel')||'';const d=localStorage.getItem('logsum.days');if(d)$('#days').value=d;}catch{}
let data=null;
async function load(){const days=$('#days').value;const am=ccModel?'&agent_models='+encodeURIComponent('claude-code:'+ccModel):'';const r=await fetch('/api/stats?days='+days+am);data=await r.json();render();}
function render(){const t=data.totals;const saved=t.tok_in-t.tok_out;const pct=t.tok_in?saved/t.tok_in:0;const sv=data.saving||{cost:0,by_how:{},unpriced:0,agent_models:{},model_choices:[]};
const sel=$('#ccmodel');const cur=sv.agent_models['claude-code']||'';if(sel.options.length!==sv.model_choices.length){sel.innerHTML=sv.model_choices.map(m=>`<option value="${m}">${m}</option>`).join('');}sel.value=cur;
const how=sv.by_how;const howTxt=[how.recorded?`${how.recorded} by session model`:'',how['opencode-session']?`${how['opencode-session']} by OpenCode session`:'',how['opencode-db']?`${how['opencode-db']} by nearest OpenCode message`:'',how.fallback?`${how.fallback} by fallback`:'',sv.unpriced?`${sv.unpriced} unpriced`:''].filter(Boolean).join(' · ');
$('#meta').textContent=`${data.stats_file} · updated ${data.generated} · ${t.exact_tokens?'exact cl100k counts':'estimated counts (install tiktoken for exact)'} · avg ${t.ms_avg} ms per summary`;
const ins=data.inspect||{total:0,rewritten:0,skipped:0};
$('#tiles').innerHTML=[
 ['Shell commands seen','',fmt(ins.total),`${fmt(ins.rewritten)} were log reads · ${fmt(ins.skipped)} skipped by rule`],
 ['Summaries','',fmt(t.summarized),`${fmt(t.passthrough)} short reads passed through`],
 ['Tokens before','',k(t.tok_in),`${fmt(t.lines_in)} log lines`],
 ['Tokens after','',k(t.tok_out),`${fmt(t.lines_out)} lines shown to the model`],
 ['Saved','hero',`${(pct*100).toFixed(0)}%`,`${fmt(saved)} tokens not sent`],
 ['Cost saved','hero','$'+sv.cost.toFixed(sv.cost<1?4:2),`at each model's own input rate · ${howTxt||'no summaries'}`]
].map(([l,c,v,d])=>`<div class="tile ${c}"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
chart();opencode();latest();agents();recent();}
function opencode(){const oc=data.opencode;if(!oc||!oc.available){$('#ocmeta').textContent='';$('#octiles').innerHTML='';$('#occhart').innerHTML='';$('#ocmodels').innerHTML=`<div class="empty">OpenCode database not found at ${esc(oc?oc.db:'?')}${oc&&oc.error?' ('+esc(oc.error)+')':''}. Mount it or set LOGSUM_OPENCODE_DB.</div>`;$('#ocagents').innerHTML='';return;}
const t=oc.totals;$('#ocmeta').textContent=`${oc.sessions} sessions · ${fmt(t.messages)} assistant messages · ${esc(oc.db)}`;
const costNote=t.cost_estimated>0?`$${t.cost_recorded.toFixed(4)} recorded by OpenCode + $${t.cost_estimated.toFixed(4)} estimated from list prices (${t.estimated_msgs} msgs)`:'as recorded by OpenCode';
const unpriced=t.unpriced_msgs>0?` · ${t.unpriced_msgs} msgs with no price found`:'';
$('#octiles').innerHTML=[['Cost','hero','$'+t.cost.toFixed(4),costNote+unpriced],['Input tokens','',k(t.input),'uncached prompt tokens'],['Output tokens','',k(t.output),(t.reasoning?fmt(t.reasoning)+' reasoning':'')],['Cache read','',k(t.cache_read),'prompt tokens served from cache'],['Cache write','',k(t.cache_write),'tokens written to cache']].map(([l,c,v,d])=>`<div class="tile ${c}"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
const rows=oc.by_day,W=900,H=200,L=48,R=12,T=14,B=30,iw=W-L-R,ih=H-T-B;const max=Math.max(1,...rows.map(r=>r.main+r.subagent));
const nice=[1,2,5,10,20,50,100,200,500,1e3,2e3,5e3,1e4,2e4,5e4,1e5,2e5,5e5,1e6,2e6,5e6].find(s=>max/s<=5)||5e6;const top=Math.ceil(max/nice)*nice;const y=v=>T+ih-(v/top)*ih;
let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="opencode tokens per day">`;for(let v=0;v<=top;v+=nice){s+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="${v?'var(--grid)':'var(--axis)'}"/><text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${k(v)}</text>`;}
const n=rows.length,slot=iw/n,bw=Math.max(6,Math.min(36,slot*0.6));rows.forEach((r,i)=>{const x=L+slot*i+(slot-bw)/2;const ym=y(r.main),yt=y(r.main+r.subagent);
 if(r.main>0)s+=`<rect x="${x}" y="${ym}" width="${bw}" height="${T+ih-ym}" fill="var(--s1)"/>`;if(r.subagent>0)s+=`<rect x="${x}" y="${yt}" width="${bw}" height="${Math.max(0,(ym-2)-yt)}" rx="3" fill="var(--s3)"/>`;
 s+=`<rect x="${L+slot*i}" y="${T}" width="${slot}" height="${ih}" fill="transparent" data-oc="${i}"/>`;const lab=n<=14||i%Math.ceil(n/12)===0?r.day.slice(5):'';if(lab)s+=`<text x="${x+bw/2}" y="${H-10}" text-anchor="middle" font-size="11" fill="var(--muted)">${lab}</text>`;});
s+='</svg>';$('#occhart').innerHTML=s;const tip=$('#tip');$('#occhart').querySelectorAll('rect[data-oc]').forEach(el=>{el.addEventListener('mousemove',e=>{const r=rows[+el.dataset.oc];tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';tip.innerHTML=`<b>${r.day}</b><br>main ${fmt(r.main)} · subagents ${fmt(r.subagent)}<br>cost $${r.cost.toFixed(4)}`;});el.addEventListener('mouseleave',()=>tip.style.display='none');});
const roleTag=r=>r==='subagent'?'<span class="muted">subagent</span>':'main';
const costCell=x=>{const est=x.cost_estimated>0;const t=est?`recorded $${x.cost_recorded.toFixed(4)} + estimated $${x.cost_estimated.toFixed(4)} (${x.estimated_msgs} msgs)`:'recorded by OpenCode';return `<td class="n" title="${t}">${est?'~':''}$${x.cost.toFixed(4)}${x.unpriced_msgs?` <span class="muted" title="${x.unpriced_msgs} messages had tokens but no price could be found">?</span>`:''}</td>`};
const basis=x=>(x.price_basis||[]).filter(b=>b!=='recorded').map(b=>b==='none'?'<span class="muted">no price</span>':`<code>${esc(b)}</code>`).join(' ')||'<span class="muted">recorded</span>';
$('#ocmodels').innerHTML=oc.by_model.length?`<table><tr><th>model endpoint</th><th>role</th><th class="n">messages</th><th class="n">input</th><th class="n">output</th><th class="n">reasoning</th><th class="n">cache read</th><th class="n">cache write</th><th class="n">cost</th><th>price basis</th></tr>${oc.by_model.map(m=>`<tr><td><code>${esc(m.model)}</code></td><td>${roleTag(m.role)}</td><td class="n">${m.messages}</td><td class="n">${fmt(m.input)}</td><td class="n">${fmt(m.output)}</td><td class="n">${fmt(m.reasoning)}</td><td class="n">${fmt(m.cache_read)}</td><td class="n">${fmt(m.cache_write)}</td>${costCell(m)}<td>${basis(m)}</td></tr>`).join('')}</table><div class="sub" style="margin-top:6px">~ = includes estimated cost. Messages OpenCode recorded at $0 (custom or proxy providers) are priced from list prices: exact provider/model if known, otherwise GPT models under any vendor other than openai at Azure OpenAI prices, otherwise the model id under its canonical provider. Table: ${esc(oc.prices?oc.prices.file:'')} (${oc.prices?oc.prices.models:0} models).</div>`:'<div class="empty">no OpenCode messages in range</div>';
$('#ocagents').innerHTML=oc.by_agent.length?`<table><tr><th>agent</th><th>role</th><th>model(s)</th><th class="n">messages</th><th class="n">input</th><th class="n">output</th><th class="n">cache read</th><th class="n">cost</th></tr>${oc.by_agent.map(a=>`<tr><td>${esc(a.agent)}</td><td>${roleTag(a.role)}</td><td>${a.models.map(m=>`<code>${esc(m)}</code>`).join(' ')}</td><td class="n">${a.messages}</td><td class="n">${fmt(a.input)}</td><td class="n">${fmt(a.output)}</td><td class="n">${fmt(a.cache_read)}</td>${costCell(a)}</tr>`).join('')}</table>`:'';}
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
$('#agents').innerHTML=`<table><tr><th>agent</th><th class="n">commands seen</th><th class="n">log reads</th><th class="n">summaries</th><th class="n">passed through</th><th class="n">lines in → out</th><th class="n">tokens before</th><th class="n">after</th><th class="n">saved</th><th class="n">cost saved</th><th>priced as</th></tr>${a.map(x=>`<tr><td>${esc(x.agent)}</td><td class="n">${fmt(x.inspected||0)}</td><td class="n">${fmt(x.rewritten||0)}</td><td class="n">${x.calls-x.passthrough}</td><td class="n">${x.passthrough}</td><td class="n">${fmt(x.lines_in)} → ${fmt(x.lines_out)}</td><td class="n">${fmt(x.tok_in)}</td><td class="n">${fmt(x.tok_out)}</td><td class="n">${x.tok_in?Math.round((1-x.tok_out/x.tok_in)*100):0}%</td><td class="n">$${(x.saved_cost||0).toFixed(4)}${x.unpriced?` <span class="muted" title="${x.unpriced} summaries could not be priced">?</span>`:''}</td><td>${(x.priced_as||[]).map(m=>`<code>${esc(m)}</code>`).join(' ')||'<span class="muted">—</span>'}</td></tr>`).join('')}</table>`;
const ri=(data.inspect&&data.inspect.recent)||[];$('#inspections').innerHTML=ri.length?`<table><tr><th>time (UTC)</th><th>agent</th><th>decision</th><th>command</th></tr>${ri.map(r=>`<tr><td>${esc(r.ts.slice(0,19).replace('T',' '))}</td><td>${esc(r.agent)}</td><td>${esc(r.decision)}</td><td><code>${esc(r.cmd.slice(0,110))}</code></td></tr>`).join('')}</table>`:'<div class="empty">no hook activity recorded (set LOGSUM_INSPECT_LOGS for the service)</div>';}
function recent(){const rs=data.recent;if(!rs.length){$('#recent').innerHTML='<div class="empty">nothing recorded yet</div>';return;}
$('#recent').innerHTML=`<table><tr><th>time</th><th>agent</th><th>command</th><th class="n">lines</th><th class="n">tokens</th><th class="n">saved</th><th>read by</th><th class="n">cost saved</th><th class="n">ms</th></tr>${rs.map(r=>{const p=r.passthrough;const howTag={recorded:'',"opencode-session":'',"opencode-db":' <span class="muted" title="matched to the next OpenCode assistant message in time; the plugin now records the session id, which is exact">(nearest)</span>',fallback:' <span class="muted" title="fallback model from the selector above">(fallback)</span>',unknown:''}[r.model_how||'unknown']||'';return `<tr><td>${esc(r.ts.slice(0,19).replace('T',' '))}</td><td>${esc(r.agent)}</td><td><code>${esc((r.cmd||'').slice(0,80))}</code>${p?' <span class="muted">(passthrough)</span>':(r.top&&r.top.length?`<details><summary>${r.templates} templates</summary><div class="tpl">${r.top.map(([c,t])=>`<div><b>${fmt(c)}×</b><span>${wild(t)}</span></div>`).join('')}</div></details>`:'')}</td><td class="n">${fmt(r.lines_in)} → ${fmt(r.lines_out)}</td><td class="n">${fmt(r.tok_in)} → ${fmt(r.tok_out)}</td><td class="n">${p?'—':Math.round((1-r.tok_out/Math.max(1,r.tok_in))*100)+'%'}</td><td>${p?'':(r.model?`<code>${esc(r.model)}</code>${howTag}`:'<span class="muted">unknown</span>')}</td><td class="n">${p||r.saved_cost==null?'—':'$'+r.saved_cost.toFixed(4)}</td><td class="n">${r.ms??''}</td></tr>`}).join('')}</table>`;}
$('#days').addEventListener('change',()=>{try{localStorage.setItem('logsum.days',$('#days').value)}catch{}load();});
$('#ccmodel').addEventListener('change',()=>{ccModel=$('#ccmodel').value;try{localStorage.setItem('logsum.ccmodel',ccModel)}catch{}load();});
$('#refresh').addEventListener('click',load);
$('#tableToggle').addEventListener('click',()=>{const t=$('#daytable');t.hidden=!t.hidden;$('#chart').hidden=!t.hidden;$('#tableToggle').textContent=t.hidden?'Show as table':'Show as chart';});
load();setInterval(load,15000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/stats":
            q = parse_qs(u.query)
            days = max(1, min(365, int(q.get("days", ["14"])[0])))
            # ?agent_models=claude-code:anthropic/claude-sonnet-5,other-agent:openai/gpt-5.6-luna
            am = {}
            for pair in q.get("agent_models", [""])[0].split(","):
                if ":" in pair:
                    a, m = pair.split(":", 1)
                    am[a.strip()] = m.strip()
            body = json.dumps(aggregate(days, am)).encode()
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
