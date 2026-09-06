// OpenCode plugin: summarize log-like tool output with Drain3 (logsum) before the model sees it.
// Install: copy to ~/.config/opencode/plugins/logsum.js  (auto-loaded at startup).
// Runs after the tool, so it never changes the command that executes; it only replaces the text
// handed back to the model. Every inspected bash/read call is appended to the audit log
// (decision + command) so the stats dashboard can show activity, not just summaries.
import { execFileSync } from "node:child_process";
import { appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const LOGSUM = join(homedir(), ".local/bin/logsum");
const AUDIT = join(homedir(), ".config/opencode/logsum-plugin.log");
const MIN_LINES = 40; // logsum passes anything shorter through unchanged; skip the spawn entirely

const LOG_COMMANDS = [
  /\bjournalctl\b/i, /\bdmesg\b/i, /\bdocker(?:\s+compose)?\s+logs\b/i, /\bkubectl\s+logs\b/i,
  /\bpodman\s+logs\b/i, /\bpm2\s+logs\b/i, /\bheroku\s+logs\b/i, /\bgcloud\s+logging\s+read\b/i,
  /\baws\s+logs\s+(?:tail|get-log-events|filter-log-events)\b/i, /\blast\s+-f\b/i,
];
const READERS = /\b(?:cat|tail|head|less|more|bat|zcat)\b/i;
const LOG_PATHS = /(?:\.log\b|\.log\.\d+\b|\.out\b|\/var\/log\/|[\\/]logs?[\\/]|\bsyslog\b|\bmessages\b|\bjournal\b)/i;

function decide(cmd) {
  if (!cmd) return "inspect";
  const isLog = LOG_COMMANDS.some((re) => re.test(cmd)) || (READERS.test(cmd) && LOG_PATHS.test(cmd));
  if (!isLog) return "inspect";                       // not a log read: nothing to do
  if (/nologsum/i.test(cmd)) return "skip:optout";
  // only skip when the whole pipeline ends in a filter (the agent already reduced it)
  if (/\|\s*(?:grep|rg|awk|sed|jq|wc|sort|uniq|head|tail|cut)\b[^|;&]*$/i.test(cmd)) return "skip:filtered";
  return "rewrite";
}

function audit(decision, detail, cmd) {
  try { appendFileSync(AUDIT, `${new Date().toISOString()}\topencode\t${decision}\t${detail}\t${String(cmd || "").replace(/\s+/g, " ").slice(0, 300)}\n`); } catch {}
}

function summarize(text, cmd) {
  // agent name + base64 command go to the stats dashboard (logsum-stats)
  const env = { ...process.env, LOGSUM_AGENT: "opencode", LOGSUM_CMD_B64: Buffer.from(String(cmd || ""), "utf8").toString("base64") };
  return execFileSync(LOGSUM, { input: text, encoding: "utf8", timeout: 20000, maxBuffer: 64 * 1024 * 1024, env });
}

export const LogsumPlugin = async () => ({
  "tool.execute.after": async (input, output) => {
    try {
      const text = output && typeof output.output === "string" ? output.output : "";
      let cmd = null, decision = null;
      if (input.tool === "bash") {
        cmd = input.args && input.args.command;
        decision = decide(cmd);
      } else if (input.tool === "read") {
        cmd = `read ${input.args && input.args.filePath}`;
        decision = LOG_PATHS.test(String(input.args && input.args.filePath || "")) ? "rewrite" : "inspect";
      } else {
        return;
      }
      if (decision !== "rewrite") { audit(decision, input.tool, cmd); return; }
      if (!text || text.split("\n").length <= MIN_LINES) { audit("short", input.tool, cmd); return; }

      // read tool prints "NNNNN| line"; strip the prefix so templates are about the log, not the numbering
      const body = input.tool === "read" ? text.replace(/^\d+\|\s?/gm, "") : text;
      const summary = summarize(body, cmd);
      if (!summary || summary.length >= body.length) { audit("nogain", input.tool, cmd); return; }
      output.output = summary;
      output.metadata = { ...(output.metadata || {}), logsum: true, originalBytes: text.length };
      audit("rewrite", `${input.tool} ${text.length}->${summary.length}`, cmd);
    } catch (err) {
      // never break the tool: on any failure the model just gets the raw output
      audit("error", err && err.message, "");
    }
  },
});
