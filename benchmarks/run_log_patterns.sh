#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/lingua-bench"
echo "=== drain3 ==="
uv run --with drain3 python /mnt/c/claude/lingua-bench/log_patterns.py /mnt/c/claude/lingua-bench/corpus/syslog.txt 2>&1 | grep -vE 'Warning|warn:'
echo; echo "=== rtk log ==="
rtk log --help | head -20
echo "--- rtk log on the file:"
rtk log /mnt/c/claude/lingua-bench/corpus/syslog.txt > /tmp/rtk_log.txt 2>&1; head -30 /tmp/rtk_log.txt; echo "... ($(wc -l < /tmp/rtk_log.txt) lines, $(wc -c < /tmp/rtk_log.txt) bytes vs $(wc -c < /mnt/c/claude/lingua-bench/corpus/syslog.txt) raw)"
echo "--- rtk log tokens:"; uv run python -c "import tiktoken,sys;e=tiktoken.get_encoding('cl100k_base');print(len(e.encode(open('/tmp/rtk_log.txt').read())))"
