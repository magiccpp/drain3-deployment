# drain3-deployment

Cut the tokens a coding agent spends on log output. `logsum` runs the
[Drain3](https://github.com/logpai/Drain3) template miner over any log a tool
returns and hands the model templates with counts instead of the raw lines.
Hooks for **OpenCode** and **Claude Code** wire it in transparently, and a small
dashboard shows what it saved.

Measured on an 800-line service log: 800 lines become 28, 25,827 tokens become
875, in about 0.2 s on a CPU. Rare lines and the tail of the log stay verbatim,
so nothing an agent needs to act on is lost.

```
2026-09-06T10:00:23Z scheduler[6815]: TLS handshake error from 10.0.128.31:40135: EOF
2026-09-06T10:00:28Z sshd[9408]: TLS handshake error from 10.0.81.62:15644: EOF
... 85 more
```
becomes
```
   87x  <TS> <*> TLS handshake error from <IP:PORT>: EOF   (lines 24-797)
         time 2026-09-06T10:00:23Z .. 2026-09-06T10:13:16Z
         IP:PORT: 87 distinct, e.g. 10.0.1.10:4117, 10.0.10.12:13612, ...
```

## Layout

| path | what |
|---|---|
| `logsum/logsum.py` | the summarizer: stdin log in, Drain3 summary out; records each call to `~/.local/share/logsum/stats.jsonl` |
| `logsum/logsum_stats.py` | dashboard server (stdlib only): `http://localhost:8765`, JSON at `/api/stats` |
| `logsum/server.py` | the container entrypoint: `POST /summarize` (warm Drain3 + tiktoken) plus the dashboard |
| `logsum/Dockerfile`, `docker-compose.yml` | the image (python:3.12-slim, non-root, tiktoken table baked in) and the service definition |
| `logsum/client/logsum` | host-side client with local and passthrough fallback |
| `logsum/logsum-stats.service` | systemd user unit for the no-Docker install |
| `opencode/logsum.js` | OpenCode plugin (`tool.execute.after`): replaces log output with the summary |
| `opencode/opencode.jsonc` | OpenCode model config: Terra main, Luna for explore/general/titles, plus a `logs` subagent |
| `claude-code/logsum-hook.js` | Claude Code PreToolUse hook for Windows: pipes log commands through `logsum` in WSL2 |
| `claude-code/install.ps1` | installs the hook and merges it into `~/.claude/settings.json` |
| `scripts/docker-up.sh`, `scripts/docker-down.sh`, `scripts/install-compose.sh` | container lifecycle |
| `scripts/install.sh` | no-Docker installer: uv env, wrappers, dashboard service, self-test |
| `scripts/install-opencode-plugin.sh`, `scripts/test-opencode.sh` | plugin install and a headless end-to-end test |
| `docs/` | the full guide (`drain3-opencode-guide.html`, built from `guide_template.html` by `build_guide.py`) |
| `benchmarks/` | how this was chosen: LLMLingua-2 on GPU, RTK vs Tamp on real tool outputs, Drain3 vs line dedup |

## Install with Docker (recommended)

One container runs the summarizer as a warm HTTP service and the dashboard.
Stats live in a named volume; the agents' audit logs are mounted read-only.

```bash
git clone git@github.com:magiccpp/drain3-deployment.git
cd drain3-deployment
scripts/install-compose.sh              # only if `docker compose` is missing (user-local plugin, no sudo)
scripts/docker-up.sh                    # build, start, install the `logsum` client into ~/.local/bin, self-test
scripts/install-opencode-plugin.sh      # OpenCode
```

On WSL2 use `scripts/docker-up.sh --bind 0.0.0.0 --claude-hook-log /mnt/c/Users/<you>/.claude/hooks/logsum-hook.log`
so the Windows browser can reach the dashboard and Claude Code activity is shown.
Requires Docker with your user in the `docker` group (`sudo usermod -aG docker $USER`).

The `logsum` command on the host is a small client: it POSTs stdin to
`http://127.0.0.1:8765/summarize` and prints the reply. If the container is down
it falls back to the local Python summarizer when one is installed, otherwise it
passes the log through unchanged, so an agent never loses output. A call costs
about 35 ms against the container versus 200 ms for a fresh Python process.

```bash
scripts/docker-down.sh                  # stop; add --purge to drop the stats volume
docker compose logs -f logsum           # service log
curl -s localhost:8765/health
```

## Install without Docker

```bash
scripts/install.sh                      # uv + drain3 + wrappers + dashboard as a systemd user service, no sudo
scripts/install-opencode-plugin.sh
```

Then open <http://localhost:8765>. On WSL2, pass `--bind 0.0.0.0` to `install.sh`
so a Windows browser can reach it, and `--claude-hook-log /mnt/c/Users/<you>/.claude/hooks/logsum-hook.log`
so Claude Code activity shows up too. In this mode each call starts a Python
process that forks a detached child to record stats after the output is flushed.

### Claude Code on Windows (summarizer in WSL2)

```powershell
cd claude-code
.\install.ps1 -Distro Ubuntu-24.04     # copies the hook, writes its config, merges settings.json
```

Claude Code cannot modify tool output after the fact, so the hook rewrites
log-reading commands to `... | wsl.exe -d <distro> -- logsum`. It only touches
commands that read logs (journalctl, dmesg, docker/kubectl logs, cat/tail/Get-Content
on `*.log`, `/var/log`, `syslog`, `logs/`), and leaves alone follow mode, commands
that already end in a filter, real file redirects, and anything containing `nologsum`.

### OpenCode itself

```bash
curl -fsSL https://opencode.ai/install | bash
echo 'export PATH="$HOME/.opencode/bin:$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
opencode --version
```

The installer puts the binary in `~/.opencode/bin` but does not always add that
directory to your shell's PATH, so add the line yourself if `opencode` is not found.

### Provider keys

OpenCode enables a provider when its key is in the environment, or after
`opencode auth login`. It reads a `.env` only from the **project directory**, so a
key file in your home is invisible to the TUI unless your shell exports it. If
you keep keys in `~/.env` (`OPENAI_API_KEY=...` one per line), add this to
`~/.bashrc` and `~/.profile`, then open a new terminal:

```bash
if [ -f "$HOME/.env" ]; then set -a; . "$HOME/.env"; set +a; fi
```

Check with `opencode models openai | wc -l`: zero means the key is not visible.

### Model configuration (Terra for the main agent, Luna for delegated work)

```bash
scripts/install-opencode-config.sh      # copies opencode/opencode.jsonc to ~/.config/opencode/, backs up any existing one
```

`opencode/opencode.jsonc` sets `model` to `openai/gpt-5.6-terra` for the primary
agents (build, plan), `small_model` to `openai/gpt-5.6-luna` for housekeeping such
as titles, and puts the built-in `explore` and `general` subagents on Luna. It also
defines a `logs` subagent on Luna whose prompt tells it to read logs with bash (so
the plugin summarizes them) and report templates, counts and time spans instead of
raw lines. Ask the main agent to "delegate to the logs subagent" or let it pick the
agent from the description. Subagents run in child sessions, which is how the
dashboard tells them apart.

## Test

```bash
python3 scripts/make-sample-log.py > /tmp/app.log
logsum < /tmp/app.log | head            # 9 templates, then the last 10 lines
scripts/test-opencode.sh anthropic/claude-haiku-4-5   # or any provider/model OpenCode lists
```

The OpenCode test proves three things: the plugin audit log shows the
reduction, the session export contains the `[logsum]` header where the tool
result used to be, and the model's answer quotes the template counts.

## Dashboard

Tiles for commands seen, summaries, tokens before and after, percent saved and
estimated cost; a tokens-per-day chart; the latest summary as Drain3 saw it;
per-agent totals; recent summaries; and every shell command the hooks looked at
with the decision taken. Token counts are exact cl100k when tiktoken is installed
(it is, via `logsum/pyproject.toml`).

**OpenCode usage** is read straight from OpenCode's SQLite database
(`~/.local/share/opencode/opencode.db`, mounted read-only into the container and
opened with `immutable=1`). Every assistant message carries its provider, model,
agent, input, output, reasoning, cache-read and cache-write tokens and the cost
OpenCode computed. The dashboard shows:

- cost and token tiles for the selected range;
- tokens per day, main agent versus subagents;
- a table per **model endpoint and role**, so `openai/gpt-5.6-terra · main` and
  `openai/gpt-5.6-luna · subagent` are separate rows even inside one conversation;
- a table per **agent** (build, plan, explore, general, logs, ...) with the models
  it actually used.

A session whose `parent_id` is set is a subagent session; that is the whole
main-versus-subagent rule, and it holds no matter which model each side uses.
Set `LOGSUM_OPENCODE_DB` (or `OPENCODE_DATA` for the container) if the database
lives elsewhere.

## Tuning

`PASSTHROUGH_LINES`, `RARE_MAX` and `TAIL_LINES` at the top of `logsum.py`;
`MASKS` for the fields that vary in your logs (add request ids, trace ids,
usernames). Drain is line-based: group multi-line stack traces into one record
before mining or each frame becomes its own template.

## Remove

```bash
systemctl --user disable --now logsum-stats.service
rm ~/.config/systemd/user/logsum-stats.service ~/.local/bin/logsum ~/.local/bin/logsum-stats
rm ~/.config/opencode/plugins/logsum.js
rm -rf ~/.local/share/logsum
```
On Windows, remove the `PreToolUse` entry from `~/.claude/settings.json` (a backup
is written as `settings.json.before-logsum`).

## Notes from the benchmarks

- LLMLingua-2 (word-level compressor) runs at 35k tokens/s fp16 on an RTX 3090 but
  destroys code, logs and filenames. Wrong tool for agent output.
- RTK (per-command filters) is the best generic Bash-output reducer: pytest to 30%
  with every failing test kept; but it truncates grep/find and ignores logs.
- Tamp's default level mangled `git status` and `ls`; its lossless level is safe and
  its re-read diffing is excellent (47k tokens to 545).
- Drain3 turns 800 log lines into 9 templates; exact-line dedup (`rtk log`) saw 169
  "unique" errors because it does not mask timestamps and PIDs.

Details and numbers: `benchmarks/results/`.
