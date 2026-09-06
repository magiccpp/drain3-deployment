"""logsum: read log lines on stdin, emit a Drain3 template summary that keeps the signal.

Short input (<= PASSTHROUGH_LINES) is echoed unchanged, so wiring this into every
log-reading command is safe. Rare templates and the tail of the log are kept verbatim.

Every call is recorded to a JSONL stats file (default ~/.local/share/logsum/stats.jsonl)
*after* the output has been written and flushed, in a forked child, so the agent never
waits for token counting. Optional env: LOGSUM_AGENT (who called), LOGSUM_CMD_B64
(base64 of the command that produced the log), LOGSUM_STATS (file path), LOGSUM_NOSTATS=1.
"""
import base64
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

PASSTHROUGH_LINES = 40     # below this, summarizing costs more than it saves
RARE_MAX = 3               # templates seen this often or less are printed verbatim (they're the signal)
TAIL_LINES = 10            # always show the most recent lines
MAX_TEMPLATES = 60
SEV = re.compile(r"\b(error|err|warn|warning|fail|failed|fatal|critical|panic|exception|traceback|denied|refused|timeout)\b", re.I)

MASKS = [
    (r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:?\d\d)?", "TS"),
    (r"\b[A-Z][a-z]{2} +\d{1,2} \d\d:\d\d:\d\d\b", "TS"),                 # syslog "Sep  6 10:00:00"
    (r"\b\d\d:\d\d:\d\d(?:[.,]\d+)?\b", "TIME"),
    (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "UUID"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}:\d+\b", "IP:PORT"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "IP"),
    (r"\b0x[0-9a-fA-F]+\b", "HEX"),
    (r"\b[0-9a-f]{12,64}\b", "HASH"),
    (r"\[\d+\]", "[PID]"),
    (r"\b\d+(?:\.\d+)?(?:ms|s|us|µs|ns|KiB|MiB|GiB|KB|MB|GB|B)\b", "NUM+unit"),
    (r"\b\d+%", "NUM%"),
    (r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", "NUM"),
]

STATS_PATH = Path(os.environ.get("LOGSUM_STATS") or Path.home() / ".local/share/logsum/stats.jsonl")


def count_tokens(text: str) -> tuple[int, str]:
    """Exact cl100k count when tiktoken is installed, else a regex estimate (within ~2% on logs)."""
    try:
        import tiktoken
        return len(tiktoken.get_encoding("cl100k_base").encode(text, disallowed_special=())), "tiktoken"
    except Exception:
        return len(re.findall(r"[A-Za-z]+|\d{1,3}|[^\w\s]|_", text)), "estimate"


def record_stats(raw: str, out: str, meta: dict, agent: str | None = None, cmd_b64: str | None = None) -> None:
    """Append one JSON line. CLI mode calls this in a forked child; the server calls it from a thread."""
    if os.environ.get("LOGSUM_NOSTATS"):
        return
    if cmd_b64 is None:
        cmd_b64 = os.environ.get("LOGSUM_CMD_B64", "")
    try:
        cmd = base64.b64decode(cmd_b64).decode("utf-8", "replace") if cmd_b64 else ""
    except Exception:
        cmd = ""
    tok_in, method = count_tokens(raw)
    tok_out, _ = count_tokens(out)
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "agent": agent or os.environ.get("LOGSUM_AGENT", "unknown"),
        "cmd": cmd[:200],
        "lines_in": raw.count("\n") + (1 if raw and not raw.endswith("\n") else 0),
        "lines_out": out.count("\n") + (1 if out and not out.endswith("\n") else 0),
        "chars_in": len(raw), "chars_out": len(out),
        "tok_in": tok_in, "tok_out": tok_out, "tok_method": method,
        **meta,
    }
    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def emit_and_record(raw: str, out: str, meta: dict) -> None:
    sys.stdout.write(out)
    sys.stdout.flush()
    if os.environ.get("LOGSUM_NOSTATS"):
        return
    try:
        pid = os.fork()
    except OSError:
        record_stats(raw, out, meta)   # no fork (unlikely on Linux): record inline
        return
    if pid == 0:
        # child: detach (own session, ignore hangup) so a wrapper like wsl.exe tearing the console down
        # does not kill it, release the pipe so the caller sees EOF at once, then count tokens at leisure
        try:
            import signal
            os.setsid()
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
            os.close(0); os.close(1); os.close(2)
            record_stats(raw, out, meta)
        finally:
            os._exit(0)


def summarize(lines: list[str]) -> tuple[str, dict]:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig

    cfg = TemplateMinerConfig()
    cfg.profiling_enabled = False
    cfg.masking_instructions = [MaskingInstruction(p, n) for p, n in MASKS]
    miner = TemplateMiner(config=cfg)

    members: dict[int, list[int]] = defaultdict(list)   # cluster id -> line numbers (1-based)
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        r = miner.add_log_message(line)
        members[r["cluster_id"]].append(i)

    clusters = sorted(miner.drain.clusters, key=lambda c: -c.size)
    out = [f"[logsum] {len(lines)} lines -> {len(clusters)} templates (Drain3). "
           f"Rare templates and the last {TAIL_LINES} lines are verbatim. "
           f"Add '# nologsum' to the command to see raw output."]

    rare, shown = [], 0
    for c in clusters:
        tmpl = c.get_template()
        idx = members.get(c.cluster_id, [])
        if c.size <= RARE_MAX:
            rare.extend(idx)
            continue
        if shown >= MAX_TEMPLATES:
            out.append(f"  ... {len(clusters) - shown} more templates omitted")
            break
        shown += 1
        span = f"lines {idx[0]}-{idx[-1]}" if idx else ""
        out.append(f"{c.size:5d}x  {tmpl}   ({span})")
        if SEV.search(tmpl):
            per_pos: dict[tuple, set] = defaultdict(set)
            for i in idx:
                params = miner.extract_parameters(tmpl, lines[i - 1], exact_matching=False) or []
                for pos, p in enumerate(params):
                    per_pos[(pos, p.mask_name)].add(p.value)
            for (pos, mask), vals in sorted(per_pos.items()):
                if mask in ("TS", "TIME"):
                    out.append(f"         time {min(vals)} .. {max(vals)}")
                elif mask == "[PID]" or mask == "*" and len(vals) > 12:
                    continue
                elif all(re.fullmatch(r"-?\d+(?:\.\d+)?%?", v) for v in vals):
                    nums = sorted(float(v.rstrip("%")) for v in vals)
                    out.append(f"         {mask}: {len(vals)} distinct, range {nums[0]:g}-{nums[-1]:g}")
                else:
                    sample = ", ".join(sorted(vals)[:6])
                    out.append(f"         {mask}: {len(vals)} distinct, e.g. {sample}{', ...' if len(vals) > 6 else ''}")

    if rare:
        out.append(f"--- {len(rare)} rare lines (template seen <= {RARE_MAX} times) ---")
        out += [f"{i:6d}: {lines[i - 1]}" for i in sorted(rare)[:200]]
        if len(rare) > 200:
            out.append(f"  ... {len(rare) - 200} more rare lines")
    out.append(f"--- last {TAIL_LINES} lines ---")
    out += lines[-TAIL_LINES:]
    meta = {"templates": len(clusters), "rare_lines": len(rare),
            "top": [[c.size, c.get_template()[:160]] for c in clusters[:5]]}
    return "\n".join(out) + "\n", meta


def main() -> None:
    t0 = time.perf_counter()
    data = sys.stdin.buffer.read().decode("utf-8", "replace").lstrip("\ufeff")
    lines = data.splitlines()
    if len(lines) <= PASSTHROUGH_LINES:
        emit_and_record(data, data, {"passthrough": True, "templates": 0, "rare_lines": 0, "top": [],
                                     "ms": round((time.perf_counter() - t0) * 1000)})
        return
    out, meta = summarize(lines)
    meta["passthrough"] = False
    meta["ms"] = round((time.perf_counter() - t0) * 1000)
    emit_and_record(data, out, meta)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never lose the log because the summarizer broke
        sys.stdout.write(f"[logsum failed: {e!r}; raw output follows]\n")
        sys.stdout.flush()
        sys.stdout.write(sys.stdin.read() if not sys.stdin.closed else "")
