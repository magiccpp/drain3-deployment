"""Benchmark LLMLingua-2 on the local GPU: throughput (tokens/s) and compression ratio.

Run from WSL:  uv run --project ~/lingua-bench python /mnt/c/claude/lingua-bench/bench.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
import tiktoken
import torch

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus"
RESULTS = HERE / "results"
CORPUS.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)

UA = {"User-Agent": "lingua-bench/0.1 (local benchmark; contact: none)"}
enc = tiktoken.get_encoding("cl100k_base")  # proxy for a modern LLM tokenizer


def ntok(s: str) -> int:
    return len(enc.encode(s, disallowed_special=()))


# --------------------------------------------------------------------------- corpus
def fetch(name: str, url: str, extract=None) -> str | None:
    path = CORPUS / f"{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        text = extract(r) if extract else r.text
        path.write_text(text, encoding="utf-8")
        return text
    except Exception as e:  # noqa: BLE001
        print(f"[corpus] failed to fetch {name}: {e}", file=sys.stderr)
        return None


def wiki(title: str) -> str | None:
    url = ("https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1"
           f"&format=json&redirects=1&titles={title}")
    return fetch(
        f"wiki_{title}", url,
        extract=lambda r: next(iter(r.json()["query"]["pages"].values()))["extract"],
    )


def synthetic_log(n_lines: int = 800) -> str:
    import random
    random.seed(0)
    comps = ["nginx", "kube-proxy", "etcd", "scheduler", "api-server", "sshd", "systemd"]
    msgs = [
        "connection from {ip}:{port} accepted",
        "request GET /api/v1/pods latency={ms}ms status=200",
        "leader election: renewing lease for node-{n}",
        "warning: disk usage on /var/lib at {pct}% (threshold 85%)",
        "reconciling deployment default/web-{n}: 3 replicas ready",
        "TLS handshake error from {ip}:{port}: EOF",
        "started session {n} of user deploy",
        "health check passed for backend-{n} in {ms}ms",
    ]
    out = []
    for i in range(n_lines):
        t = f"2026-09-06T10:{(i // 60) % 60:02d}:{i % 60:02d}Z"
        m = random.choice(msgs).format(
            ip=f"10.0.{random.randint(0, 255)}.{random.randint(1, 254)}",
            port=random.randint(1024, 65535), ms=random.randint(1, 900),
            n=random.randint(1, 40), pct=random.randint(60, 99))
        out.append(f"{t} {random.choice(comps)}[{random.randint(100, 9999)}]: {m}")
    return "\n".join(out)


def build_corpus() -> dict[str, str]:
    docs: dict[str, str] = {}
    readme = fetch("llmlingua_readme",
                   "https://raw.githubusercontent.com/microsoft/LLMLingua/main/README.md")
    if readme:
        docs["docs/markdown (LLMLingua README)"] = readme
    for t in ["Transformer_(deep_learning_architecture)", "Large_language_model",
              "Graphics_processing_unit", "Attention_(machine_learning)"]:
        w = wiki(t)
        if w:
            docs[f"prose (Wikipedia: {t})"] = w
    docs["logs (synthetic server log)"] = synthetic_log()
    # a real Python source file: the LLMLingua implementation itself
    import llmlingua
    src = Path(llmlingua.__file__).parent / "prompt_compressor.py"
    docs["code (llmlingua/prompt_compressor.py)"] = src.read_text(encoding="utf-8")[:40000]
    # long document for sustained throughput: all wikipedia articles concatenated
    long = "\n\n".join(v for k, v in docs.items() if k.startswith("prose"))
    if long:
        docs["long prose (all Wikipedia articles concatenated)"] = long
    return docs


# --------------------------------------------------------------------------- bench
FORCE_TOKENS = ["\n", ".", "?", "!", ",", ":", ";"]
RATES = [0.33, 0.5, 0.7]
MODELS = [
    "microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
    "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
]


def bench_model(model_name: str, docs: dict[str, str]) -> list[dict]:
    from llmlingua import PromptCompressor

    print(f"\n=== {model_name} ===", flush=True)
    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    comp = PromptCompressor(model_name=model_name, use_llmlingua2=True, device_map="cuda")
    load_s = time.perf_counter() - t0
    n_params = sum(p.numel() for p in comp.model.parameters()) / 1e6
    print(f"loaded in {load_s:.1f}s, {n_params:.0f}M params, dtype={next(comp.model.parameters()).dtype}")

    # warm-up (CUDA kernels, tokenizer caches)
    warm = next(iter(docs.values()))[:3000]
    for _ in range(2):
        comp.compress_prompt(warm, rate=0.5, force_tokens=FORCE_TOKENS)
    torch.cuda.synchronize()

    rows = []
    for doc_name, text in docs.items():
        for rate in RATES:
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            res = comp.compress_prompt(text, rate=rate, force_tokens=FORCE_TOKENS)
            torch.cuda.synchronize()
            dt = time.perf_counter() - t0
            before, after = ntok(text), ntok(res["compressed_prompt"])
            row = {
                "model": model_name.split("/")[-1],
                "doc": doc_name,
                "target_rate": rate,
                "cl100k_before": before,
                "cl100k_after": after,
                "cl100k_kept": after / before,
                "lingua_before": res["origin_tokens"],
                "lingua_after": res["compressed_tokens"],
                "seconds": dt,
                "in_tok_per_s": before / dt,
                "compressed": res["compressed_prompt"],
            }
            rows.append(row)
            print(f"{doc_name[:52]:52s} rate={rate:.2f}  {before:6d} -> {after:6d} tok "
                  f"(kept {after / before:5.1%})  {dt:6.2f}s  {before / dt:8.0f} tok/s", flush=True)

    peak = torch.cuda.max_memory_allocated() / 2**20
    print(f"peak GPU memory: {peak:.0f} MiB")
    for r in rows:
        r["peak_mib"] = peak
        r["load_s"] = load_s
        r["params_M"] = n_params
    del comp
    torch.cuda.empty_cache()
    return rows


def main() -> None:
    print("GPU:", torch.cuda.get_device_name(0), "| torch", torch.__version__, "| cuda", torch.version.cuda)
    docs = build_corpus()
    print("\ncorpus:")
    for k, v in docs.items():
        print(f"  {k:60s} {ntok(v):7d} cl100k tokens")

    all_rows: list[dict] = []
    for m in MODELS:
        all_rows += bench_model(m, docs)

    (RESULTS / "results.json").write_text(json.dumps(all_rows, indent=1), encoding="utf-8")

    # markdown summary (without the compressed text)
    lines = ["| model | document | target rate | tokens before | tokens after | kept | seconds | input tok/s |",
             "|---|---|---|---|---|---|---|---|"]
    for r in all_rows:
        lines.append(f"| {r['model'].replace('llmlingua-2-', '').replace('-meetingbank', '')} | {r['doc']} | "
                     f"{r['target_rate']:.2f} | {r['cl100k_before']} | {r['cl100k_after']} | "
                     f"{r['cl100k_kept']:.1%} | {r['seconds']:.2f} | {r['in_tok_per_s']:.0f} |")
    (RESULTS / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    # before/after excerpts for eyeballing quality
    ex = []
    for r in all_rows:
        if r["model"].startswith("llmlingua-2-xlm") and r["target_rate"] == 0.5 \
                and r["doc"].startswith(("prose (Wikipedia: Transformer", "code", "logs", "docs")):
            src = docs[r["doc"]]
            ex.append(f"## {r['doc']} @ rate 0.5\n\n### original (first 1200 chars)\n\n```\n{src[:1200]}\n```\n\n"
                      f"### compressed (first 1200 chars)\n\n```\n{r['compressed'][:1200]}\n```\n")
    (RESULTS / "excerpts.md").write_text("\n".join(ex), encoding="utf-8")
    print("\nwrote", RESULTS / "results.json", RESULTS / "summary.md", RESULTS / "excerpts.md")


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "true")
    main()
