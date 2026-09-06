"""Mine repetitive patterns from a log with Drain3 and print a token-cheap summary."""
import re, sys
from collections import defaultdict
import tiktoken
from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

enc = tiktoken.get_encoding("cl100k_base")
path = sys.argv[1]
lines = open(path, encoding="utf-8").read().splitlines()

cfg = TemplateMinerConfig()
cfg.profiling_enabled = False
# mask the usual variable fields so they don't split templates
cfg.masking_instructions = []
from drain3.masking import MaskingInstruction
for pat, name in [(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "TS"), (r"\b\d{1,3}(\.\d{1,3}){3}:\d+\b", "IP:PORT"),
                  (r"\b\d{1,3}(\.\d{1,3}){3}\b", "IP"), (r"\[\d+\]", "[PID]"), (r"\b\d+ms\b", "NUMms"),
                  (r"\b\d+%", "NUM%"), (r"\b\d+\b", "NUM")]:
    cfg.masking_instructions.append(MaskingInstruction(pat, name))
miner = TemplateMiner(config=cfg)

first, last, examples = {}, {}, defaultdict(list)
for i, line in enumerate(lines, 1):
    r = miner.add_log_message(line)
    cid = r["cluster_id"]
    first.setdefault(cid, i); last[cid] = i
    if len(examples[cid]) < 2:
        examples[cid].append(line)

out = [f"{len(lines)} lines -> {len(miner.drain.clusters)} templates"]
for c in sorted(miner.drain.clusters, key=lambda c: -c.size):
    tmpl = c.get_template()
    out.append(f"{c.size:4d}x  {tmpl}   (lines {first[c.cluster_id]}-{last[c.cluster_id]})")
templates_only = "\n".join(out)

# error/warning templates: aggregate the variable parts instead of dumping every line
sev_re = re.compile(r"error|warn|fail|fatal|critical", re.I)
agg = ["\n--- error/warning templates with aggregated parameters ---"]
for c in sorted(miner.drain.clusters, key=lambda c: -c.size):
    tmpl = c.get_template()
    if not sev_re.search(tmpl):
        continue
    members = [l for l in lines if miner.match(l) and miner.match(l).cluster_id == c.cluster_id]
    per_pos = defaultdict(set)
    for l in members:
        for i, p in enumerate(miner.extract_parameters(tmpl, l, exact_matching=False) or []):
            per_pos[(i, p.mask_name)].add(p.value)
    agg.append(f"{c.size}x {tmpl}")
    for (i, mask), vals in sorted(per_pos.items()):
        if mask == "TS":
            agg.append(f"   time: {min(vals)} .. {max(vals)}")
        elif all(re.fullmatch(r"\d+%?", v) for v in vals):
            nums = sorted(int(v.rstrip('%')) for v in vals)
            agg.append(f"   {mask}: {len(vals)} distinct, range {nums[0]}-{nums[-1]}")
        else:
            sample = ", ".join(sorted(vals)[:8])
            agg.append(f"   {mask}: {len(vals)} distinct e.g. {sample}{', ...' if len(vals) > 8 else ''}")
verbatim = [l for l in lines if sev_re.search(l)]
summary = templates_only + "\n" + "\n".join(agg)
print(summary)
print(f"\n[tokens] raw={len(enc.encode(open(path, encoding='utf-8').read()))} "
      f"templates-only={len(enc.encode(templates_only))} templates+aggregated-errors={len(enc.encode(summary))} "
      f"templates+all-{len(verbatim)}-error-lines-verbatim={len(enc.encode(templates_only + chr(10).join(verbatim)))}")
