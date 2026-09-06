#!/usr/bin/env node
// Claude Code PreToolUse hook (matcher: Bash|PowerShell) for Windows + WSL2.
// If the shell command reads a log, pipe its output through the Drain3 summarizer (logsum) running in WSL2.
// Every inspected command is appended to logsum-hook.log (decision + command) so the stats dashboard
// can show activity even when nothing was summarized. Anything else: exit 0 with no output.
//
// Configuration: logsum-hook.config.json next to this file, written by install.ps1:
//   { "distro": "Ubuntu-24.04", "logsum": "/home/<user>/.local/bin/logsum", "agent": "claude-code" }
'use strict';
const fs = require('fs');
const path = require('path');

let cfg = { distro: 'Ubuntu-24.04', logsum: '/home/ken/.local/bin/logsum', agent: 'claude-code' };
try { cfg = { ...cfg, ...JSON.parse(fs.readFileSync(path.join(__dirname, 'logsum-hook.config.json'), 'utf8')) }; } catch {}
const LOG_FILE = path.join(__dirname, 'logsum-hook.log');
// The agent name and the (base64) command are passed as env so the stats dashboard can attribute the call.
const logsumFor = (cmd) => `wsl.exe -d ${cfg.distro} -- env LOGSUM_AGENT=${cfg.agent} ` +
  `LOGSUM_CMD_B64=${Buffer.from(cmd, 'utf8').toString('base64')} ${cfg.logsum}`;

// Commands whose output is a log stream (anywhere in the command, including inside an ssh/wsl quoted string).
const LOG_COMMANDS = [
  /\bjournalctl\b/i, /\bdmesg\b/i, /\bdocker(?:\s+compose)?\s+logs\b/i, /\bkubectl\s+logs\b/i,
  /\bpodman\s+logs\b/i, /\bpm2\s+logs\b/i, /\bheroku\s+logs\b/i, /\bgcloud\s+logging\s+read\b/i,
  /\baws\s+logs\s+(?:tail|get-log-events|filter-log-events)\b/i, /\blast\s+-f\b/i,
];
// File readers pointed at something that looks like a log file.
const READERS = /\b(?:Get-Content|gc|cat|type|tail|head|less|more|bat|zcat)\b/i;
const LOG_PATHS = /(?:\.log\b|\.log\.\d+\b|\.out\b|\/var\/log\/|[\\/]logs?[\\/]|\bsyslog\b|\bmessages\b|\bjournal\b)/i;

function decide(cmd) {
  if (typeof cmd !== 'string' || !cmd) return 'inspect';
  const isLog = LOG_COMMANDS.some(re => re.test(cmd)) || (READERS.test(cmd) && LOG_PATHS.test(cmd));
  if (!isLog) return 'inspect';                                                   // not a log read: nothing to do
  // From here on the command reads a log; the skip rules say why it is still left alone.
  if (cmd.length > 4000) return 'skip:size';
  if (/nologsum|\/logsum\b/i.test(cmd)) return 'skip:optout';                    // opt-out marker or already rewritten
  if (/\s(?:-f|-F|--follow|-Wait)\b/.test(cmd) && !/\blast\s+-f\b/i.test(cmd)) return 'skip:follow'; // streaming never ends
  // Only a real file redirect counts: "> path" not preceded by a digit or &, and not >> or >&.
  if (/(?<![\d&>])>(?![>&])\s*[^\s&|;)]/.test(cmd) && !/^\s*(?:Get-Content|cat|tail|head)\b/i.test(cmd)) return 'skip:redirect';
  // Only skip when the *whole* pipeline ends in a filter (the agent already reduced it).
  if (/\|\s*(?:grep|rg|Select-String|findstr|sls|awk|sed|jq|wc|sort|uniq|head|tail|cut|Select-Object|Measure-Object)\b[^|;&]*$/i.test(cmd)) return 'skip:filtered';
  return 'rewrite';
}

function rewrite(cmd, toolName) {
  if (toolName === 'PowerShell') {
    // PS 5.1 pipes to native exes in ASCII by default; force UTF-8 (no BOM) so nothing turns into '?'.
    return `$OutputEncoding=New-Object Text.UTF8Encoding $false; & { ${cmd} } 2>&1 | Out-String -Stream | ${logsumFor(cmd)}`;
  }
  return `{ ${cmd} ; } 2>&1 | ${logsumFor(cmd)}`;   // Bash (Git Bash on Windows)
}

function audit(toolName, decision, cmd) {
  try { fs.appendFileSync(LOG_FILE, `${new Date().toISOString()}\t${cfg.agent}\t${decision}\t${toolName}\t${cmd.replace(/\s+/g, ' ').slice(0, 300)}\n`); } catch {}
}

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', d => { input += d; });
process.stdin.on('end', () => {
  let data;
  try { data = JSON.parse(input.replace(/^﻿/, '')); } catch { process.exit(0); }
  const toolName = data.tool_name;
  const cmd = data.tool_input && data.tool_input.command;
  if ((toolName !== 'Bash' && toolName !== 'PowerShell') || typeof cmd !== 'string') process.exit(0);
  const decision = decide(cmd);
  audit(toolName, decision, cmd);
  if (decision !== 'rewrite') process.exit(0);
  const updated = rewrite(cmd, toolName);
  // On Windows, stdout to a pipe is async: never process.exit() right after writing or the JSON is truncated.
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecisionReason: 'logsum: log output summarized with Drain3 in WSL2',
      updatedInput: { ...data.tool_input, command: updated },
    },
  }) + '\n', () => { process.exitCode = 0; });
});
