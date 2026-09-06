"""Compare RTK vs Tamp on real coding-agent tool outputs: token reduction and information preservation.

Run (WSL):  TAMP_JS=$(npm root -g)/@sliday/tamp/bin/tamp.js uv run --with requests python compare.py
Expects: toolout/<name>.raw.txt and toolout/<name>.rtk.txt from gen_corpus.sh, Tamp installed globally
via npm, and (optionally) the LLMLingua sidecar on http://127.0.0.1:8788.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests
import tiktoken

HERE = Path(__file__).resolve().parent
TOOLOUT = HERE / "toolout"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
enc = tiktoken.get_encoding("cl100k_base")
MOCK_PORT, TAMP_PORT = 7799, 7778
TAMP_LEVELS = [4, 5, 9]
CORE_PATH = "/home/ken/bench-repos/click/src/click/core.py"


def _find_tamp_js() -> Path:
    if os.environ.get("TAMP_JS"):
        return Path(os.environ["TAMP_JS"])
    root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()
    return Path(root) / "@sliday/tamp/bin/tamp.js"


TAMP_JS = _find_tamp_js()


def ntok(s: str) -> int:
    return len(enc.encode(s, disallowed_special=()))


# ------------------------------------------------------------------ mock upstream
class Recorder(BaseHTTPRequestHandler):
    last_body: dict | None = None
    event = threading.Event()

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(n)
        try:
            Recorder.last_body = json.loads(raw)
        except Exception:
            Recorder.last_body = {"_raw": raw.decode("utf-8", "replace")}
        Recorder.event.set()
        resp = json.dumps({"id": "msg_mock", "type": "message", "role": "assistant", "model": "mock",
                           "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                           "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):  # silence
        pass


def start_mock():
    srv = HTTPServer(("127.0.0.1", MOCK_PORT), Recorder)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------------ tamp lifecycle
def start_tamp(level: int, log_path: Path) -> subprocess.Popen:
    env = dict(os.environ, TAMP_LEVEL=str(level), TAMP_PORT=str(TAMP_PORT),
               TAMP_UPSTREAM=f"http://127.0.0.1:{MOCK_PORT}",
               TAMP_LLMLINGUA_URL="http://127.0.0.1:8788", TAMP_CACHE_SAFE="true", NO_COLOR="1")
    logf = open(log_path, "w", encoding="utf-8")
    p = subprocess.Popen(["node", str(TAMP_JS), "-y", "--force", "--level", str(level)],
                         env=env, stdout=logf, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            h = requests.get(f"http://127.0.0.1:{TAMP_PORT}/health", timeout=1).json()
            print(f"  tamp L{level} up: stages={h.get('stages')} sidecar={h.get('sidecar')}", flush=True)
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("tamp did not start; see " + str(log_path))


TASK = "Run the tests and fix whatever fails. Report the exact failing tests."


def turn(tool_use: dict, raw: str, tid: str) -> list[dict]:
    return [
        {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": tool_use["name"],
                                           "input": tool_use["input"]}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid,
                                      "content": [{"type": "text", "text": raw}]}]},
    ]


def send(messages: list[dict]) -> dict:
    body = {"model": "claude-sonnet-5", "max_tokens": 64, "stream": False,
            "system": "You are a coding agent.", "messages": messages}
    Recorder.event.clear()
    Recorder.last_body = None
    r = requests.post(f"http://127.0.0.1:{TAMP_PORT}/v1/messages", json=body,
                      headers={"x-api-key": "sk-mock", "anthropic-version": "2023-06-01"}, timeout=180)
    if not Recorder.event.wait(180):
        raise RuntimeError(f"upstream never received request (status {r.status_code})")
    return Recorder.last_body


def last_tool_result_text(fwd: dict) -> str:
    for msg in reversed(fwd["messages"]):
        if msg["role"] != "user" or not isinstance(msg["content"], list):
            continue
        for block in msg["content"]:
            if block.get("type") == "tool_result":
                c = block.get("content")
                if isinstance(c, str):
                    return c
                return "\n".join(p.get("text", "") for p in c if p.get("type") == "text")
    raise RuntimeError("no tool_result in forwarded body")


def through_tamp(tool_use: dict, raw: str) -> str:
    fwd = send([{"role": "user", "content": TASK}] + turn(tool_use, raw, "toolu_01"))
    return last_tool_result_text(fwd)


def reread_through_tamp(numbered_a: str, numbered_b: str) -> str:
    """Two requests in one session: Read core.py, then Read it again after a small edit."""
    read = {"name": "Read", "input": {"file_path": CORE_PATH}}
    base = [{"role": "user", "content": TASK}] + turn(read, numbered_a, "toolu_r1")
    send(base)  # primes tamp's read cache
    msgs = base + [{"role": "assistant", "content": [{"type": "text", "text": "I edited the file; re-reading."}]},
                   {"role": "user", "content": "ok"}] + turn(read, numbered_b, "toolu_r2")
    return last_tool_result_text(send(msgs))


# ------------------------------------------------------------------ facts (what must survive)
def facts_for(name: str, raw: str) -> list[tuple[str, list[str]]]:
    """Return [(label, [alternative substrings]) ...]; a fact is kept if ANY alternative appears."""
    f: list[tuple[str, list[str]]] = []
    if name.startswith("pytest"):
        for m in re.finditer(r"^FAILED (tests/\w+\.py::[\w\[\]\-\.]+)", raw, re.M):
            tid = m.group(1)
            f.append((f"failed test {tid}", [tid, tid.split("::", 1)[1]]))
        for m in set(re.finditer(r"^E\s+(\w+(?:Error|Exception|Failed)\b[^\n]{0,60})", raw, re.M)):
            f.append((f"error line {m.group(1)[:40]}", [m.group(1)[:40].strip()]))
        m = re.search(r"(\d+) failed", raw)
        if m:
            n = m.group(1)
            f.append((f"fail count {n}", [f"{n} failed", f"{n} fail", f"failed: {n}", f"FAIL {n}", f"{n}F",
                                          f"x{n}", f"{n} ✗", f"({n})", f"✗ {n}", f"{n} FAILED"]))
    elif name.startswith("ruff"):
        for m in re.finditer(r"^(\S+?\.py):(\d+):(\d+): (\w+) ", raw, re.M):
            path, line, _, code = m.groups()
            f.append((f"{code} at {Path(path).name}:{line}", [f"{Path(path).name}:{line}", f"{line}:"]))
            f.append((f"rule {code}", [code]))
        for m in re.finditer(r"^(\w\d{3,4}) (.{10,40})\n\s+--> (\S+?):(\d+):", raw, re.M):  # full format
            code, msg, path, line = m.groups()
            f.append((f"{code} at {Path(path).name}:{line}", [f"{Path(path).name}:{line}", f":{line}:"]))
            f.append((f"rule {code}", [code]))
    elif name == "mypy":
        for m in re.finditer(r"^(\S+?):(\d+): error: ([^\n]{0,40})", raw, re.M):
            f.append((f"mypy {Path(m.group(1)).name}:{m.group(2)}", [f":{m.group(2)}", m.group(3)[:25]]))
    elif name == "git_status":
        for m in re.finditer(r"^\s+(?:modified:\s+)?(\S+)$", raw, re.M):
            p = m.group(1)
            if "/" in p or "." in p:
                f.append((f"path {p}", [p, p.rstrip("/")]))
    elif name == "git_diff":
        for m in re.finditer(r"^diff --git a/(\S+)", raw, re.M):
            f.append((f"file {m.group(1)}", [m.group(1), Path(m.group(1)).name]))
        for m in re.finditer(r"^\+([^+\n][^\n]{3,})", raw, re.M):
            f.append((f"added '{m.group(1).strip()[:30]}'", [m.group(1).strip()[:30]]))
    elif name.startswith("git_log"):
        for m in re.finditer(r"^(?:commit )?([0-9a-f]{7,40})\b[ \n]", raw, re.M):
            f.append((f"hash {m.group(1)[:7]}", [m.group(1)[:7]]))
        for m in re.finditer(r"^[0-9a-f]{7,} (.{10,40})", raw, re.M):
            f.append((f"subject {m.group(1)[:25]}", [m.group(1)[:25]]))
        for m in re.finditer(r"^    (\S.{8,30})", raw, re.M):
            f.append((f"subject {m.group(1)[:25]}", [m.group(1)[:25].strip()]))
    elif name.startswith("grep"):
        for m in re.finditer(r"^(\S+?):(\d+):\s*(.*)$", raw, re.M):
            path, line, content = m.groups()
            f.append((f"{Path(path).name}:{line}", [f"{path}:{line}", f"{Path(path).name}:{line}", f"{line}:"]))
        for m in list(re.finditer(r"def (\w+)\(", raw))[::10]:
            f.append((f"def {m.group(1)}", [m.group(1)]))
    elif name == "ls_la":
        for m in re.finditer(r" (\S+)$", raw, re.M):
            if m.group(1) not in (".", ".."):
                f.append((f"entry {m.group(1)}", [m.group(1)]))
    elif name == "find_py":
        for line in raw.splitlines():
            if line.endswith(".py"):
                f.append((f"path {line}", [line, line[2:] if line.startswith("./") else line, Path(line).name]))
    elif name.startswith("read_core"):
        for m in re.finditer(r"^\s*(?:\d+\t)?\s*def (\w+)\(", raw, re.M):
            f.append((f"def {m.group(1)}", [f"def {m.group(1)}"]))
        for m in re.finditer(r"^\s*(?:\d+\t)?class (\w+)", raw, re.M):
            f.append((f"class {m.group(1)}", [f"class {m.group(1)}"]))
    elif name == "pip_list":
        for m in re.finditer(r"^([A-Za-z][\w\-\.]+)\s+(\d[\w\.]*)$", raw, re.M):
            f.append((f"{m.group(1)}=={m.group(2)}", [m.group(2)]))
    elif name.startswith("syslog"):
        for m in re.finditer(r"TLS handshake error from ([\d\.]+:\d+)", raw):
            f.append((f"TLS error {m.group(1)}", [m.group(1)]))
        for m in re.finditer(r"disk usage on /var/lib at (\d+)%", raw):
            f.append((f"disk {m.group(1)}%", [f"{m.group(1)}%"]))
        for m in re.finditer(r"ERROR failed to pull image (\S+)", raw):
            f.append((f"pull fail {m.group(1)}", [m.group(1)]))
    seen, out = set(), []
    for lab, alts in f:
        if lab not in seen:
            seen.add(lab)
            out.append((lab, alts))
    return out


def recall(facts, text: str) -> tuple[float, list[str]]:
    if not facts:
        return float("nan"), []
    lost = [lab for lab, alts in facts if not any(a and a in text for a in alts)]
    return 1 - len(lost) / len(facts), lost


def numbered(text: str) -> str:
    """Claude Code Read-tool style: line number, tab, content."""
    return "\n".join(f"{i + 1:6d}\t{l}" for i, l in enumerate(text.splitlines()))


# ------------------------------------------------------------------ main
def main():
    manifest = {}
    for line in (TOOLOUT / "manifest.tsv").read_text(encoding="utf-8").splitlines():
        name, cmd, rewritten, code = line.split("\t")
        manifest[name] = (cmd, rewritten, code)

    samples: dict[str, dict] = {}
    for name, (cmd, rewritten, code) in manifest.items():
        raw = (TOOLOUT / f"{name}.raw.txt").read_text(encoding="utf-8", errors="replace")
        rtk = (TOOLOUT / f"{name}.rtk.txt").read_text(encoding="utf-8", errors="replace")
        if len(raw) < 100:
            print(f"skip {name}: raw output too small ({len(raw)} chars) -> tool probably missing")
            continue
        if not rewritten:
            rtk = raw  # hook leaves the command alone -> the agent sees the raw output unchanged
        samples[name] = {"cmd": cmd, "rtk_cmd": rewritten, "raw": raw, "rtk": rtk,
                         "tool_use": {"name": "Bash", "input": {"command": cmd}}}

    # Claude Code's Read tool is not a Bash command: RTK never sees it, Tamp does.
    core = samples["read_core"]["raw"]
    core_num = numbered(core)
    samples["read_core_numbered (Read tool)"] = {
        "cmd": "Read core.py", "rtk_cmd": "", "raw": core_num, "rtk": core_num,
        "tool_use": {"name": "Read", "input": {"file_path": CORE_PATH}}}
    # re-read after a 3-line edit (second read of the same file in one session)
    lines = core.splitlines()
    for i in (120, 400, 900):
        if i < len(lines):
            lines[i] = lines[i] + "  # edited"
    core_b_num = numbered("\n".join(lines))

    rows = []
    for name, s in samples.items():
        facts = facts_for(name, s["raw"])
        rec, lost = recall(facts, s["rtk"])
        rows.append({"tool": "rtk", "sample": name, "before": ntok(s["raw"]), "after": ntok(s["rtk"]),
                     "recall": rec, "n_facts": len(facts), "lost": lost, "out": s["rtk"]})
    rows.append({"tool": "rtk", "sample": "reread_core_after_edit (Read tool)", "before": ntok(core_b_num),
                 "after": ntok(core_b_num), "recall": float("nan"), "n_facts": 0, "lost": [], "out": core_b_num})

    start_mock()
    for level in TAMP_LEVELS:
        p = start_tamp(level, RESULTS / f"tamp_L{level}.log")
        try:
            for name, s in samples.items():
                out = through_tamp(s["tool_use"], s["raw"])
                facts = facts_for(name, s["raw"])
                rec, lost = recall(facts, out)
                rows.append({"tool": f"tamp-L{level}", "sample": name, "before": ntok(s["raw"]), "after": ntok(out),
                             "recall": rec, "n_facts": len(facts), "lost": lost, "out": out})
                print(f"  L{level} {name[:30]:30s} {ntok(s['raw']):6d} -> {ntok(out):6d}  recall {rec:.2f}", flush=True)
            out = reread_through_tamp(core_num, core_b_num)
            rows.append({"tool": f"tamp-L{level}", "sample": "reread_core_after_edit (Read tool)",
                         "before": ntok(core_b_num), "after": ntok(out), "recall": float("nan"), "n_facts": 0,
                         "lost": [], "out": out})
            print(f"  L{level} {'reread_core_after_edit':30s} {ntok(core_b_num):6d} -> {ntok(out):6d}", flush=True)
        finally:
            p.kill()
            time.sleep(1)

    (RESULTS / "compare.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    # -------- report
    tools = ["rtk"] + [f"tamp-L{l}" for l in TAMP_LEVELS]
    by = {(r["tool"], r["sample"]): r for r in rows}
    names = list(samples) + ["reread_core_after_edit (Read tool)"]
    L = ["# RTK vs Tamp on real tool outputs", "",
         "Tokens = cl100k_base. Recall = share of extracted must-keep facts (failing test ids, error lines, paths, "
         "line numbers, hashes, versions, log errors) still present verbatim in the compressed output. "
         "RTK only touches Bash commands it has a filter for; Tamp sees every tool_result.", "",
         "| sample | raw tokens | " + " | ".join(f"{t} (kept) / recall" for t in tools) + " |",
         "|---|---|" + "---|" * len(tools)]
    tot = {t: [0, 0] for t in tools}
    for name in names:
        raw_t = by[("rtk", name)]["before"]
        cells = []
        for t in tools:
            r = by[(t, name)]
            tot[t][0] += r["before"]; tot[t][1] += r["after"]
            rec = "n/a" if r["recall"] != r["recall"] else f"{r['recall']:.0%}"
            cells.append(f"{r['after']} ({r['after'] / r['before']:.0%}) / {rec}")
        L.append(f"| {name} | {raw_t} | " + " | ".join(cells) + " |")
    L.append("| **total** | " + f"{tot['rtk'][0]} | " + " | ".join(
        f"{tot[t][1]} ({tot[t][1] / tot[t][0]:.0%})" for t in tools) + " |")

    L += ["", "## Lost facts (information that did not survive)", ""]
    for t in tools:
        L.append(f"### {t}")
        for name in names:
            r = by[(t, name)]
            if r["lost"]:
                L.append(f"- **{name}** lost {len(r['lost'])}/{r['n_facts']}: " + "; ".join(r["lost"][:12]) +
                         (" ..." if len(r["lost"]) > 12 else ""))
        L.append("")

    L += ["## Excerpts (first 900 chars)", ""]
    for name in ("pytest_std", "pytest_fail", "ruff_concise", "git_status", "ls_la", "grep_def", "find_py",
                 "reread_core_after_edit (Read tool)"):
        if (("rtk", name)) not in by:
            continue
        cmd = samples.get(name, {}).get("cmd", name)
        L.append(f"### {name}  —  `{cmd}`\n")
        raw_text = samples[name]["raw"] if name in samples else core_b_num
        L.append("**raw**\n```\n" + raw_text[:900] + "\n```\n")
        shown = set()
        for t in tools:
            o = by[(t, name)]["out"]
            key = o.strip()
            if key in shown:
                L.append(f"**{t}**: identical to above\n")
                continue
            shown.add(key)
            L.append(f"**{t}**\n```\n" + o[:900] + "\n```\n")
    (RESULTS / "compare.md").write_text("\n".join(L), encoding="utf-8")
    print("\nwrote", RESULTS / "compare.md")


if __name__ == "__main__":
    main()
