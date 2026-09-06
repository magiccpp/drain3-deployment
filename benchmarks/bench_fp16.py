"""Quick fp16 vs fp32 throughput check for the large LLMLingua-2 model (weights already cached)."""
import time
from pathlib import Path

import tiktoken
import torch
from llmlingua import PromptCompressor

HERE = Path(__file__).resolve().parent
enc = tiktoken.get_encoding("cl100k_base")
text = "\n\n".join(p.read_text(encoding="utf-8") for p in sorted((HERE / "corpus").glob("wiki_*.txt")))
n = len(enc.encode(text))
FORCE = ["\n", ".", "?", "!", ",", ":", ";"]
MODEL = "microsoft/llmlingua-2-xlm-roberta-large-meetingbank"

for dtype in (torch.float32, torch.float16):
    torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    comp = PromptCompressor(MODEL, use_llmlingua2=True, device_map="cuda", model_config={"torch_dtype": dtype})
    load = time.perf_counter() - t0
    comp.compress_prompt(text[:3000], rate=0.5, force_tokens=FORCE)  # warm-up
    torch.cuda.synchronize()
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        res = comp.compress_prompt(text, rate=0.5, force_tokens=FORCE)
        torch.cuda.synchronize()
        times.append(time.perf_counter() - t0)
    best = min(times)
    kept = len(enc.encode(res["compressed_prompt"])) / n
    print(f"{str(dtype):14s} warm-load {load:5.1f}s  {n} tok in {best:.2f}s = {n / best:8.0f} tok/s  "
          f"kept {kept:.1%}  peak {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB  "
          f"param dtype {next(comp.model.parameters()).dtype}", flush=True)
    del comp
