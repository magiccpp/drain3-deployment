"""logsum server: Drain3 summarizer as a long-lived HTTP service, plus the stats dashboard.

    POST /summarize        body = raw log (utf-8); headers X-Logsum-Agent, X-Logsum-Cmd-B64 (optional)
                           -> text/plain summary (or the input unchanged when it is short)
    GET  /health           -> {"status":"ok"}
    GET  /, /api/stats     -> the dashboard (see logsum_stats.py)

Keeping the process alive avoids a Python start plus tiktoken load on every agent call
(about 200 ms locally) and makes the container the single place that owns the stats file.
"""
import argparse
import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse

import logsum
import logsum_stats


class Handler(logsum_stats.Handler):
    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._send(200, "application/json", json.dumps({"status": "ok", "stats_file": str(logsum.STATS_PATH)}).encode())
            return
        super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/summarize":
            self._send(404, "text/plain", b"not found")
            return
        t0 = time.perf_counter()
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8", "replace").lstrip("﻿")
        agent = self.headers.get("X-Logsum-Agent", "unknown")
        cmd_b64 = self.headers.get("X-Logsum-Cmd-B64", "")
        lines = raw.splitlines()
        try:
            if len(lines) <= logsum.PASSTHROUGH_LINES:
                out, meta = raw, {"passthrough": True, "templates": 0, "rare_lines": 0, "top": []}
            else:
                out, meta = logsum.summarize(lines)
                meta["passthrough"] = False
        except Exception as e:  # never lose the log because the summarizer broke
            out, meta = f"[logsum failed: {e!r}; raw output follows]\n" + raw, {"passthrough": True, "templates": 0, "rare_lines": 0, "top": [], "error": repr(e)}
        meta["ms"] = round((time.perf_counter() - t0) * 1000)
        self._send(200, "text/plain; charset=utf-8", out.encode("utf-8"))
        # record after responding; the client never waits for token counting
        threading.Thread(target=logsum.record_stats, args=(raw, out, meta), kwargs={"agent": agent, "cmd_b64": cmd_b64}, daemon=True).start()


def main():
    ap = argparse.ArgumentParser(description="logsum summarizer + dashboard service")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    logsum.count_tokens("warm up")  # load tiktoken once, before the first request
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"logsum server: http://{a.host}:{a.port}  stats={logsum.STATS_PATH}  inspect={[str(p) for p in logsum_stats.INSPECT_LOGS]}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
