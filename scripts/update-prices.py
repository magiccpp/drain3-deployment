"""Refresh logsum/prices.json from models.dev (list prices per 1M tokens) for the canonical providers.

The dashboard uses this table to price messages that OpenCode recorded with cost 0, which happens
for custom or proxy providers (e.g. "my-gateway/gpt-5.6-luna"). Matching is by exact provider/model
first, then by model id under a canonical provider, so a proxy of gpt-5.6-luna gets OpenAI's list price.

    python scripts/update-prices.py            # rewrites logsum/prices.json
"""
import json
import sys
import urllib.request
from pathlib import Path

CANONICAL = ["openai", "azure", "anthropic", "google", "xai", "deepseek", "mistral", "moonshotai", "zai"]
OUT = Path(__file__).resolve().parent.parent / "logsum" / "prices.json"

req = urllib.request.Request("https://models.dev/api.json", headers={"User-Agent": "logsum-stats/1.0 (+https://github.com/magiccpp/drain3-deployment)"})
with urllib.request.urlopen(req, timeout=20) as r:
    api = json.load(r)

table = {}
for prov in CANONICAL:
    for mid, m in (api.get(prov, {}).get("models") or {}).items():
        c = m.get("cost") or {}
        if not c or "input" not in c:
            continue
        table[f"{prov}/{mid}"] = {k: float(c[k]) for k in ("input", "output", "cache_read", "cache_write") if k in c}
        over = c.get("context_over_200k")
        if over:
            table[f"{prov}/{mid}"]["context_over_200k"] = {k: float(over[k]) for k in ("input", "output", "cache_read", "cache_write") if k in over}
OUT.write_text(json.dumps({"source": "https://models.dev/api.json", "unit": "USD per 1M tokens",
                           "rule": "messages with recorded cost 0 are priced by exact provider/model, else gpt-* under a non-openai vendor -> azure/<model>, else the model id under a canonical provider",
                           "models": table}, indent=1, sort_keys=True), encoding="utf-8")
print(f"wrote {OUT} with {len(table)} priced models", file=sys.stderr)
for k in sorted(table):
    if "gpt-5.6" in k or "claude-haiku-4-5" in k:
        print(k, table[k])
