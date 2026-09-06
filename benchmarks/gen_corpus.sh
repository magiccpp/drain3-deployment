#!/usr/bin/env bash
# Generate realistic coding-agent tool outputs (raw) and their RTK-filtered equivalents.
# Runs inside WSL. Output: /mnt/c/claude/lingua-bench/toolout/<name>.{raw,rtk}.txt + manifest.tsv
set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"
export TERM=dumb NO_COLOR=1 PY_COLORS=0 COLUMNS=120
unset FORCE_COLOR CLICOLOR_FORCE
OUT=/mnt/c/claude/lingua-bench/toolout
REPO=$HOME/bench-repos/click
mkdir -p "$OUT"
: > "$OUT/manifest.tsv"

cd "$REPO"
git checkout -q -- . 2>/dev/null || true

# ---- inject realistic breakage so tests fail and linters complain ----------
# 1) break help formatting -> many pytest failures with diffs
if grep -q '"Usage:"' src/click/formatting.py; then
  sed -i 's/"Usage:"/"Usag:"/' src/click/formatting.py
elif grep -q '"Usage:"' src/click/core.py; then
  sed -i 's/"Usage:"/"Usag:"/' src/click/core.py
fi
# 2) a real bug: off-by-one in terminal width handling used by many tests
sed -i '0,/^import /s//import os, sys, json  # noqa-bait\nimport /' src/click/utils.py
# 3) ruff bait: unused imports + long line + bad comparison
cat >> src/click/utils.py <<'EOF'


def _bench_bait(x, y):
    unused_variable = 42
    if x == None:
        return "this is a deliberately very long line to trigger the ruff line-length rule E501 in the benchmark corpus and nothing else"
    return y
EOF
# 4) untracked + modified files for git status
echo "scratch" > notes.txt
mkdir -p tmpdir && echo "x" > tmpdir/a.py && echo "y" > tmpdir/b.py
echo "# bench change" >> README.md

# make sure the project env exists (pytest comes from click's dev group)
uv sync -q --all-groups 2>/dev/null || uv sync -q 2>/dev/null || true

run_pair () {
  # $1 = name, $2 = raw command (as an agent would type it)
  local name="$1" cmd="$2"
  local rewritten
  # `rtk hook check` is the dry-run of the Claude Code PreToolUse hook: exit 0, rewritten command on stdout
  rewritten=$(rtk hook check "$cmd" 2>/dev/null | head -1)
  [[ "$rewritten" == rtk* ]] || rewritten=""
  echo "[$name] raw: $cmd" >&2
  bash -c "$cmd" > "$OUT/$name.raw.txt" 2>&1
  local raw_exit=$?
  if [ -n "$rewritten" ]; then
    echo "[$name] rtk: $rewritten" >&2
    bash -c "$rewritten" > "$OUT/$name.rtk.txt" 2>&1
  else
    echo "[$name] rtk: (no rewrite)" >&2
    echo "(rtk has no rewrite for this command)" > "$OUT/$name.rtk.txt"
  fi
  printf '%s\t%s\t%s\t%s\n' "$name" "$cmd" "$rewritten" "$raw_exit" >> "$OUT/manifest.tsv"
}

run_pair pytest_fail   "uv run -q pytest tests -q -p no:cacheprovider"
run_pair pytest_std    "uv run -q pytest tests -p no:cacheprovider"
run_pair pytest_verb   "uv run -q pytest tests/test_basic.py tests/test_formatting.py -v -p no:cacheprovider"
run_pair ruff          "uv run ruff check src/click --no-cache"
run_pair ruff_concise  "uv run ruff check src/click --no-cache --output-format concise"
run_pair mypy          "uv run mypy src/click/utils.py src/click/formatting.py --no-color-output"
run_pair git_status    "git status"
run_pair git_diff      "git diff"
run_pair git_log       "git log --oneline -40"
run_pair git_log_full  "git log -15 --stat"
run_pair grep_def      "grep -rn 'def ' src/click/"
run_pair grep_import   "grep -rnE '^(from|import) ' src/click/"
run_pair ls_la         "ls -la src/click"
run_pair find_py       "find . -name '*.py' -not -path './.venv/*'"
run_pair read_core     "cat src/click/core.py"
run_pair pip_list      "uv pip list"
# synthetic but realistic server log (same generator as bench.py, written to a file)
uv run --project "$HOME/lingua-bench" python - <<'EOF' > /mnt/c/claude/lingua-bench/corpus/syslog.txt
import random
random.seed(0)
comps = ["nginx", "kube-proxy", "etcd", "scheduler", "api-server", "sshd", "systemd"]
msgs = ["connection from {ip}:{port} accepted",
        "request GET /api/v1/pods latency={ms}ms status=200",
        "leader election: renewing lease for node-{n}",
        "warning: disk usage on /var/lib at {pct}% (threshold 85%)",
        "reconciling deployment default/web-{n}: 3 replicas ready",
        "TLS handshake error from {ip}:{port}: EOF",
        "started session {n} of user deploy",
        "health check passed for backend-{n} in {ms}ms",
        "ERROR failed to pull image registry.local/app:{n}: manifest unknown"]
for i in range(800):
    t = f"2026-09-06T10:{(i // 60) % 60:02d}:{i % 60:02d}Z"
    m = random.choice(msgs).format(ip=f"10.0.{random.randint(0, 255)}.{random.randint(1, 254)}",
        port=random.randint(1024, 65535), ms=random.randint(1, 900), n=random.randint(1, 40), pct=random.randint(60, 99))
    print(f"{t} {random.choice(comps)}[{random.randint(100, 9999)}]: {m}")
EOF
run_pair syslog        "cat /mnt/c/claude/lingua-bench/corpus/syslog.txt"
run_pair syslog_tail   "tail -n 200 /mnt/c/claude/lingua-bench/corpus/syslog.txt"

# restore the repo
git checkout -q -- . ; rm -rf notes.txt tmpdir
echo CORPUS-DONE
