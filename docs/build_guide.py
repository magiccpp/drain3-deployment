"""Render docs/drain3-opencode-guide.html from guide_template.html, embedding the real source files escaped."""
import html
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
tpl = (HERE / "guide_template.html").read_text(encoding="utf-8")
files = {
    "LOGSUM_PY": ROOT / "logsum.py",
    "LOGSUM_STATS_PY": ROOT / "logsum_stats.py",
    "OPENCODE_PLUGIN_JS": ROOT / "opencode-logsum.js",
}
for key, path in files.items():
    src = path.read_text(encoding="utf-8").rstrip("\n")
    tpl = tpl.replace("{{" + key + "}}", html.escape(src, quote=False))
out = HERE / "drain3-opencode-guide.html"
out.write_text(tpl, encoding="utf-8")
print(f"wrote {out} ({len(tpl):,} chars)")
